"""#31 maker-rebate harvesting near 50c (and #33 maker variant) in 5-minute windows.
Quotes: decided from the kacho book at tick t (1 Hz), live during [t+1, t+2) (1 s posting latency), re-decided every second.
Fills: only when a later taker print (aliplayer1 websocket trades, ms timestamps) trades STRICTLY THROUGH our price; fill <= 0.5 x print size
(back-of-queue), <= remaining quote size. All prices in Up-equivalent terms: an Up-ask at a == a Down-bid at 1-a (books are mirrored).
Inventory capped at +-L shares of net Up exposure. All positions held to resolution (official outcome).
Rebate: pro-rata share of 20% fee pool == 0.2*0.07*p(1-p) per filled share if all takers pay the fee; reported at 100% and 50% of that."""
import numpy as np, pandas as pd, json, sys, os, duckdb, numba
from common import *

from maker_sim import sim, load_trades

con = duckdb.connect(); con.execute("set threads=2; set memory_limit='3GB'; set enable_progress_bar=false")
ali_m = market_map()
W = load_windows()
res = {}; allF = []
coins = sys.argv[1:] or ["btc", "eth", "sol", "xrp"]
for coin in coins:
    w = W[W.coin == coin].reset_index(drop=True); w["w"] = np.arange(len(w))
    P = load_panel(coin, W)[['w', 't', 'tau', 'bu', 'au']]
    P["mid"] = (P.bu + P.au) / 2
    tr = load_trades(con, coin, w, ali_m, EXT)
    covered = np.zeros(len(w), bool); covered[tr.w.unique()] = True
    cut = w.start[covered].quantile(0.6)
    print(coin, "trades", len(tr), "windows w/ trades", covered.sum(), "split", pd.to_datetime(cut, unit="s"), flush=True)
    # taker volume stats for capacity context
    trw = tr.w.to_numpy().astype(np.int64); trs = tr.tsec.to_numpy().astype(np.int64); tru = tr.upx.to_numpy(); trd = tr.dirn.to_numpy().astype(np.int64); trh = tr.sh.to_numpy()
    del tr
    wfirst = P.groupby("w").cumcount().to_numpy() == 0
    first_idx = np.full(len(w), -1, np.int64); first_idx[P.w[wfirst].to_numpy()] = np.nonzero(wfirst)[0]
    wn = np.bincount(P.w, minlength=len(w)).astype(np.int64)
    wstart = w.start.to_numpy().astype(np.int64)
    first_t = np.full(len(w), 0, np.int64); first_t[P.w[wfirst].to_numpy()] = P.t[wfirst].to_numpy()
    for (band, tau_stop, improve, L, fillrule) in [((0.35, 0.65), 60, False, 200, "through"), ((0.35, 0.65), 60, True, 200, "through"), ((0.35, 0.65), 120, False, 200, "through"),
                                         ((0.2, 0.8), 30, False, 200, "through"), ((0.35, 0.65), 60, False, 1000, "through"), ((0.05, 0.95), 0, False, 200, "through"),
                                         ((0.35, 0.65), 60, False, 200, "touch_q0.5"), ((0.35, 0.65), 60, False, 200, "touch_q0.1"), ((0.35, 0.65), 120, True, 200, "touch_q0.5"),
                                         ((0.35, 0.65), 60, False, 200, "through_qlag0"), ((0.35, 0.65), 60, False, 200, "touch_q0.5_qlag0"), ((0.35, 0.65), 120, True, 200, "touch_q0.5_qlag0")]:
        eps = 1e-9 if fillrule.startswith("through") else -1e-9
        qlag = 0 if fillrule.endswith("qlag0") else 1
        qs = 0.1 if "q0.1" in fillrule else 0.5
        spr = P.au - P.bu
        bidq = P.bu.to_numpy().copy(); askq = P.au.to_numpy().copy()
        if improve:
            wide = (spr >= 0.025).to_numpy()
            bidq[wide] += 0.01; askq[wide] -= 0.01
        act = (P.mid.between(*band) & (P.tau >= max(tau_stop, 1)) & (spr <= 0.05)).to_numpy()
        n = len(trw) // 2
        ow = np.zeros(n, np.int64); ot = np.zeros(n, np.int64); os_ = np.zeros(n, np.int64); op = np.zeros(n); osh = np.zeros(n)
        nf = sim(trw, trs, tru, trd, trh, first_idx, wn, first_t, bidq, askq, act, act, 50.0, float(L), qs, eps, ow, ot, os_, op, osh, qlag)
        F = pd.DataFrame({"w": ow[:nf], "t": ot[:nf], "side": os_[:nf], "px": op[:nf], "sh": osh[:nf]})
        F["up"] = w.up.to_numpy()[F.w]; F["start"] = wstart[F.w]
        F["oos"] = F.start >= cut
        # markouts using Up mid at t+5 / t+30 (rows are contiguous seconds per window)
        r0 = first_idx[F.w] + (F.t - first_t[F.w])
        midarr = P.mid.to_numpy()
        for h in (5, 30):
            rh = np.minimum(r0 + h, first_idx[F.w] + wn[F.w] - 1)
            F[f"m{h}"] = midarr[rh]
        F["mid0"] = midarr[r0]
        F["tau"] = P.tau.to_numpy()[r0]
        # pnl per fill (side +1: bought Up at px; side -1: sold Up at px == bought Down at 1-px)
        F["pnl_res"] = F.sh * F.side * (F.up - F.px)
        F["spread_cap"] = F.sh * F.side * (F.mid0 - F.px)
        F["mk5"] = F.sh * F.side * (F.m5 - F.px); F["mk30"] = F.sh * F.side * (F.m30 - F.px)
        pe = np.where(F.side > 0, F.px, 1 - F.px)
        F["rebate"] = REBATE_SHARE * FEE_RATE * pe * (1 - pe) * F.sh
        F["cost"] = F.sh * pe
        F["coin"] = coin; F["variant"] = f"band{band}_stop{tau_stop}_imp{int(improve)}_L{L}_{fillrule}"
        os.makedirs(f"{OUT}/idea31", exist_ok=True)
        F.drop(columns=['m5', 'm30']).astype({c: np.float32 for c in ['px', 'sh', 'pnl_res', 'spread_cap', 'mk5', 'mk30', 'rebate', 'cost', 'mid0']}).to_parquet(
            f"{OUT}/idea31/fills_{coin}_{F.variant.iloc[0].replace(' ', '')}.parquet", index=False)
        for o in (False, True):
            g = F[F.oos == o]
            if len(g) == 0:
                continue
            days = g.start.nunique() * 300 / 86400
            print(f"  {F.variant.iloc[0]} {'OOS' if o else 'IS '} fills={len(g)} sh={g.sh.sum():.0f} spread_cap/sh={g.spread_cap.sum()/g.sh.sum():.4f} "
                  f"mk5/sh={g.mk5.sum()/g.sh.sum():.4f} mk30/sh={g.mk30.sum()/g.sh.sum():.4f} res/sh={g.pnl_res.sum()/g.sh.sum():.4f} "
                  f"rebate/sh={g.rebate.sum()/g.sh.sum():.4f} pnl+reb/day={(g.pnl_res.sum()+g.rebate.sum())/days:.1f}", flush=True)
    del P

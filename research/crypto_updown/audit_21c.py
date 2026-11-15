"""Audit of #21c (BTC 5m, 2026-03-24..04-26 where ms prints exist).
(3) Stale-quote persistence: reference = last same-side print before the Binance event T (within 5 s). Do same-side prints at <= that
    stale price still happen at match time >= T + 250 ms (then-current taker delay) + 300 ms?  -> share of events, shares available.
(2) Book-fill confirmation: book fill = kacho ask at first 1 Hz sample s >= T+L (sample instant ~ s+0.5 s, see audit_kacho_lag.csv).
    'confirmed' if a real same-side print at <= that ask happens within [s+0.5 s, s+2 s]. Also a conservative price =
    max(book ask, first same-side print after s+0.5 s).  ROI for all / confirmed / conservative."""
import numpy as np, pandas as pd, duckdb, json
from common import *
from maker_sim import load_trades
W = load_windows(); w = W[W.coin == "btc"].reset_index(drop=True); w["w"] = np.arange(len(w))
E = pd.read_parquet(f"{OUT}/idea21c_events.parquet").drop_duplicates(["thr", "L", "T"])
E = E[(E.thr == 5) & E.L.isin([500, 1000]) & (E["T"] < 1777226000000)]
E = E[~w.bad_date.to_numpy()[E.w]]
P = pd.read_parquet(f"{OUT}/panel_btc.parquet", columns=["w", "t", "au", "ad", "sau", "su"])
isf = P.groupby("w").cumcount().to_numpy() == 0
fi = np.full(len(w), -1, np.int64); fi[P.w[isf].to_numpy()] = np.nonzero(isf)[0]
ft = np.zeros(len(w), np.int64); ft[P.w[isf].to_numpy()] = P.t[isf].to_numpy(); wn = np.bincount(P.w, minlength=len(w))
con = duckdb.connect(); con.execute("set threads=2; set memory_limit='2GB'; set enable_progress_bar=false")
tr = load_trades(con, "btc", w, market_map(), EXT)
tr = tr[tr.w.isin(E.w.unique())].sort_values(["w", "ts"])
byw = {k: (g.ts.to_numpy(), g.dirn.to_numpy(), g.upx.to_numpy(), g.sh.to_numpy()) for k, g in tr.groupby("w")}
rows = []
for e in E.itertuples(index=False):
    if e.w not in byw:
        continue
    ts, dr, ux, sh = byw[e.w]
    side = e.side; pr = np.where(side > 0, ux, 1 - ux); same = dr == side
    T = int(e.T)
    i0 = np.searchsorted(ts, T - 5000); i1 = np.searchsorted(ts, T)
    pre = np.nonzero(same[i0:i1])[0]
    p_pre = pr[i0 + pre[-1]] if len(pre) else np.nan
    j0 = np.searchsorted(ts, T + 550); j1 = np.searchsorted(ts, T + 2000)
    m = same[j0:j1] & (pr[j0:j1] <= p_pre + 1e-9) if not np.isnan(p_pre) else np.zeros(0, bool)
    stale_n = int(m.sum()); stale_sh = float(sh[j0:j1][m].sum()) if stale_n else 0.0
    # book fill
    s = -(-(T + e.L) // 1000); off = s - ft[e.w]
    if not (0 <= off < wn[e.w]):
        continue
    r = fi[e.w] + off
    bpx = P.au.to_numpy()[r] if side > 0 else P.ad.to_numpy()[r]
    bsz = P.sau.to_numpy()[r] if side > 0 else P.su.to_numpy()[r]
    k0 = np.searchsorted(ts, s * 1000 + 500); k1 = np.searchsorted(ts, s * 1000 + 2000)
    mm = same[k0:k1]
    conf = bool((mm & (pr[k0:k1] <= bpx + 1e-9)).any())
    nxt = np.nonzero(mm)[0]
    cons = max(bpx, pr[k0 + nxt[0]]) if len(nxt) else bpx
    rows.append((e.L, T, e.w, side, e.start, e.win, e.oos, p_pre, stale_n, stale_sh, bpx, bsz, conf, cons))
A = pd.DataFrame(rows, columns=["L", "T", "w", "side", "start", "win", "oos", "p_pre", "stale_n", "stale_sh", "bpx", "bsz", "conf", "cons_px"])
A.to_parquet(f"{OUT}/audit_21c.parquet", index=False)
res = {}
for L, g in A.groupby("L"):
    g1 = g[g.p_pre.notna()]
    res[f"L{L}_stale_persist"] = {"events_with_pre_print": len(g1), "share_with_stale_print_after_T+550ms": float((g1.stale_n > 0).mean()),
                                  "median_stale_shares_if_any": float(g1[g1.stale_n > 0].stale_sh.median())}
    for lab, sel, pxcol in (("all", np.ones(len(g), bool), "bpx"), ("confirmed", g.conf.to_numpy(), "bpx"), ("conservative_px", np.ones(len(g), bool), "cons_px")):
        x = g[sel & g.bpx.between(0.01, 0.99) & (g.bsz > 0)].copy()
        x["price"] = x[pxcol]; x = x[x.price.between(0.01, 0.99)]
        x["shares"] = np.minimum(x.bsz, 100); x["fee"] = x.shares * fee_ps(x.price); x["cost"] = x.shares * x.price + x.fee
        x["pnl"] = x.shares * (x.win - x.price) - x.fee; x["cluster"] = x.start; x["t_entry"] = x["T"] // 1000; x["t_exit"] = x.start + 300
        for o in (False, True):
            s_ = summ(x[x.oos == o])
            res[f"L{L}_{lab}_{'oos' if o else 'is'}"] = {k: s_.get(k) for k in ("n_trades", "roi", "roi_ci95", "p_roi_le_0", "pnl_per_day")}
            print(L, lab, "OOS" if o else "IS", res[f"L{L}_{lab}_{'oos' if o else 'is'}"])
    print(L, "confirmed share", g.conf.mean().round(3), res[f"L{L}_stale_persist"])
json.dump(res, open(f"{OUT}/audit_21c.json", "w"), indent=1, default=float)

"""#21c robustness: fill every Binance-jump event at the RECORDED BOOK ask (kacho 1 Hz) at the first sampled second >= T+L
(effective latency L..L+1000 ms), size <= displayed best ask size (cap 100 sh). Removes the selection on 'a print happened'."""
import numpy as np, pandas as pd, json, sys
from common import *
COIN = sys.argv[1] if len(sys.argv) > 1 else "btc"
W = load_windows(); w = W[W.coin == COIN].reset_index(drop=True)
P = pd.read_parquet(f"{OUT}/panel_{COIN}.parquet", columns=["w", "t", "au", "ad", "sau", "su"])
isf = P.groupby("w").cumcount().to_numpy() == 0
first_idx = np.full(len(w), -1, np.int64); first_idx[P.w[isf].to_numpy()] = np.nonzero(isf)[0]
first_t = np.zeros(len(w), np.int64); first_t[P.w[isf].to_numpy()] = P.t[isf].to_numpy()
wn = np.bincount(P.w, minlength=len(w))
E = pd.read_parquet(f"{OUT}/idea21c_events{'' if COIN == 'btc' else '_' + COIN}.parquet")
E = E.drop_duplicates(["thr", "L", "T"])
sec = -(-(E["T"].to_numpy() + E.L.to_numpy()) // 1000)  # ceil
wi = E.w.to_numpy(); off = sec - first_t[wi]; ok = (off >= 0) & (off < wn[wi])
r = np.where(ok, first_idx[wi] + np.clip(off, 0, None), 0)
up = E.side.to_numpy() > 0
E["bpx"] = np.where(ok, np.where(up, P.au.to_numpy()[r], P.ad.to_numpy()[r]), np.nan)
E["bsz"] = np.where(ok, np.where(up, P.sau.to_numpy()[r], P.su.to_numpy()[r]), np.nan)
E["bad"] = w.bad_date.to_numpy()[E.w]
E["period"] = np.where(~E.oos, "IS", np.where(pd.to_datetime(E["T"], unit="ms") < "2026-04-27", "OOS1", "OOS2_heldout"))
F = E[E.bpx.between(0.01, 0.99) & (E.bsz > 0) & ~E.bad].copy()
F["sh"] = np.minimum(F.bsz, 100.0)
res = {}
for slip in (0.0, 0.01):
    F["px"] = F.bpx + slip
    F["fee"] = F.sh * fee_ps(F.px); F["cost"] = F.sh * F.px + F.fee; F["pnl"] = F.sh * (F.win - F.px) - F.fee
    F["cluster"] = F.start; F["t_entry"] = F["T"] // 1000; F["t_exit"] = F.start + 300; F["shares"] = F.sh; F["price"] = F.px
    for (thr, L, o), g in F.groupby(["thr", "L", "period"]):
        s = summ(g); res[f"book_slip{slip}_thr{thr}_L{L}_{o}"] = s
        print(f"book+{slip:.2f} thr={thr:>2} L={L:>4} {o:>12} n={len(g):>5} px={g.px.mean():.3f} win={g.win.mean():.3f} ROI={s['roi']:+.4f} "
              f"CI={np.round(s['roi_ci95'], 4)} p={s['p_roi_le_0']:.3f} pnl/day={s['pnl_per_day']:.0f} avg_sh={g.sh.mean():.0f}")
json.dump(res, open(f"{OUT}/idea21c_book{'' if COIN == 'btc' else '_' + COIN}.json", "w"), indent=1, default=float)

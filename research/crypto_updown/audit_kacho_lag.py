"""Audit (A1/A2): alignment of aliplayer websocket print times (server ms) with kacho 1 Hz book samples.
For small taker prints (<=50 sh) the print price equals the best opposite quote at match time. For shifts d in -3..+3 s we measure
P(print price == kacho best ask (taker buy) / best bid (taker sell) at second floor(t)+d). The peak tells how kacho's sample at
second s relates to real time; the share of prints that trade BELOW the displayed ask (buy) of the same/previous sample measures staleness."""
import numpy as np, pandas as pd, duckdb
from common import *
from maker_sim import load_trades
W = load_windows(); w = W[W.coin == "btc"].reset_index(drop=True); w["w"] = np.arange(len(w))
P = pd.read_parquet(f"{OUT}/panel_btc.parquet", columns=["w", "t", "bu", "au"])
isf = P.groupby("w").cumcount().to_numpy() == 0
fi = np.full(len(w), -1, np.int64); fi[P.w[isf].to_numpy()] = np.nonzero(isf)[0]
ft = np.zeros(len(w), np.int64); ft[P.w[isf].to_numpy()] = P.t[isf].to_numpy(); wn = np.bincount(P.w, minlength=len(w))
con = duckdb.connect(); con.execute("set threads=2; set memory_limit='2GB'; set enable_progress_bar=false")
tr = load_trades(con, "btc", w, market_map(), EXT)
tr = tr[(tr.sh <= 50)].sample(400000, random_state=0)
bu = P.bu.to_numpy(); au = P.au.to_numpy()
rows = []
for d in range(-3, 4):
    sec = tr.tsec.to_numpy() + d; wi = tr.w.to_numpy(); off = sec - ft[wi]; ok = (off >= 0) & (off < wn[wi])
    r = np.where(ok, fi[wi] + np.clip(off, 0, None), 0)
    buy = tr.dirn.to_numpy() > 0; px = tr.upx.to_numpy()
    q = np.where(buy, au[r], bu[r])
    eq = np.abs(q - px) < 1e-6
    better = np.where(buy, px < q - 1e-6, px > q + 1e-6)  # print at a better price than the displayed quote
    rows.append({"shift_s": d, "n": int(ok.sum()), "p_equal": float(eq[ok].mean()), "p_print_better_than_display": float(better[ok].mean()),
                 "within_tick_ms": None})
R = pd.DataFrame(rows); print(R.to_string())
# within-second position: does equality depend on the ms within the second (kacho sample instant)?
d = 0; sec = tr.tsec.to_numpy(); wi = tr.w.to_numpy(); off = sec - ft[wi]; ok = (off >= 0) & (off < wn[wi]) & (off + 1 < wn[wi])
r = np.where(ok, fi[wi] + np.clip(off, 0, None), 0)
buy = tr.dirn.to_numpy() > 0; px = tr.upx.to_numpy(); ms = tr.ts.to_numpy() % 1000
for k, lab in ((0, "same second s"), (1, "next second s+1")):
    q = np.where(buy, au[r + k], bu[r + k]); eq = np.abs(q - px) < 1e-6
    print(lab, {f"{a}-{a+250}ms": round(float(eq[ok & (ms >= a) & (ms < a + 250)].mean()), 3) for a in (0, 250, 500, 750)})
R.to_csv(f"{OUT}/audit_kacho_lag.csv", index=False)

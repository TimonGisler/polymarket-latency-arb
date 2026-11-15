"""(A3) persistence curve: share of >=5 bp Binance events (BTC 5m, 03-24..04-26) where a same-side print still trades at <= the last
pre-event same-side print price (i.e. a stale quote) with match time in [T+X, T+X+1000ms], and the stale shares available."""
import numpy as np, pandas as pd, duckdb, json
from common import *
from maker_sim import load_trades
W = load_windows(); w = W[W.coin == "btc"].reset_index(drop=True); w["w"] = np.arange(len(w))
E = pd.read_parquet(f"{OUT}/idea21c_events.parquet").drop_duplicates(["thr", "T"])
E = E[(E.thr == 5) & (E["T"] < 1777226000000)]; E = E[~w.bad_date.to_numpy()[E.w]]
con = duckdb.connect(); con.execute("set threads=2; set memory_limit='2GB'; set enable_progress_bar=false")
tr = load_trades(con, "btc", w, market_map(), EXT); tr = tr[tr.w.isin(E.w.unique())].sort_values(["w", "ts"])
byw = {k: (g.ts.to_numpy(), g.dirn.to_numpy(), g.upx.to_numpy(), g.sh.to_numpy()) for k, g in tr.groupby("w")}
Xs = [0, 150, 300, 550, 1000, 1500, 2500]
rows = []
for e in E.itertuples(index=False):
    if e.w not in byw: continue
    ts, dr, ux, sh = byw[e.w]; side = e.side; pr = np.where(side > 0, ux, 1 - ux); same = dr == side; T = int(e.T)
    i0, i1 = np.searchsorted(ts, [T - 5000, T]); pre = np.nonzero(same[i0:i1])[0]
    if not len(pre): continue
    p_pre = pr[i0 + pre[-1]]
    row = {}
    for X in Xs:
        j0, j1 = np.searchsorted(ts, [T + X, T + X + 1000]); m = same[j0:j1] & (pr[j0:j1] <= p_pre + 1e-9)
        row[X] = float(sh[j0:j1][m].sum())
    rows.append(row)
A = pd.DataFrame(rows)
out = {f"T+{X}ms..+1s": {"share_events_with_stale_fill": float((A[X] > 0).mean()), "mean_stale_shares": float(A[X].mean())} for X in Xs}
out["n_events"] = len(A)
print(json.dumps(out, indent=1)); json.dump(out, open(f"{OUT}/audit_stale_curve.json", "w"), indent=1)

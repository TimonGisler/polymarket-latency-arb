"""Print-confirmation of simulated taker fills: a fill at (coin, window w, second t_entry, side, price) is 'confirmed' if a real trade print
(aliplayer1 websocket ticks) on the same outcome traded at <= our price (Up-equivalent: >= 1-price on the other token) within [t_entry-1, t_entry+2) s.
Only windows covered by ali ticks (<= 2026-04-26) can be checked."""
import numpy as np, pandas as pd, duckdb
from common import *
from maker_sim import load_trades

def confirm(T, coins=("btc", "eth", "sol", "xrp")):
    con = duckdb.connect(); con.execute("set threads=2; set memory_limit='3GB'; set enable_progress_bar=false")
    ali_m = market_map()
    W = load_windows()
    out = []
    for coin in coins:
        X = T[T.coin == coin].copy()
        if X.empty:
            continue
        w = W[W.coin == coin].reset_index(drop=True); w["w"] = np.arange(len(w))
        tr = load_trades(con, coin, w, ali_m, EXT)
        covered = np.zeros(len(w), bool); covered[tr.w.unique()] = True
        X["checkable"] = covered[X.w.astype(int)]
        # best (lowest) Up-equivalent price at which Up was bought / highest at which Up was sold, per (w, second)
        g = tr.groupby(["w", "tsec"]).upx.agg(["min", "max"]).reset_index()
        key = dict(zip(zip(g.w, g.tsec), zip(g["min"], g["max"])))
        conf = []
        for r in X.itertuples(index=False):
            ok = False
            if r.checkable:
                for s in range(int(r.t_entry) - 1, int(r.t_entry) + 2):
                    mm = key.get((int(r.w), s))
                    if mm is None:
                        continue
                    # buying Up at price p confirmed if some print at Up-eq <= p; buying Down at q confirmed if a print at Up-eq >= 1-q
                    if (r.side == "up" and mm[0] <= r.price + 1e-9) or (r.side == "dn" and mm[1] >= 1 - r.price - 1e-9):
                        ok = True; break
            conf.append(ok)
        X["confirmed"] = conf
        out.append(X)
    return pd.concat(out) if out else T.iloc[:0]

"""Per-window table: opening book, kacho outcome, Binance open/close, Chainlink open/close (where available), ali resolution."""
import numpy as np, pandas as pd, duckdb
from common import *

ali = pd.read_parquet(f"{EXT}/ali/markets.parquet", columns=["condition_id", "resolution", "timeframe", "fee_rate_bps"])
ali = ali[ali.timeframe == "5-minute"].drop(columns="timeframe")
con = duckdb.connect(); con.execute("set threads=2; set memory_limit='3GB'")
cl = con.sql(f"select ts_ms, symbol, price from '{EXT}/ali/spot_prices.parquet' where source='chainlink'").df()
rows = []
for coin in COINS:
    m = load_markets(coin)
    t = load_ticks(coin, ["condition_id", "t", "bu", "au", "bd", "ad", "sau", "sad"])
    t = t.merge(m[["condition_id", "start", "end"]], on="condition_id")
    t["el"] = t["t"] - t["start"]
    first = t[t.el.between(0, 3)].sort_values("t").groupby("condition_id").first()
    last = t.sort_values("t").groupby("condition_id").last()
    w = m[["condition_id", "event_id", "slug", "start", "end", "outcome", "n_ticks", "volume"]].copy()
    w["coin"] = coin
    w = w.join(first[["bu", "au", "bd", "ad", "el"]].rename(columns=lambda c: "o_" + c), on="condition_id")
    w = w.join(last[["bu", "au", "el"]].rename(columns=lambda c: "l_" + c), on="condition_id")
    if coin in BINANCE:
        s = load_binance(coin)
        w["bn_open"] = s.reindex(w["start"] - 1).to_numpy()
        w["bn_close"] = s.reindex(w["end"] - 1).to_numpy()
    sym = coin + "/usd"
    c = cl[cl.symbol == sym].sort_values("ts_ms")
    if len(c):
        cts = c["ts_ms"].to_numpy(); cp = c["price"].to_numpy()
        for col, b in [("cl_open", "start"), ("cl_close", "end")]:
            ms = w[b].to_numpy() * 1000
            i = np.searchsorted(cts, ms, side="right") - 1
            ok = (i >= 0) & (ms - cts[np.clip(i, 0, None)] <= 5000) & (ms <= cts[-1])
            w[col] = np.where(ok, cp[np.clip(i, 0, None)], np.nan)
    rows.append(w)
W = pd.concat(rows, ignore_index=True)
W = W.merge(ali, on="condition_id", how="left")
W["up_kacho"] = W.outcome.map({"Up": 1, "Down": 0})
W["up_bn"] = np.where(W.bn_open.notna(), (W.bn_close >= W.bn_open).astype(float), np.nan)
W["up_cl"] = np.where(W.cl_open.notna() & W.cl_close.notna(), (W.cl_close >= W.cl_open).astype(float), np.nan)
W["up_ali"] = W.resolution.where(W.resolution >= 0)
W.to_parquet(f"{OUT}/windows.parquet", index=False)
print(len(W))
# agreement
for a, b in [("up_kacho", "up_cl"), ("up_kacho", "up_ali"), ("up_cl", "up_ali"), ("up_bn", "up_cl"), ("up_bn", "up_ali"), ("up_bn", "up_kacho")]:
    x = W[[a, b, "coin"]].dropna()
    print(a, b, len(x), round((x[a] == x[b]).mean(), 4), x.groupby("coin").apply(lambda d: round((d[a] == d[b]).mean(), 4)).to_dict())

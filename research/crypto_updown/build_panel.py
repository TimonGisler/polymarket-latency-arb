"""Per-second panel per coin: kacho book + Binance spot features known at time t.
S_t = close of the Binance 1s kline that opened at t-1 (fully known at t).  K = Binance price at window start (close of kline start-1).
Realized vol from 1s log returns, trailing 300 s and 3600 s windows, ending at t-1."""
import numpy as np, pandas as pd, sys
from common import *

W = pd.read_parquet(f"{OUT}/windows.parquet")
for coin in sys.argv[1:] or COINS:
    m = W[W.coin == coin][["condition_id", "start", "end"]].reset_index(drop=True)
    m["w"] = np.arange(len(m), dtype=np.int32)
    t = load_ticks(coin, ["condition_id", "t", "bu", "au", "bd", "ad", "su", "sau", "du", "dd"])
    t = t.merge(m, on="condition_id").drop(columns="condition_id")
    t["tau"] = (t["end"] - t["t"]).astype(np.int16)
    t = t[(t.t >= t.start) & (t.t < t.end)]
    if coin in BINANCE:
        s = load_binance(coin)
        r = np.log(s).diff()
        v300 = (r ** 2).rolling(300, min_periods=200).mean()
        v3600 = (r ** 2).rolling(3600, min_periods=2000).mean()
        S = s.reindex(t["t"] - 1).to_numpy()
        K = s.reindex(t["start"] - 1).to_numpy()
        t["S"] = S; t["K"] = K
        t["sig300"] = np.sqrt(v300.reindex(t["t"] - 1).to_numpy())
        t["sig3600"] = np.sqrt(v3600.reindex(t["t"] - 1).to_numpy())
        # spot return over last 1/5/30 s (momentum features)
        for k in (1, 5, 30):
            t[f"r{k}"] = np.log(S / s.reindex(t["t"] - 1 - k).to_numpy())
    t = t.sort_values(["w", "t"]).drop(columns=["end"])
    for c in t.columns:
        if t[c].dtype == np.float64:
            t[c] = t[c].astype(np.float32) if c not in ("S", "K") else t[c]
    t.to_parquet(f"{OUT}/panel_{coin}.parquet", index=False)
    print(coin, len(t), flush=True)

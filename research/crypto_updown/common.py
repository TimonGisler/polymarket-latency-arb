"""Shared loaders for the crypto up/down study."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import numpy as np, pandas as pd, os
EXT = ROOT + "/data/ext/crypto"
OUT = ROOT + "/data/ext/crypto/work"  # big intermediates; small json/csv results are copied to research/crypto_updown/out
os.makedirs(OUT, exist_ok=True)
COINS = ["btc", "eth", "sol", "xrp", "doge", "bnb", "hype"]
BINANCE = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT", "doge": "DOGEUSDT", "bnb": "BNBUSDT"}
FEE_RATE = 0.07  # crypto taker fee rate (today's schedule)
REBATE_SHARE = 0.20


def fee_ps(p):
    """taker fee per share at price p"""
    return FEE_RATE * p * (1 - p)


def load_markets(coin):
    m = pd.read_parquet(f"{EXT}/kacho/{coin}_markets.parquet")
    m["start"] = m["market_start"].astype("int64") // 10**9 if m["market_start"].dtype != "int64" else m["market_start"]
    m["start"] = pd.to_datetime(m["market_start"]).astype("int64") // 10**9
    m["end"] = pd.to_datetime(m["market_end"]).astype("int64") // 10**9
    return m


def load_ticks(coin, cols=None):
    t = pd.read_parquet(f"{EXT}/kacho/{coin}_ticks.parquet", columns=cols)
    return t


def load_binance(coin):
    """Series indexed by second s: last traded price strictly before s+1 (close of 1s kline opened at s)."""
    b = pd.read_parquet(f"{EXT}/binance1s/{BINANCE[coin]}.parquet", columns=["ts", "close"])
    s = b.set_index("ts")["close"]
    full = np.arange(s.index.min(), s.index.max() + 1)
    return s.reindex(full).ffill()


def load_windows():
    """windows with best official outcome: gamma outcomePrices > ali resolution > chainlink-derived > kacho final-tick."""
    W = pd.read_parquet(f"{OUT}/windows.parquet")
    if os.path.exists(f"{OUT}/gamma_res.parquet"):
        g = pd.read_parquet(f"{OUT}/gamma_res.parquet")[["slug", "up_gamma"]]
        W = W.merge(g, on="slug", how="left")
    else:
        W["up_gamma"] = np.nan
    W["up"] = W.up_gamma.fillna(W.up_ali).fillna(W.up_cl).fillna(W.up_kacho)
    # chronological 60/40 split per coin
    q = W.groupby("coin").start.transform(lambda s: s.quantile(0.6))
    W["oos"] = W.start >= q
    # data-quality exclusion: 2026-04-29..05-04 the kacho books of several coins stop converging at window end
    # (final mid on the wrong side of the official outcome in up to 30% of windows vs ~1-2% normally) -> stale recorder books.
    d = pd.to_datetime(W.start, unit="s")
    W["bad_date"] = (d >= "2026-04-29") & (d < "2026-05-05")
    return W


def load_panel(coin, W=None):
    P = pd.read_parquet(f"{OUT}/panel_{coin}.parquet")
    if W is None:
        W = load_windows()
    w = W[W.coin == coin].reset_index(drop=True)  # same order as build_panel (w index)
    P["up"] = w["up"].to_numpy()[P["w"].to_numpy()]
    P["oos"] = w["oos"].to_numpy()[P["w"].to_numpy()]
    P["bad_date"] = w["bad_date"].to_numpy()[P["w"].to_numpy()]
    # seconds since the Up BBO (bid, ask) last changed within the window (real-time staleness, no look-ahead)
    chg = (P["bu"].diff() != 0) | (P["au"].diff() != 0) | (P["w"].diff() != 0)
    grp = chg.cumsum()
    P["age"] = P.groupby(grp).cumcount().astype(np.int16)
    return P


def taker_sim(P, sig_up, sig_dn, lat=1, tol=0.0, cap_usd=500.0, one_shot=True, extra_slip=0.0, fee_mult=1.0, cooldown=10):
    """Taker replay. Decision at row i (time t) -> marketable limit at the ask seen at t (+tol);
    executes on row i+lat (time t+lat) at that row's ask if ask_{i+lat} <= ask_i + tol; size <= displayed best size, <= cap_usd.
    one_shot: first executed trade per window only; else re-enter at most every `cooldown` s.
    Returns trades DataFrame (one row per fill)."""
    w = P["w"].to_numpy(); t = P["t"].to_numpy(); n = len(P)
    au = P["au"].to_numpy(); ad = P["ad"].to_numpy(); sau = np.nan_to_num(P["sau"].to_numpy()); sad = np.nan_to_num(P["su"].to_numpy())
    up = P["up"].to_numpy(); tau = P["tau"].to_numpy(); start = P["start"].to_numpy()
    j = np.arange(n) + lat
    ok = j < n
    jj = np.minimum(j, n - 1)
    ok &= (w[jj] == w) & (t[jj] == t + lat)
    out = []
    for side, sig, ask, sz in (("up", sig_up, au, sau), ("dn", sig_dn, ad, sad)):
        px = ask[jj]
        ex = sig & ok & (px <= ask + tol + 1e-9) & (sz[jj] > 0) & (px < 0.995)
        idx = np.nonzero(ex)[0]
        if len(idx) == 0:
            continue
        d = pd.DataFrame({"i": idx, "w": w[idx], "t": t[idx]})
        if one_shot:
            d = d.groupby("w").head(1)
        else:
            keep = []; lastw = -1; lastt = -10**9
            for r in d.itertuples(index=False):
                if r.w != lastw or r.t - lastt >= cooldown:
                    keep.append(r.i); lastw, lastt = r.w, r.t
            d = d[d.i.isin(keep)]
        i = d.i.to_numpy(); k = jj[i]
        price = px[i] + extra_slip
        sh = np.minimum(sz[k], cap_usd / price)
        fee = sh * FEE_RATE * fee_mult * price * (1 - price)
        win = up[i] if side == "up" else 1 - up[i]
        cost = sh * price + fee
        out.append(pd.DataFrame({"w": w[i], "cluster": start[i], "t_entry": t[k], "t_exit": start[i] + 300, "tau": tau[i], "side": side,
                                 "price": price, "shares": sh, "fee": fee, "cost": cost, "pnl": sh * win - cost, "win": win}))
    if not out:
        return pd.DataFrame(columns=["w", "cluster", "t_entry", "t_exit", "tau", "side", "price", "shares", "fee", "cost", "pnl", "win"])
    T = pd.concat(out, ignore_index=True).sort_values(["w", "t_entry"])
    if one_shot:
        T = T.groupby("w").head(1)
    return T


def summ(T, name=""):
    import sys
    sys.path.insert(0, ROOT)
    from pmbt.metrics import summarize
    if len(T) == 0:
        return {"name": name, "n_trades": 0}
    s = summarize(T, name=name, split=False, n_boot=1000)
    s["pnl_per_share"] = float(T.pnl.sum() / T.shares.sum())
    s["avg_price"] = float((T.price * T.shares).sum() / T.shares.sum())
    return s


def market_map():
    """market_id (gamma id, as used by aliplayer1 ticks) -> condition_id; aliplayer1 markets.parquet (to 2026-04-20) + gamma lookups for kacho windows."""
    a = pd.read_parquet(f"{EXT}/ali/markets.parquet", columns=["market_id", "condition_id"])
    if os.path.exists(f"{OUT}/gamma_ids.parquet"):
        a = pd.concat([a, pd.read_parquet(f"{OUT}/gamma_ids.parquet")]).drop_duplicates("market_id")
    return a

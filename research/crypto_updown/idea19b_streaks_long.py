"""#19 on 15-minute / 1-hour / 4-hour windows (BTC/ETH/SOL/XRP, Dec 2025 - Apr 2026) from aliplayer1 markets + CLOB price history.
Opening price = first CLOB history price (last-trade/mid, NOT executable) within 60 s after window start; outcome = official gamma outcomePrices.
Test: realized P(Up) - opening price conditional on the previous-k streak; trade = buy the side at open price + 0.5c half-spread + fee."""
import numpy as np, pandas as pd, json
from common import *
g = pd.read_parquet(f"{OUT}/gamma_res_ali.parquet")[["condition_id", "up_gamma"]]
m = pd.read_parquet(f"{EXT}/ali/markets.parquet")
m = m[m.timeframe.isin(["15-minute", "1-hour", "4-hour"]) & m.crypto.isin(["BTC", "ETH", "SOL", "XRP"])].merge(g, on="condition_id")
L = {"15-minute": 900, "1-hour": 3600, "4-hour": 14400}
m["len"] = m.timeframe.map(L); m["wstart"] = m.end_ts - m["len"]
rows = []
for (c, tf), mm in m.groupby(["crypto", "timeframe"]):
    p = pd.read_parquet(f"{EXT}/ali/prices/{c}_{tf}.parquet", columns=["market_id", "timestamp", "up_price"])
    p = p.merge(mm[["market_id", "wstart"]], on="market_id")
    p = p[(p.timestamp >= p.wstart) & (p.timestamp <= p.wstart + 60)].sort_values("timestamp").groupby("market_id").first()
    x = mm.join(p[["up_price"]], on="market_id").sort_values("wstart").drop_duplicates("wstart")
    up = x.up_gamma.to_numpy(); st = x.wstart.to_numpy(); r = np.zeros(len(x), int)
    for i in range(1, len(x)):
        if st[i] - st[i - 1] != x["len"].iloc[0] or np.isnan(up[i - 1]):
            continue
        prev = 1 if up[i - 1] == 1 else -1
        r[i] = r[i - 1] + prev if np.sign(r[i - 1]) == prev else prev
    x["streak"] = r
    rows.append(x)
X = pd.concat(rows).dropna(subset=["up_gamma", "up_price"])
X["oos"] = X.groupby(["crypto", "timeframe"]).wstart.transform(lambda s: s >= s.quantile(0.6))
X["sk"] = X.streak.clip(-4, 4)
tab = X.groupby(["timeframe", "oos", "sk"]).agg(n=("up_gamma", "size"), p_up=("up_gamma", "mean"), open_px=("up_price", "mean")).round(4)
tab["bias"] = (tab.p_up - tab.open_px).round(4)
print(tab.to_string())
# trade rule: buy Up if model(streak)-ask-fee>0 using IS-estimated p_up per (timeframe, sk); ask = open_px + 0.005 (assumed half-spread)
est = X[~X.oos].groupby(["timeframe", "sk"]).up_gamma.mean().rename("p_hat")
Y = X.join(est, on=["timeframe", "sk"])
au = Y.up_price + 0.005; ad = 1 - Y.up_price + 0.005
eu = Y.p_hat - au - fee_ps(au); ed = (1 - Y.p_hat) - ad - fee_ps(ad)
Y["side"] = np.where(eu > 0.0, "up", np.where(ed > 0.0, "dn", ""))
T = Y[Y.side != ""].copy()
T["price"] = np.where(T.side == "up", au[T.index] if False else T.up_price + 0.005, 1 - T.up_price + 0.005)
T["win"] = np.where(T.side == "up", T.up_gamma, 1 - T.up_gamma)
T["shares"] = 100.0; T["fee"] = T.shares * fee_ps(T.price); T["cost"] = T.shares * T.price + T.fee; T["pnl"] = T.shares * T.win - T.cost
T["cluster"] = T.wstart; T["t_entry"] = T.wstart; T["t_exit"] = T.end_ts
out = {"table": {f"{k[0]}|{'oos' if k[1] else 'is'}|{k[2]}": v for k, v in tab.to_dict("index").items()}}
for (tf, o), gg in T.groupby(["timeframe", "oos"]):
    s = summ(gg); out[f"trade_{tf}_{'oos' if o else 'is'}"] = s
    print(tf, "OOS" if o else "IS", s["n_trades"], round(s["roi"], 4), np.round(s["roi_ci95"], 4), s["p_roi_le_0"])
json.dump(out, open(f"{OUT}/idea19b.json", "w"), indent=1, default=float)
# targeted rule chosen from the IS table: fade |streak|>=k (buy Down after k Ups, Up after k Downs) at open price + 0.5c (+1.5c stress)
res2 = {}
for tf in ["15-minute", "1-hour", "4-hour"]:
    for k in (3, 4):
        for slip in (0.005, 0.015):
            Z = X[(X.timeframe == tf) & (X.streak.abs() >= k)].copy()
            Z["side"] = np.where(Z.streak > 0, "dn", "up")
            Z["price"] = np.where(Z.side == "up", Z.up_price, 1 - Z.up_price) + slip
            Z["win"] = np.where(Z.side == "up", Z.up_gamma, 1 - Z.up_gamma)
            Z["shares"] = 100.0; Z["fee"] = Z.shares * fee_ps(Z.price); Z["cost"] = Z.shares * Z.price + Z.fee; Z["pnl"] = Z.shares * Z.win - Z.cost
            Z["cluster"] = Z.wstart; Z["t_entry"] = Z.wstart; Z["t_exit"] = Z.end_ts
            for o in (False, True):
                s = summ(Z[Z.oos == o]); res2[f"fade_{tf}_k{k}_slip{slip}_{'oos' if o else 'is'}"] = s
                print("fade", tf, k, slip, "OOS" if o else "IS", s["n_trades"], s.get("n_clusters"), round(s["roi"], 4), np.round(s["roi_ci95"], 4), s["p_roi_le_0"])
out.update(res2)
json.dump(out, open(f"{OUT}/idea19b.json", "w"), indent=1, default=float)

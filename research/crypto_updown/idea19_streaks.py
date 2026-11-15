"""#19 Gambler's fallacy / streak bias in 5-minute up/down windows.
For each window: previous k official outcomes of the same coin (contiguous windows only), opening book at t=start (first tick within 3 s).
Tests: (a) realized P(Up) vs streak, (b) opening mid vs streak, (c) trade: buy Up or Down at the opening ask on tick start+1 (decision at start)."""
import numpy as np, pandas as pd, json
from common import *
W = load_windows().sort_values(["coin", "start"]).reset_index(drop=True)
W["mid0"] = (W.o_bu + W.o_au) / 2
res = {}
# streak: signed run length of previous outcomes (+n = n Ups in a row before this window, -n = n Downs)
def runs(g):
    up = g.up.to_numpy(); st = g.start.to_numpy()
    r = np.zeros(len(g), dtype=int)
    for i in range(1, len(g)):
        if st[i] - st[i - 1] != 300:
            r[i] = 0; continue
        prev = 1 if up[i - 1] == 1 else -1
        r[i] = (r[i - 1] + prev) if np.sign(r[i - 1]) == prev else prev
    return pd.Series(r, index=g.index)
W["streak"] = W.groupby("coin", group_keys=False).apply(runs)
W["sk"] = W.streak.clip(-5, 5)
tab = W.groupby(["oos", "sk"]).agg(n=("up", "size"), p_up=("up", "mean"), mid0=("mid0", "mean")).round(4)
print(tab.to_string())
res["table_by_streak"] = {f"{'oos' if k[0] else 'is'}_{k[1]}": v for k, v in tab.to_dict("index").items()}
# regression of up on streak sign and mid0 on streak
import statsmodels.api as sm
for o in (False, True):
    d = W[(W.oos == o) & (W.streak != 0)].dropna(subset=["mid0"])
    X = sm.add_constant(np.sign(d.streak) * np.minimum(d.streak.abs(), 5))
    f1 = sm.OLS(d.up - 0.5, X).fit(cov_type="cluster", cov_kwds={"groups": d.start})
    f2 = sm.OLS(d.mid0 - 0.5, X).fit(cov_type="cluster", cov_kwds={"groups": d.start})
    print("oos" if o else "is", "up~streak b=%.4f t=%.2f | mid0~streak b=%.4f t=%.2f" % (f1.params.iloc[1], f1.tvalues.iloc[1], f2.params.iloc[1], f2.tvalues.iloc[1]))
    res[f"reg_{'oos' if o else 'is'}"] = {"up_on_streak_b": f1.params.iloc[1], "t": f1.tvalues.iloc[1], "mid0_on_streak_b": f2.params.iloc[1], "t_mid": f2.tvalues.iloc[1]}
# trade rule: after |streak|>=k, bet continuation (follow) or reversal (fade) at opening ask (tick at start+1 via panel)
trades = []
for coin in COINS:
    P = pd.read_parquet(f"{OUT}/panel_{coin}.parquet", columns=["w", "t", "start", "tau", "au", "ad", "sau", "su"])
    P = P[P.tau >= 295]
    w = W[W.coin == coin].reset_index(drop=True)
    P["up"] = w.up.to_numpy()[P.w]; P["streak"] = w.streak.to_numpy()[P.w]; P["oos"] = w.oos.to_numpy()[P.w]
    P = P.reset_index(drop=True)
    first = P.groupby("w").cumcount() == 0
    for k in (1, 2, 3, 4, 5):
        for mode in ("fade", "follow"):
            s = P.streak.to_numpy()
            want_up = (s <= -k) if mode == "fade" else (s >= k)
            want_dn = (s >= k) if mode == "fade" else (s <= -k)
            T = taker_sim(P, first.to_numpy() & want_up, first.to_numpy() & want_dn, lat=1, tol=0.01)
            T["coin"] = coin; T["k"] = k; T["mode"] = mode; T["oos"] = P.oos.to_numpy()[0] if False else w.oos.to_numpy()[T.w]
            trades.append(T)
T = pd.concat(trades, ignore_index=True)
rows = []
for (k, mode, o), g in T.groupby(["k", "mode", "oos"]):
    s = summ(g)
    rows.append({"k": k, "mode": mode, "oos": o, "n": s["n_trades"], "roi": s["roi"], "ci": s["roi_ci95"], "p": s["p_roi_le_0"], "win": g.win.mean(), "avg_px": s["avg_price"]})
R = pd.DataFrame(rows)
print(R.to_string())
res["trade_rules"] = R.to_dict("records")
# baseline: buy the cheaper/expensive side unconditionally at open
W.to_parquet(f"{OUT}/windows_streak.parquet", index=False)
json.dump(res, open(f"{OUT}/idea19.json", "w"), indent=1, default=float)

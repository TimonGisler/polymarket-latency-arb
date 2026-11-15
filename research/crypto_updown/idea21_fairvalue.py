"""#21 Fair value from Binance spot vs strike.  p = Phi( (ln(S/K) + c*r30) / sqrt(k^2 sig^2 tau + b^2) ), fit (k, b, c) per coin by MLE on in-sample (first 60%)
against OFFICIAL outcomes (so Binance-vs-Chainlink basis noise is absorbed into b).  Then (1) compare log-loss of model vs market mid by tau bucket,
(2) does model add info beyond the mid (logit regression), (3) taker replay: buy side if model - ask - fee > margin."""
import numpy as np, pandas as pd, json, sys
from scipy.optimize import minimize
from scipy.stats import norm
from common import *

W = load_windows()
coins = sys.argv[1:] or [c for c in COINS if c in BINANCE]
res = {}; allT = []
def model_p(x, sig, tau, r30, th):
    k, b, c = th
    return norm.cdf((x + c * r30) / np.sqrt((k * sig) ** 2 * tau + (b * 1e-4) ** 2))
for coin in coins:
    P = load_panel(coin, W)
    P = P[P.S.notna() & P.K.notna() & P.sig300.notna() & P.sig3600.notna()].reset_index(drop=True)
    P["x"] = np.log(P.S / P.K)
    P["sig"] = np.sqrt(0.5 * P.sig300.astype(float) ** 2 + 0.5 * P.sig3600.astype(float) ** 2)
    P["mid"] = (P.bu + P.au) / 2
    ins = P[~P.oos & (P.t % 3 == 0)]
    def nll(th):
        p = np.clip(model_p(ins.x, ins.sig, ins.tau, ins.r30, th), 1e-6, 1 - 1e-6)
        return -np.mean(ins.up * np.log(p) + (1 - ins.up) * np.log(1 - p))
    fit = minimize(nll, [1.0, 1.0, 0.0], method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-6, "maxiter": 400})
    th = fit.x
    P["p"] = model_p(P.x, P.sig, P.tau, P.r30, th)
    # log loss comparison by tau bucket
    P["tb"] = pd.cut(P.tau, [0, 5, 10, 30, 60, 120, 200, 301], right=False)
    def ll(p, y):
        p = np.clip(p, 1e-4, 1 - 1e-4); return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    cmp = P.groupby(["oos", "tb"], observed=True).apply(lambda d: pd.Series({"n": len(d), "ll_model": ll(d.p, d.up), "ll_mid": ll(d.mid, d.up),
                                                                            "mean_abs_p_minus_mid": (d.p - d.mid).abs().mean()}))
    print(coin, "theta(k,b_bp,c)=", np.round(th, 3)); print(cmp.round(4).to_string())
    # information beyond mid: logit(up) ~ logit(mid) + logit(p), OOS
    import statsmodels.api as sm
    o = P[P.oos & (P.t % 5 == 0) & P.mid.between(0.03, 0.97)]
    lg = lambda v: np.log(np.clip(v, 1e-3, 1 - 1e-3) / (1 - np.clip(v, 1e-3, 1 - 1e-3)))
    X = sm.add_constant(np.column_stack([lg(o.mid), lg(o.p)]))
    f = sm.Logit(o.up.to_numpy(), X).fit(disp=0, cov_type="cluster", cov_kwds={"groups": o.w.to_numpy()})
    print("OOS logit(up)~logit(mid)+logit(model):", np.round(f.params, 3), "t=", np.round(f.tvalues, 1))
    res[coin] = {"theta": th.tolist(), "ll_table": {f"{'oos' if k[0] else 'is'}_{k[1]}": v for k, v in cmp.round(5).to_dict("index").items()},
                 "oos_logit_mid_model": {"params": f.params.tolist(), "t": f.tvalues.tolist()}}
    # taker replay
    fee_u = FEE_RATE * P.au * (1 - P.au); fee_d = FEE_RATE * P.ad * (1 - P.ad)
    eu = P.p - P.au - fee_u; ed = (1 - P.p) - P.ad - fee_d
    for margin in (0.0, 0.02, 0.05):
        for (lo, hi) in ((5, 30), (30, 60), (60, 120), (120, 295), (5, 295)):
            inb = P.tau.between(lo, hi - 1).to_numpy()
            for lat in (1, 2):
                T = taker_sim(P, (eu > margin).to_numpy() & inb, (ed > margin).to_numpy() & inb, lat=lat, tol=0.0, one_shot=True)
                T["coin"] = coin; T["margin"] = margin; T["bucket"] = f"{lo}-{hi}"; T["lat"] = lat
                T["oos"] = P.oos.to_numpy()[0] if len(T) == 0 else W[W.coin == coin].oos.to_numpy()[T.w]
                allT.append(T)
T = pd.concat(allT, ignore_index=True)
T.to_parquet(f"{OUT}/idea21_trades.parquet", index=False)
rows = []
for key, g in T.groupby(["margin", "bucket", "lat", "oos"]):
    s = summ(g)
    days = (g.t_entry.max() - g.t_entry.min()) / 86400
    rows.append(dict(zip(["margin", "bucket", "lat", "oos"], key), n=s["n_trades"], roi=round(s["roi"], 4), ci=np.round(s["roi_ci95"], 4).tolist(), p=s["p_roi_le_0"],
                     pnl_sh=round(s["pnl_per_share"], 4), win=round(g.win.mean(), 3), px=round(s["avg_price"], 3), pnl_day=round(g.pnl.sum() / max(days, 1), 1)))
R = pd.DataFrame(rows)
print(R.to_string())
res["replay"] = R.to_dict("records")
json.dump(res, open(f"{OUT}/idea21.json", "w"), indent=1, default=float)

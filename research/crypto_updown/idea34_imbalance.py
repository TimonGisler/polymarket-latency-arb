"""#34 order-book imbalance alpha (+ #21b spot lead-lag) on 1 Hz kacho books.
Target: Up mid change from t to t+k (k=1,2,5,10,30 s).  Features known at t: top-of-book imbalance imb=(bid_sz-ask_sz)/(bid_sz+ask_sz) of the Up book,
depth imbalance dimb=(du-dd)/(du+dd) (bid depth Up vs Down within 5c), spot delta-moves dsp1/dsp5 (Binance move in last 1/5 s converted to probability units).
Fit OLS in-sample, report OOS R^2 / coefficients, then taker replay: buy Up if mid+pred-ask_up-fee>margin (hold to resolution), symmetric Down."""
import numpy as np, pandas as pd, json, sys
from scipy.stats import norm
from common import *
W = load_windows()
coins = sys.argv[1:] or COINS
res = {}; allT = []
for coin in coins:
    P = load_panel(coin, W)
    P["mid"] = (P.bu + P.au) / 2
    P["spr"] = P.au - P.bu
    bs = P.su.fillna(0).astype(float); as_ = P.sau.fillna(0).astype(float)
    P["imb"] = np.where(bs + as_ > 0, (bs - as_) / (bs + as_), 0)
    P["dimb"] = np.where(P.du + P.dd > 0, (P.du - P.dd) / (P.du + P.dd), 0)
    has_spot = coin in BINANCE
    feats = ["imb", "dimb"]
    if has_spot:
        sig = np.sqrt(0.5 * P.sig300.astype(float) ** 2 + 0.5 * P.sig3600.astype(float) ** 2)
        mid_c = P.mid.clip(0.02, 0.98)
        dens = norm.pdf(norm.ppf(mid_c))
        for k in (1, 5):
            P[f"dsp{k}"] = (dens * P[f"r{k}"].astype(float) / (sig * np.sqrt(P.tau.clip(lower=1)))).clip(-0.3, 0.3).fillna(0)
        feats += ["dsp1", "dsp5"]
    w = P.w.to_numpy(); n = len(P)
    out = {}
    for k in (1, 2, 5, 10, 30):
        j = np.minimum(np.arange(n) + k, n - 1)
        okk = (w[j] == w) & (P.t.to_numpy()[j] == P.t.to_numpy() + k)
        P[f"dm{k}"] = np.where(okk, P.mid.to_numpy()[j] - P.mid.to_numpy(), np.nan)
    base = P.mid.between(0.1, 0.9) & (P.tau > 35) & (P.spr <= 0.05)
    for k in (1, 2, 5, 10, 30):
        d = P[base & P[f"dm{k}"].notna()]
        ins, oos = d[~d.oos], d[d.oos]
        X = np.column_stack([np.ones(len(ins))] + [ins[f] for f in feats]); y = ins[f"dm{k}"].to_numpy()
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        Xo = np.column_stack([np.ones(len(oos))] + [oos[f] for f in feats]); yo = oos[f"dm{k}"].to_numpy()
        pred = Xo @ beta
        r2 = 1 - np.sum((yo - pred) ** 2) / np.sum((yo - yo.mean()) ** 2)
        hi = np.abs(pred) > np.quantile(np.abs(pred), 0.99)
        out[k] = {"beta": dict(zip(["c"] + feats, np.round(beta, 5).tolist())), "oos_r2": round(float(r2), 4),
                  "oos_top1pct_mean_move_signed": round(float(np.mean(np.sign(pred[hi]) * yo[hi])), 4),
                  "oos_top1pct_mean_halfspread": round(float(oos.spr.to_numpy()[hi].mean() / 2), 4)}
        if k in (5, 30):
            P[f"pred{k}"] = np.column_stack([np.ones(n)] + [P[f] for f in feats]) @ beta
    print(coin, json.dumps(out)); res[coin] = out
    feeu = FEE_RATE * P.au * (1 - P.au); feed = FEE_RATE * P.ad * (1 - P.ad)
    elig = (P.tau.between(36, 290) & P.mid.between(0.1, 0.9)).to_numpy()
    for k in (5, 30):
        for margin in (0.0, 0.01, 0.02):
            su_ = ((P.mid + P[f"pred{k}"] - P.au - feeu) > margin).to_numpy() & elig
            sd_ = ((1 - P.mid - P[f"pred{k}"] - P.ad - feed) > margin).to_numpy() & elig
            for lat in (1, 2):
                T = taker_sim(P, su_, sd_, lat=lat, one_shot=False, cooldown=10)
                T["coin"] = coin; T["k"] = k; T["margin"] = margin; T["lat"] = lat
                T["oos"] = W[W.coin == coin].oos.to_numpy()[T.w.astype(int)] if len(T) else []
                allT.append(T)
T = pd.concat(allT, ignore_index=True)
T.to_parquet(f"{OUT}/idea34_trades.parquet", index=False)
rows = []
for key, g in T.groupby(["k", "margin", "lat", "oos"]):
    s = summ(g); days = max((g.t_entry.max() - g.t_entry.min()) / 86400, 1)
    rows.append(dict(zip(["k", "margin", "lat", "oos"], key), n=s["n_trades"], roi=round(s["roi"], 4), ci=np.round(s["roi_ci95"], 4).tolist(), p=s["p_roi_le_0"],
                     pnl_sh=round(s["pnl_per_share"], 4), px=round(s["avg_price"], 3), pnl_day=round(g.pnl.sum() / days, 1)))
R = pd.DataFrame(rows); print(R.to_string())
res["replay"] = R.to_dict("records")
json.dump(res, open(f"{OUT}/idea34{'_' + '_'.join(coins) if sys.argv[1:] else ''}.json", "w"), indent=1, default=float)

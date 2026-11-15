"""#33 end-of-window behaviour (final 2-60 s) in 5-minute windows.
A) Taker: at decision tick with tau seconds left, buy the favourite (side with mid>=0.5) or the underdog at its ask on the NEXT tick (lat 1; stress lat 2),
   bucketed by ask price.  Cells (tau, side, bucket) selected in-sample (ROI>0, p<0.05), evaluated OOS.
B) Maker: rest a bid on the favourite (join best bid, optionally +1c) for tau in [2,60] when favourite mid>=0.6; fills only on trade-through prints
   (aliplayer1 websocket trades; BTC/ETH/SOL/XRP where downloaded), hold to resolution; rebate 0.2*fee-equivalent."""
import numpy as np, pandas as pd, json, sys, os, duckdb
from common import *
from maker_sim import sim, load_trades
W = load_windows()
taus = [60, 45, 30, 20, 15, 10, 5, 3, 2]
bins = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 1.0]
allT = []
for coin in COINS:
    P = load_panel(coin, W)
    P["mid"] = (P.bu + P.au) / 2
    tau = P.tau.to_numpy(); mid = P.mid.to_numpy()
    for td in taus:
        at = tau == td
        for who in ("fav", "dog"):
            su = at & ((mid >= 0.5) if who == "fav" else (mid < 0.5))
            sd = at & ((mid < 0.5) if who == "fav" else (mid >= 0.5))
            for lat in (1, 2):
                T = taker_sim(P, su, sd, lat=lat, tol=0.01, cap_usd=500, one_shot=True)
                T["coin"] = coin; T["tau_dec"] = td; T["who"] = who; T["lat"] = lat
                T["oos"] = W[W.coin == coin].oos.to_numpy()[T.w.astype(int)] if len(T) else []
                allT.append(T)
T = pd.concat(allT, ignore_index=True)
T["bucket"] = pd.cut(T.price, bins, right=False).astype(str)
T.to_parquet(f"{OUT}/idea33_taker_trades.parquet", index=False)
rows = []
for key, g in T.groupby(["tau_dec", "who", "bucket", "lat", "oos"]):
    if len(g) < 30:
        continue
    s = summ(g)
    rows.append(dict(zip(["tau_dec", "who", "bucket", "lat", "oos"], key), n=len(g), roi=s["roi"], p=s["p_roi_le_0"], win=g.win.mean(), px=s["avg_price"],
                     edge_pre_fee=g.win.mean() - s["avg_price"], pnl_sh=s["pnl_per_share"]))
R = pd.DataFrame(rows)
R.to_csv(f"{OUT}/idea33_taker_cells.csv", index=False)
ins = R[(~R.oos) & (R.lat == 1)]
sel = ins[(ins.roi > 0) & (ins.p < 0.05)][["tau_dec", "who", "bucket"]]
print("in-sample selected cells:", len(sel)); print(sel.to_string())
res = {"selected_cells": sel.to_dict("records")}
for lat in (1, 2):
    for o in (False, True):
        g = T[(T.lat == lat) & (T.oos == o)].merge(sel, on=["tau_dec", "who", "bucket"])
        s = summ(g, f"selected lat{lat} {'oos' if o else 'is'}")
        print(lat, o, {k: s.get(k) for k in ["n_trades", "n_clusters", "roi", "roi_ci95", "p_roi_le_0", "pnl_per_day", "avg_price", "pnl_per_share"]})
        res[f"selected_lat{lat}_{'oos' if o else 'is'}"] = s
# pooled calibration table (lat1, all coins) for the README
cal = T[T.lat == 1].groupby(["tau_dec", "who", "oos"]).apply(lambda g: pd.Series({"n": len(g), "win": g.win.mean(), "px": g.price.mean(),
                                                                                   "roi": g.pnl.sum() / g.cost.sum()})).round(4)
print(cal.to_string()); res["calibration"] = {str(k): v for k, v in cal.to_dict("index").items()}
# ---- B) maker on favourite
con = duckdb.connect(); con.execute("set threads=2; set memory_limit='3GB'; set enable_progress_bar=false")
ali_m = market_map()
mk = []
for coin in ["btc", "eth", "sol", "xrp"]:
    if not os.path.exists(f"{EXT}/ali/ticks/{coin.upper()}_5-minute.parquet"):
        continue
    w = W[W.coin == coin].reset_index(drop=True); w["w"] = np.arange(len(w))
    P = load_panel(coin, W); P["mid"] = (P.bu + P.au) / 2
    tr = load_trades(con, coin, w, ali_m, EXT)
    covered = np.zeros(len(w), bool); covered[tr.w.unique()] = True
    cut = w.start[covered].quantile(0.6)
    isf = P.groupby("w").cumcount().to_numpy() == 0
    first_idx = np.full(len(w), -1, np.int64); first_idx[P.w[isf].to_numpy()] = np.nonzero(isf)[0]
    wn = np.bincount(P.w, minlength=len(w)).astype(np.int64)
    first_t = np.zeros(len(w), np.int64); first_t[P.w[isf].to_numpy()] = P.t[isf].to_numpy()
    for (lo_tau, hi_tau, fav_min, improve) in [(2, 60, 0.6, 0), (2, 60, 0.6, 1), (2, 30, 0.8, 0), (10, 60, 0.7, 0), (2, 15, 0.9, 0)]:
        tau = P.tau.to_numpy(); mid = P.mid.to_numpy(); spr = (P.au - P.bu).to_numpy()
        win_t = (tau >= lo_tau) & (tau <= hi_tau)
        act_b = win_t & (mid >= fav_min) & (mid < 0.995)       # bid Up (Up favourite)
        act_a = win_t & (mid <= 1 - fav_min) & (mid > 0.005)   # Up-ask == bid on Down (Down favourite)
        bidq = P.bu.to_numpy().copy(); askq = P.au.to_numpy().copy()
        if improve:
            wide = spr >= 0.025; bidq[wide] += 0.01; askq[wide] -= 0.01
        n = len(tr)
        ow = np.zeros(n, np.int64); ot = np.zeros(n, np.int64); os_ = np.zeros(n, np.int64); op = np.zeros(n); osh = np.zeros(n)
        nf = sim(tr.w.to_numpy().astype(np.int64), tr.tsec.to_numpy().astype(np.int64), tr.upx.to_numpy(), tr.dirn.to_numpy().astype(np.int64),
                 tr.sh.to_numpy(), first_idx, wn, first_t, bidq, askq, act_b, act_a, 100.0, 1000.0, 0.5, 1e-9, ow, ot, os_, op, osh)
        F = pd.DataFrame({"w": ow[:nf], "t": ot[:nf], "side": os_[:nf], "px": op[:nf], "sh": osh[:nf]})
        F["up"] = w.up.to_numpy()[F.w]; F["start"] = w.start.to_numpy()[F.w]; F["oos"] = F.start >= cut
        pe = np.where(F.side > 0, F.px, 1 - F.px)
        F["price"] = pe; F["shares"] = F.sh; F["cost"] = F.sh * pe
        F["rebate"] = REBATE_SHARE * FEE_RATE * pe * (1 - pe) * F.sh
        F["pnl"] = F.sh * F.side * (F.up - F.px) + 0.5 * F.rebate   # 50% haircut on rebate
        F["cluster"] = F.start; F["t_entry"] = F.t; F["t_exit"] = F.start + 300; F["fee"] = 0.0
        F["coin"] = coin; F["variant"] = f"tau{lo_tau}-{hi_tau}_fav{fav_min}_imp{improve}"
        mk.append(F)
M = pd.concat(mk, ignore_index=True)
M.to_parquet(f"{OUT}/idea33_maker_fills.parquet", index=False)
for (v, o), g in M.groupby(["variant", "oos"]):
    s = summ(g)
    print("maker", v, "OOS" if o else "IS", {k: s.get(k) for k in ["n_trades", "n_clusters", "roi", "roi_ci95", "p_roi_le_0", "pnl_per_day", "avg_price", "pnl_per_share"]})
    res[f"maker_{v}_{'oos' if o else 'is'}"] = s
json.dump(res, open(f"{OUT}/idea33.json", "w"), indent=1, default=float)

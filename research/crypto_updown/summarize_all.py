"""Collect per-idea results into result.json (framework schema) + printed tables for README. Excludes the 2026-04-29..05-04 incident dates."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import sys, json, numpy as np, pandas as pd
sys.path.insert(0, ROOT)
from pmbt.metrics import summarize, verdict
from common import *
W = load_windows()
bad = {c: W[W.coin == c].bad_date.to_numpy() for c in COINS}
oosm = {c: W[W.coin == c].oos.to_numpy() for c in COINS}

def split_summary(T, name, params):
    T = T.copy()
    s = summarize(T, name=name, split=False, n_boot=1000)
    s["in_sample"] = summarize(T[~T.oos], split=False, n_boot=1000) if (~T.oos).any() else None
    s["out_of_sample"] = summarize(T[T.oos], split=False, n_boot=1000) if T.oos.any() else None
    s["params"] = params
    s["verdict"] = verdict(s)
    return s

def tag(T):
    T = T.copy()
    T["bad"] = [bad[c][int(w)] for c, w in zip(T.coin, T.w)]
    return T[~T.bad]

def brief(s):
    o = s.get("out_of_sample") or {}; i = s.get("in_sample") or {}
    return (f"IS n={i.get('n_trades')} ROI={i.get('roi', float('nan')):+.4f} | OOS n={o.get('n_trades')} clusters={o.get('n_clusters')} ROI={o.get('roi', float('nan')):+.4f} "
            f"CI=[{o.get('roi_ci95', [np.nan, np.nan])[0]:+.4f},{o.get('roi_ci95', [np.nan, np.nan])[1]:+.4f}] p={o.get('p_roi_le_0')} $/day={o.get('pnl_per_day', float('nan')):.0f} -> {s['verdict']}")

results = {}
# ---- #21 fair value (Phi model) taker
T = tag(pd.read_parquet(f"{OUT}/idea21_trades.parquet"))
v21 = []
for (m, b, lat), g in T.groupby(["margin", "bucket", "lat"]):
    s = split_summary(g, f"fv_margin{m}_tau{b}_lat{lat}", {"margin": m, "tau_bucket": b, "latency_ticks": lat, "one_shot_per_window": True, "cap_usd": 500})
    v21.append(s)
best = max([s for s in v21 if s["params"]["latency_ticks"] == 1], key=lambda s: (s["in_sample"] or {}).get("roi", -9))
print("#21 best-IS variant:", best["name"], brief(best))
for s in v21:
    if s["params"]["latency_ticks"] == 1 or s["name"] == best["name"].replace("lat1", "lat2"):
        print("   ", s["name"], brief(s))
lat2 = [s for s in v21 if s["name"] == best["name"].replace("lat1", "lat2")][0]
results[21] = {"idea": 21, "name": "crypto up/down fair value from Binance spot (taker)", "variants": v21, "best_variant_chosen_in_sample": best["name"],
               "best_variant_lat2": brief(lat2)}
# per-coin OOS for the best variant
g = T[(T.margin == best["params"]["margin"]) & (T.bucket == best["params"]["tau_bucket"]) & (T.lat == 1) & T.oos]
print("   per-coin OOS ROI:", g.groupby("coin").apply(lambda d: round(d.pnl.sum() / d.cost.sum(), 4)).to_dict())
# ---- #34 imbalance + lead-lag taker
T = tag(pd.read_parquet(f"{OUT}/idea34_trades.parquet"))
v34 = []
for (k, m, lat), g in T.groupby(["k", "margin", "lat"]):
    v34.append(split_summary(g, f"imb_leadlag_k{k}_margin{m}_lat{lat}", {"horizon_s": k, "margin": m, "latency_ticks": lat, "cooldown_s": 10}))
best34 = max([s for s in v34 if s["params"]["latency_ticks"] == 1], key=lambda s: (s["in_sample"] or {}).get("roi", -9))
print("#34 best-IS:", best34["name"], brief(best34))
for s in v34:
    print("   ", s["name"], brief(s))
results[34] = {"idea": 34, "name": "order-book imbalance (+ Binance lead-lag) taker", "variants": v34, "best_variant_chosen_in_sample": best34["name"]}
# ---- #33 end-of-window taker: re-select cells in-sample excluding incident dates
T = tag(pd.read_parquet(f"{OUT}/idea33_taker_trades.parquet"))
T["bucket"] = T.bucket.astype(str)
cells = []
for key, g in T[(T.lat == 1) & (~T.oos)].groupby(["tau_dec", "who", "bucket"]):
    if len(g) < 100:
        continue
    s = summarize(g, split=False, n_boot=500)
    cells.append(dict(zip(["tau_dec", "who", "bucket"], key), n=len(g), roi=s["roi"], p=s["p_roi_le_0"]))
C = pd.DataFrame(cells)
sel = C[(C.roi > 0) & (C.p < 0.05)][["tau_dec", "who", "bucket"]]
print("#33 IS-selected cells (excl. incident):", sel.to_dict("records"))
v33 = []
for lat in (1, 2):
    g = T[T.lat == lat].merge(sel, on=["tau_dec", "who", "bucket"])
    if len(g):
        v33.append(split_summary(g, f"endwindow_taker_selected_cells_lat{lat}", {"cells": sel.to_dict("records"), "latency_ticks": lat}))
        print("   ", v33[-1]["name"], brief(v33[-1]))
for who in ("fav", "dog"):
    for td in (60, 30, 10, 5, 2):
        g = T[(T.lat == 1) & (T.who == who) & (T.tau_dec == td)]
        s = split_summary(g, f"endwindow_taker_{who}_tau{td}_lat1", {"who": who, "tau": td})
        v33.append(s); print("   ", s["name"], brief(s))
# maker on favourite
M = pd.read_parquet(f"{OUT}/idea33_maker_fills.parquet")
for v, g in M.groupby("variant"):
    s = split_summary(g, f"endwindow_maker_{v}", {"variant": v, "fill": "trade-through, back of queue, qshare 0.5, quote from 1-s-old book", "rebate": "50% of pro-rata 20% pool"})
    v33.append(s); print("   ", s["name"], brief(s))
results[33] = {"idea": 33, "name": "end-of-window (final 2-60 s) taker/maker on near-determined outcome", "variants": v33}

# ---- #21c sub-second latency arb (BTC; ETH as robustness)
def events_trades(coin, mode, slip):
    E = pd.read_parquet(f"{OUT}/idea21c_events{'' if coin == 'btc' else '_' + coin}.parquet").drop_duplicates(["thr", "L", "T"])
    w = W[W.coin == coin].reset_index(drop=True)
    E = E[~w.bad_date.to_numpy()[E.w]]
    if mode == "book":
        P = pd.read_parquet(f"{OUT}/panel_{coin}.parquet", columns=["w", "t", "au", "ad", "sau", "su"])
        isf = P.groupby("w").cumcount().to_numpy() == 0
        fi = np.full(len(w), -1, np.int64); fi[P.w[isf].to_numpy()] = np.nonzero(isf)[0]
        ft = np.zeros(len(w), np.int64); ft[P.w[isf].to_numpy()] = P.t[isf].to_numpy(); wn = np.bincount(P.w, minlength=len(w))
        sec = -(-(E["T"].to_numpy() + E.L.to_numpy()) // 1000); wi = E.w.to_numpy(); off = sec - ft[wi]; ok = (off >= 0) & (off < wn[wi])
        r = np.where(ok, fi[wi] + np.clip(off, 0, None), 0); up = E.side.to_numpy() > 0
        E["px"] = np.where(ok, np.where(up, P.au.to_numpy()[r], P.ad.to_numpy()[r]), np.nan)
        E["sh"] = np.minimum(np.where(ok, np.where(up, P.sau.to_numpy()[r], P.su.to_numpy()[r]), np.nan), 100.0)
    elif mode == "worst":
        E["px"] = E.px_worst
    E = E[E.px.between(0.01, 0.99) & (E.sh > 0)].copy()
    E["px"] = E.px + slip; E["price"] = E.px; E["shares"] = E.sh
    E["fee"] = E.sh * fee_ps(E.px); E["cost"] = E.sh * E.px + E.fee; E["pnl"] = E.sh * (E.win - E.px) - E.fee
    E["cluster"] = E.start; E["t_entry"] = E["T"] // 1000; E["t_exit"] = E.start + 300
    return E
v21c = []
for coin in ("btc", "eth"):
    for mode in ("book", "first", "worst"):
        for slip in (0.0, 0.01):
            E = events_trades(coin, mode, slip)
            for (thr, L), g in E.groupby(["thr", "L"]):
                if thr not in (3, 5, 8) or L == 2000 and slip > 0:
                    continue
                s_ = split_summary(g, f"latarb_{coin}_{mode}_thr{thr}bp_L{L}ms_slip{slip}", {"coin": coin, "fill": mode, "jump_threshold_bp_1s": thr, "latency_ms": L, "slippage": slip, "cap_shares": 100})
                o2 = g[pd.to_datetime(g["T"], unit="ms") >= "2026-04-27"]
                if len(o2):
                    s_["heldout_after_2026_04_27"] = summarize(o2, split=False, n_boot=500)
                v21c.append(s_)
                if thr == 5 and L in (250, 500, 1000):
                    print("#21c", s_["name"], brief(s_))
results["21c"] = {"idea": 21, "name": "crypto up/down latency arb: Binance 1-s jump -> take the stale Polymarket side (BTC 5m)", "variants": v21c,
                  "best_variant_chosen_in_sample": "latarb_btc_book_thr5bp_L500ms_slip0.0 (IS ROI +6.8%; threshold 5 bp and 500 ms picked as realistic, not max-IS)"}

# ---- #31 maker (one fills file per coin x variant, read one at a time)
import glob, os
v31 = []
for fpath in sorted(glob.glob(f"{OUT}/idea31/fills_*.parquet")):
    g = pd.read_parquet(fpath)
    coin = g.coin.iloc[0]; v = g.variant.iloc[0]
    g["shares"] = g.sh; g["price"] = np.where(g.side > 0, g.px, 1 - g.px); g["fee"] = 0.0
    g["cluster"] = g.start; g["t_entry"] = g.t; g["t_exit"] = g.start + 300
    for reb, lab in ((1.0, "reb100"), (0.5, "reb50")):
        g["pnl"] = g.pnl_res + reb * g.rebate
        s_ = split_summary(g, f"mm_{coin}_{v}_{lab}", {"coin": coin, "variant": v, "rebate_share_of_prorata": reb, "quote_size": 50})
        o = g[g.oos]
        s_["per_share_oos"] = {k: float(o[c].sum() / o.sh.sum()) for k, c in
                          (("spread_captured", "spread_cap"), ("markout_5s", "mk5"), ("markout_30s", "mk30"), ("pnl_at_resolution", "pnl_res"), ("rebate_100pct", "rebate"))}
        v31.append(s_)
        if lab == "reb100":
            print("#31", s_["name"], brief(s_), {k: round(x, 4) for k, x in s_["per_share_oos"].items()}, flush=True)
    del g
results[31] = {"idea": 31, "name": "maker-rebate harvesting near 50c (two-sided quoting)", "variants": v31}
json.dump(results, open(f"{OUT}/summaries.json", "w"), indent=1, default=float)

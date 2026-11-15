"""#1 complement arb inside crypto up/down windows: count ticks with bid_up+bid_down>1 (split & sell both) or ask_up+ask_down+fees<1 (buy both & merge),
their size (min displayed size of the two legs), duration (consecutive 1 Hz ticks), and net edge after taker fees on both legs."""
import numpy as np, pandas as pd, json
from common import *
res = {}
for coin in COINS:
    t = load_ticks(coin, ["condition_id", "t", "bu", "au", "bd", "ad", "su", "sd", "sau", "sad"])
    n = len(t)
    sell_edge = t.bu + t.bd - 1 - fee_ps(t.bu) - fee_ps(t.bd)
    buy_edge = 1 - t.au - t.ad - fee_ps(t.au) - fee_ps(t.ad)
    mir = ((t.bu + t.ad - 1).abs() < 1e-6) & ((t.au + t.bd - 1).abs() < 1e-6)
    out = {"ticks": n, "mirrored_share": float(mir.mean())}
    for name, e, s1, s2 in (("sell_both", sell_edge, t.su, t.sd), ("buy_both", buy_edge, t.sau, t.sad)):
        raw = (t.bu + t.bd > 1) if name == "sell_both" else (t.au + t.ad < 1)
        x = t[e > 0].copy(); x["edge"] = e[e > 0]; x["size"] = np.minimum(s1[e > 0].fillna(0), s2[e > 0].fillna(0))
        x = x.sort_values(["condition_id", "t"])
        run = ((x.t.diff() != 1) | (x.condition_id != x.condition_id.shift())).cumsum()
        dur = x.groupby(run).size()
        out[name] = {"raw_cross_ticks": int(raw.sum()), "net_positive_ticks": int(len(x)), "windows": int(x.condition_id.nunique()),
                     "episodes": int(run.nunique()) if len(x) else 0, "episodes_lasting_2s_plus": int((dur >= 2).sum()) if len(x) else 0,
                     "median_edge_per_share": float(x.edge.median()) if len(x) else None, "median_size_sh": float(x["size"].median()) if len(x) else None,
                     "sum_edge_x_size_usd_if_all_captured": float((x.edge * x["size"]).sum())}
    res[coin] = out
    print(coin, json.dumps(out))
json.dump(res, open(f"{OUT}/idea1.json", "w"), indent=1)

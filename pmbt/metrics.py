"""Standard evaluation for every strategy test.

A strategy test produces a *trades* DataFrame with at least:
  cluster   - id used for clustered bootstrap (event_id; correlated bets share a cluster)
  t_entry   - unix seconds
  t_exit    - unix seconds (resolution time or exit time)
  cost      - USDC paid incl. fees (capital at risk, > 0)
  pnl       - USDC profit net of all fees and rebates (payoff - cost)
Optional: fee, mkt, side, price, shares, category.

`summarize(trades)` returns a dict with ROI (pnl per $ of cost), event-clustered bootstrap CI,
one-sided p-value for ROI <= 0, capital-time annualized return, drawdown, splits.
"""
import json
import numpy as np
import pandas as pd

OOS_START = 1775001600  # 2026-04-01 00:00 UTC: everything after is out-of-sample by convention
DAY = 86400.0


def _cluster_bootstrap_roi(df, n_boot=2000, seed=0):
    g = df.groupby("cluster").agg(pnl=("pnl", "sum"), cost=("cost", "sum"))
    if len(g) < 2:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    pnl = g["pnl"].to_numpy()
    cost = g["cost"].to_numpy()
    n = len(g)
    idx = rng.integers(0, n, size=(n_boot, n))
    rois = pnl[idx].sum(1) / cost[idx].sum(1)
    lo, hi = np.percentile(rois, [2.5, 97.5])
    p = float((rois <= 0).mean())
    return float(lo), float(hi), p


def _max_drawdown(df):
    s = df.sort_values("t_exit")["pnl"].cumsum()
    peak = s.cummax()
    return float((s - peak).min()) if len(s) else 0.0


def summarize(trades: pd.DataFrame, name="", n_boot=2000, split=True):
    df = trades.copy()
    if "cluster" not in df:
        df["cluster"] = np.arange(len(df))
    out = {"name": name, "n_trades": int(len(df))}
    if len(df) == 0:
        return out
    cost = df["cost"].sum()
    pnl = df["pnl"].sum()
    days = ((df["t_exit"] - df["t_entry"]).clip(lower=60) / DAY)
    cap_days = float((df["cost"] * days).sum())
    lo, hi, p = _cluster_bootstrap_roi(df, n_boot=n_boot)
    span_days = max((df["t_exit"].max() - df["t_entry"].min()) / DAY, 1.0)
    out.update({
        "n_clusters": int(df["cluster"].nunique()),
        "total_cost": float(cost),
        "total_pnl": float(pnl),
        "roi": float(pnl / cost) if cost else np.nan,
        "roi_ci95": [lo, hi],
        "p_roi_le_0": p,
        "hit_rate": float((df["pnl"] > 0).mean()),
        "avg_hold_days": float(days.mean()),
        "ann_return_on_capital": float(pnl / cap_days * 365) if cap_days > 0 else np.nan,
        "pnl_per_day": float(pnl / span_days),
        "max_drawdown": _max_drawdown(df),
        "worst_cluster_pnl": float(df.groupby("cluster")["pnl"].sum().min()),
        "fees_paid": float(df["fee"].sum()) if "fee" in df else None,
        "first_entry": pd.to_datetime(df["t_entry"].min(), unit="s").strftime("%Y-%m-%d"),
        "last_exit": pd.to_datetime(df["t_exit"].max(), unit="s").strftime("%Y-%m-%d"),
    })
    if split:
        ins = df[df["t_entry"] < OOS_START]
        oos = df[df["t_entry"] >= OOS_START]
        out["in_sample"] = summarize(ins, split=False, n_boot=n_boot) if len(ins) else None
        out["out_of_sample"] = summarize(oos, split=False, n_boot=n_boot) if len(oos) else None
        q = pd.to_datetime(df["t_entry"], unit="s").dt.to_period("Q").astype(str)
        by_q = df.groupby(q).agg(n=("pnl", "size"), pnl=("pnl", "sum"), cost=("cost", "sum"))
        by_q["roi"] = by_q["pnl"] / by_q["cost"]
        out["by_quarter"] = {k: {"n": int(r.n), "pnl": round(float(r.pnl), 2), "roi": round(float(r.roi), 4)}
                             for k, r in by_q.iterrows()}
    return out


def verdict(summary, min_oos_trades=100, min_clusters=30, alpha=0.01):
    """Kill / promising / inconclusive per pmbt/README.md."""
    oos = summary.get("out_of_sample") or {}
    ins = summary.get("in_sample") or {}
    if not oos or oos.get("n_trades", 0) < min_oos_trades or oos.get("n_clusters", 0) < min_clusters:
        return "INCONCLUSIVE (insufficient out-of-sample data)"
    if oos["roi"] <= 0:
        return "KILL (out-of-sample ROI <= 0 after fees)"
    if oos["p_roi_le_0"] > alpha:
        return f"WEAK (OOS ROI>0 but not significant, p={oos['p_roi_le_0']:.3f})"
    if ins and ins.get("roi", 0) <= 0:
        return "WEAK (OOS positive but in-sample negative: unstable)"
    return "PROMISING (OOS ROI>0, significant, consistent with in-sample)"


def save(summary, path):
    def conv(o):
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        raise TypeError(type(o))
    with open(path, "w") as f:
        json.dump(summary, f, indent=2, default=conv)

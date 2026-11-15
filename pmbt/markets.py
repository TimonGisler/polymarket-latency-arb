"""Market metadata: cleaned, categorized, with parsed resolution outcome.

Build once with `python -m pmbt.markets` -> data/derived/markets.parquet
Columns added:
  mkt (uint32), category, yes_won (1/0, NaN if unresolved / 50-50), resolved (bool),
  yes_won_x / resolved_x (extended: near-certain final snapshots and 50-50 = 0.5; PREFER THESE),
  is_updown (recurring crypto up/down window), plus tape stats once the tape exists:
  first_ts, last_ts, n_trades, tape_usd.
"""
import os
import ast
import numpy as np
import pandas as pd

from pmbt.db import RAW, DERIVED, connect
from pmbt.fees import classify

MARKETS_PATH = os.path.join(DERIVED, "markets.parquet")


def _parse_outcome(s):
    try:
        v = [float(x) for x in ast.literal_eval(s)]
    except Exception:
        return np.nan
    if len(v) != 2:
        return np.nan
    if v[0] == 1.0 and v[1] == 0.0:
        return 1.0
    if v[0] == 0.0 and v[1] == 1.0:
        return 0.0
    return np.nan  # unresolved, 50/50, or mid-prices of open markets


def _parse_outcome_x(s):
    """Extended outcome: also accepts near-certain final snapshots (max >= 0.99) and 50-50 (=0.5).
    Use only for closed markets (open markets carry live prices)."""
    try:
        v = [float(x) for x in ast.literal_eval(s)]
    except Exception:
        return np.nan
    if len(v) != 2:
        return np.nan
    if abs(v[0] - 0.5) < 1e-9 and abs(v[1] - 0.5) < 1e-9:
        return 0.5
    if v[0] >= 0.99 and v[1] <= 0.01:
        return 1.0
    if v[1] >= 0.99 and v[0] <= 0.01:
        return 0.0
    return np.nan


def _to_unix_s(col):
    return col.dt.tz_convert(None).astype("datetime64[s]").astype("int64")


def build(with_tape_stats=True):
    df = pd.read_parquet(os.path.join(RAW, "markets.parquet"))
    df["mkt"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["mkt"])
    df["mkt"] = df["mkt"].astype("uint32")
    text = df["question"].fillna("") + " | " + df["event_title"].fillna("") + " | " + df["slug"].fillna("")
    # classify unique texts only (many repeats)
    uniq = pd.Series(text.unique())
    cat_map = dict(zip(uniq, uniq.map(classify)))
    df["category"] = text.map(cat_map)
    df["is_updown"] = df["slug"].str.contains("updown|up-or-down", regex=True, na=False) | \
        df["question"].str.contains("Up or Down", na=False)
    df.loc[df["is_updown"], "category"] = "crypto"
    df["yes_won"] = df["outcome_prices"].map(_parse_outcome)
    df["resolved"] = (df["closed"] == 1) & df["yes_won"].notna()
    # ~30% of 2026 closed markets store a near-certain snapshot (e.g. ['0.0005','0.9995']) instead of 1/0,
    # and 50-50 resolutions are otherwise dropped: prefer yes_won_x / resolved_x for backtests.
    df["yes_won_x"] = df["outcome_prices"].map(_parse_outcome_x).where(df["closed"] == 1)
    df["resolved_x"] = df["yes_won_x"].notna()
    df["end_ts"] = _to_unix_s(df["end_date"])
    df["created_ts"] = _to_unix_s(df["created_at"])
    keep = ["mkt", "question", "slug", "condition_id", "token1", "token2", "answer1", "answer2",
            "closed", "active", "volume", "event_id", "event_slug", "event_title", "created_ts",
            "end_ts", "neg_risk", "category", "is_updown", "yes_won", "resolved", "yes_won_x", "resolved_x"]
    df = df[keep]
    if with_tape_stats and os.path.exists(os.path.join(DERIVED, "tape")):
        con = connect()
        st = con.execute(f"""
            SELECT mkt, min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS n_trades, sum(usd) AS tape_usd
            FROM read_parquet('{DERIVED}/tape/*/*.parquet') GROUP BY mkt""").df()
        df = df.merge(st, on="mkt", how="left")
    df.to_parquet(MARKETS_PATH, index=False)
    return df


def load(columns=None):
    return pd.read_parquet(MARKETS_PATH, columns=columns)


if __name__ == "__main__":
    d = build()
    print(len(d), d["resolved"].sum())
    print(d.groupby("category").agg(n=("mkt", "size"), vol=("volume", "sum")).sort_values("vol"))

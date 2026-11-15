"""Execution helpers on the historical trade tape (no historical order books for most markets).

Conventions (see pmbt/README.md):
  * Every tape row is one maker fill at the maker's price, YES-normalized: p = YES price,
    tb = True if the taker bought YES (lifted the YES ask / sold NO), False if taker sold YES.
  * A *taker* entry decided at time t is executed at the price of the first real taker print on the
    same side strictly after t + latency (an ask that someone actually paid). Buying YES uses the
    first tb=True print (price p); buying NO uses the first tb=False print (NO price = 1 - p).
  * Available size = shares printed on that side within `window_s` after t + latency at a price no
    worse than the first print + `slip`. We cap our size at `max_share` of it.
  * A *maker* resting buy at limit b fills only from later opposite-side taker prints strictly
    through our price (queue-at-back, conservative), see `maker_fills`.
"""
import os
import pandas as pd

from pmbt.db import DERIVED, connect

TAPE = os.path.join(DERIVED, "tape", "*", "*.parquet")
BARS = os.path.join(DERIVED, "bars_1h.parquet")


def tape_sql(where=""):
    w = f"WHERE {where}" if where else ""
    return f"(SELECT * FROM read_parquet('{TAPE}', hive_partitioning=false) {w})"


def taker_entries(con, req: pd.DataFrame, latency_s=2, window_s=600, slip=0.01, max_share=0.25):
    """req: DataFrame[rid, mkt, t, side('yes'|'no'), want_shares(optional)].

    Returns req + [fill_ts, fill_p_yes, price (price paid for the chosen token), avail_shares].
    Rows with no print within window_s get NaN price (no fill)."""
    r = req.copy()
    r["t2"] = (r["t"] + latency_s).astype("int64")
    r["tb"] = r["side"].eq("yes")
    con.register("req_df", r[["rid", "mkt", "t2", "tb"]])
    lo, hi = int(r["t2"].min()), int(r["t2"].max() + window_s)
    q = f"""
    WITH tp AS (SELECT ts, mkt, p, sh, tb FROM {tape_sql(f'ts BETWEEN {lo} AND {hi}')}
                WHERE mkt IN (SELECT DISTINCT mkt FROM req_df)),
    first AS (
      SELECT q.rid, q.mkt, q.t2, q.tb, tp.ts AS fill_ts, tp.p AS fill_p_yes
      FROM req_df q ASOF JOIN tp ON q.mkt = tp.mkt AND q.tb = tp.tb AND q.t2 < tp.ts
    )
    SELECT f.rid, f.fill_ts, f.fill_p_yes,
      (SELECT sum(sh) FROM tp WHERE tp.mkt=f.mkt AND tp.tb=f.tb AND tp.ts > f.t2 AND tp.ts <= f.t2+{window_s}
         AND (CASE WHEN f.tb THEN tp.p <= f.fill_p_yes + {slip} ELSE tp.p >= f.fill_p_yes - {slip} END)) AS avail_shares
    FROM first f WHERE f.fill_ts <= f.t2 + {window_s}
    """
    res = con.execute(q).df()
    con.unregister("req_df")
    out = req.merge(res, on="rid", how="left")
    out["price"] = out["fill_p_yes"].where(out["side"].eq("yes"), 1 - out["fill_p_yes"])
    out["avail_shares"] = out["avail_shares"] * max_share
    return out


def last_price_before(con, req: pd.DataFrame, lookback_s=7 * 86400):
    """req: DataFrame[rid, mkt, t] -> + last_ts, last_p (YES price of last fill at or before t)."""
    con.register("req_lp", req[["rid", "mkt", "t"]])
    lo, hi = int(req["t"].min() - lookback_s), int(req["t"].max())
    q = f"""
    WITH tp AS (SELECT ts, mkt, p FROM {tape_sql(f'ts BETWEEN {lo} AND {hi}')}
                WHERE mkt IN (SELECT DISTINCT mkt FROM req_lp))
    SELECT q.rid, tp.ts AS last_ts, tp.p AS last_p
    FROM req_lp q ASOF JOIN tp ON q.mkt = tp.mkt AND q.t >= tp.ts
    """
    res = con.execute(q).df()
    con.unregister("req_lp")
    return req.merge(res, on="rid", how="left")


def build_bars(con=None):
    """Hourly YES bars per market: n, usd, vwap, first/last price, taker-buy & taker-sell VWAP."""
    con = con or connect(memory_limit="8GB")
    con.execute(f"""
    COPY (
      SELECT mkt, (ts // 3600) * 3600 AS hour, count(*) AS n, sum(usd) AS usd, sum(sh) AS sh,
             sum(p * sh) / nullif(sum(sh), 0) AS vwap,
             arg_min(p, ts) AS p_first, arg_max(p, ts) AS p_last, min(p) AS p_min, max(p) AS p_max,
             max(ts) AS last_ts,
             sum(CASE WHEN tb THEN sh END) AS sh_buy, sum(CASE WHEN NOT tb THEN sh END) AS sh_sell,
             sum(CASE WHEN tb THEN p * sh END) / nullif(sum(CASE WHEN tb THEN sh END), 0) AS vwap_buy,
             sum(CASE WHEN NOT tb THEN p * sh END) / nullif(sum(CASE WHEN NOT tb THEN sh END), 0) AS vwap_sell
      FROM read_parquet('{TAPE}', hive_partitioning=false)
      GROUP BY ALL ORDER BY mkt, hour
    ) TO '{BARS}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 500000)
    """)

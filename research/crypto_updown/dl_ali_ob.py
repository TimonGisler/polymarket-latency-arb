"""Pull a few days of BTC 5-minute BBO events (ms timestamps) from aliplayer1 orderbook part-0 using row-group pruning on ts_ms."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import sys, os, time, datetime as dt
sys.path.insert(0, ROOT)
from pmbt.db import connect
con = connect(memory_limit="2GB", threads=2); con.execute("set enable_progress_bar=false")
src = "hf://datasets/aliplayer1/polymarket-crypto-updown/data/orderbook/crypto=BTC/timeframe=5-minute/part-0.parquet"
for day in sys.argv[1:]:
    d0 = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000); d1 = d0 + 86400000
    dst = f"{ROOT}/data/ext/crypto/ali/ob/BTC5m_{day}.parquet"
    if os.path.exists(dst):
        continue
    t0 = time.time()
    con.execute(f"""COPY (SELECT ts_ms, market_id, outcome='Up' AS is_up, best_bid, best_ask, best_bid_size, best_ask_size FROM read_parquet('{src}')
                 WHERE ts_ms >= {d0} AND ts_ms < {d1} AND outcome='Up') TO '{dst}.tmp' (FORMAT parquet, COMPRESSION zstd)""")
    os.rename(dst + ".tmp", dst); print(day, round(time.time() - t0), "s", flush=True)

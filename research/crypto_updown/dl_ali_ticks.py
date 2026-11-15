"""Copy selected columns of aliplayer1 ticks (on-chain/WS fills) from HF to local parquet."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import sys, os, time
sys.path.insert(0, ROOT)
from pmbt.db import connect
OUT = ROOT + "/data/ext/crypto/ali/ticks"
con = connect(memory_limit="3GB", threads=2)
for spec in sys.argv[1:]:
    coin, tf = spec.split(":")
    dst = f"{OUT}/{coin}_{tf}.parquet"
    if os.path.exists(dst):
        continue
    src = f"hf://datasets/aliplayer1/polymarket-crypto-updown/data/ticks/crypto={coin}/timeframe={tf}/*.parquet"
    t0 = time.time()
    con.execute(f"""COPY (SELECT market_id, timestamp_ms, outcome, side, price, size_usdc, source, spot_price_usdt
                 FROM read_parquet('{src}', union_by_name=true) WHERE timestamp_ms > 1700000000000)
                 TO '{dst}.tmp' (FORMAT parquet, COMPRESSION zstd)""")
    os.rename(dst + ".tmp", dst)
    print(spec, round(time.time() - t0), "s", flush=True)

"""DuckDB connection helper configured for the sandbox proxy and HF remote parquet."""
import os
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
DERIVED = os.path.join(DATA, "derived")
HF_TRADES = "hf://datasets/SII-WANGZJ/Polymarket_data/trades.parquet"
HF_USERS = "hf://datasets/SII-WANGZJ/Polymarket_data/users.parquet"


def connect(path=":memory:", memory_limit="6GB", threads=None, read_only=False):
    con = duckdb.connect(path, read_only=read_only)
    con.execute("INSTALL httpfs; LOAD httpfs;")
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        con.execute(f"SET http_proxy='{proxy}'")
    if os.path.exists("/root/.ccr/ca-bundle.crt"):
        con.execute("SET ca_cert_file='/root/.ccr/ca-bundle.crt'")
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{os.path.join(DATA, 'duckdb_tmp')}'")
    if threads:
        con.execute(f"SET threads={threads}")
    return con

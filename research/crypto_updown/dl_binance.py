"""Download Binance spot 1s klines (data.binance.vision) -> one parquet per symbol (ts sec, close, open)."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import io, sys, zipfile, datetime as dt, urllib.request, os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
OUT = ROOT + "/data/ext/crypto/binance1s"
syms = sys.argv[1].split(",")
d0, d1 = dt.date.fromisoformat(sys.argv[2]), dt.date.fromisoformat(sys.argv[3])
days = [d0 + dt.timedelta(i) for i in range((d1 - d0).days + 1)]

def get(sym, d):
    url = f"https://data.binance.vision/data/spot/daily/klines/{sym}/1s/{sym}-1s-{d}.zip"
    for _ in range(3):
        try:
            b = urllib.request.urlopen(url, timeout=120).read()
            z = zipfile.ZipFile(io.BytesIO(b))
            df = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=[0, 1, 4, 5])
            df.columns = ["ot", "open", "close", "vol"]
            ot = df["ot"].astype("int64")
            df["ts"] = (ot // 1_000_000 if ot.iloc[0] > 1e14 else ot // 1000).astype("int64")
            return df[["ts", "open", "close", "vol"]]
        except Exception as e:
            err = e
    print("FAIL", sym, d, err, flush=True)
    return None

for sym in syms:
    path = f"{OUT}/{sym}.parquet"
    if os.path.exists(path):
        continue
    with ThreadPoolExecutor(4) as ex:
        parts = [p for p in ex.map(lambda d: get(sym, d), days) if p is not None]
    df = pd.concat(parts).sort_values("ts").drop_duplicates("ts")
    df.to_parquet(path, index=False)
    print(sym, len(df), flush=True)

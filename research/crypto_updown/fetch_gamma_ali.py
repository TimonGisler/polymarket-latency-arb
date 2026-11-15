"""Official outcomes (gamma outcomePrices) for aliplayer1 15m/1h/4h markets (BTC/ETH/SOL/XRP), by condition_id batches."""
import json, subprocess, pandas as pd, time
from concurrent.futures import ThreadPoolExecutor
from common import OUT, EXT
m = pd.read_parquet(f"{EXT}/ali/markets.parquet")
m = m[m.timeframe.isin(["15-minute", "1-hour", "4-hour"]) & m.crypto.isin(["BTC", "ETH", "SOL", "XRP"])]
ids = m.condition_id.tolist()
batches = [ids[i:i + 40] for i in range(0, len(ids), 40)]
def get(b):
    url = "https://gamma-api.polymarket.com/markets?closed=true&limit=100&" + "&".join("condition_ids=" + s for s in b)
    for k in range(4):
        try:
            r = subprocess.run(["curl", "-sS", "-m", "60", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
            return [(x["conditionId"], x.get("slug"), x.get("outcomePrices")) for x in json.loads(r)]
        except Exception:
            time.sleep(2 + 3 * k)
    return []
with ThreadPoolExecutor(6) as ex:
    res = [x for part in ex.map(get, batches) for x in part]
g = pd.DataFrame(res, columns=["condition_id", "slug", "op"]).drop_duplicates("condition_id")
op = g.op.map(lambda s: json.loads(s) if s else None)
g["up_gamma"] = op.map(lambda v: 1.0 if v and float(v[0]) == 1 else (0.0 if v and float(v[1]) == 1 else float("nan")))
g.to_parquet(f"{OUT}/gamma_res_ali.parquet", index=False)
print(len(ids), len(g), g.up_gamma.value_counts(dropna=False))

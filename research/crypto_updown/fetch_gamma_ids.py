"""gamma market id <-> condition_id for kacho windows (aliplayer1 markets.parquet stops at 2026-04-20, so later ws trades can't be mapped otherwise)."""
import json, subprocess, pandas as pd, sys, time
from concurrent.futures import ThreadPoolExecutor
from common import OUT
W = pd.read_parquet(f"{OUT}/windows.parquet", columns=["slug", "coin", "condition_id"])
W = W[W.coin.isin(sys.argv[1:])]
slugs = W.slug.tolist(); batches = [slugs[i:i + 50] for i in range(0, len(slugs), 50)]
def get(b):
    url = "https://gamma-api.polymarket.com/markets?closed=true&limit=100&" + "&".join("slug=" + s for s in b)
    for k in range(4):
        try:
            r = subprocess.run(["curl", "-sS", "-m", "60", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
            return [(str(m["id"]), m["conditionId"]) for m in json.loads(r)]
        except Exception:
            time.sleep(2 + 3 * k)
    return []
with ThreadPoolExecutor(6) as ex:
    res = [x for part in ex.map(get, batches) for x in part]
g = pd.DataFrame(res, columns=["market_id", "condition_id"]).drop_duplicates()
g.to_parquet(f"{OUT}/gamma_ids.parquet", index=False); print(len(W), len(g))

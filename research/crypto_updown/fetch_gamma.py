"""Fetch official resolutions (outcomePrices) for all kacho windows from gamma-api by slug (batches of 50)."""
import json, subprocess, pandas as pd, os, time
from concurrent.futures import ThreadPoolExecutor
from common import OUT
W = pd.read_parquet(f"{OUT}/windows.parquet", columns=["slug"])
slugs = W.slug.tolist()
batches = [slugs[i:i + 50] for i in range(0, len(slugs), 50)]

def get(b):
    url = "https://gamma-api.polymarket.com/markets?closed=true&limit=100&" + "&".join("slug=" + s for s in b)
    for k in range(4):
        try:
            r = subprocess.run(["curl", "-sS", "-m", "60", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
            return [(m["slug"], m.get("outcomePrices"), m.get("umaResolutionStatus"), m.get("closedTime")) for m in json.loads(r)]
        except Exception:
            time.sleep(2 + 3 * k)
    return []

with ThreadPoolExecutor(6) as ex:
    res = [x for part in ex.map(get, batches) for x in part]
g = pd.DataFrame(res, columns=["slug", "op", "uma", "closed_time"]).drop_duplicates("slug")
op = g.op.map(lambda s: json.loads(s) if s else None)
g["up_gamma"] = op.map(lambda v: 1.0 if v and float(v[0]) == 1 else (0.0 if v and float(v[1]) == 1 else (0.5 if v and float(v[0]) == 0.5 else float("nan"))))
g.to_parquet(f"{OUT}/gamma_res.parquet", index=False)
print(len(g), g.up_gamma.value_counts(dropna=False))

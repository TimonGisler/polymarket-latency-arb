"""Resolve HF dataset files to their signed CDN URL once, to avoid HF 'resolvers' rate limits (HTTP 429).

DuckDB's hf:// reader goes through huggingface.co/.../resolve/... for every range request, and the shared
IP quota there is 3000 calls / 5 min. One remote pass makes ~10k range requests, so it gets 429s.
The CDN URL (valid ~1 h) has no such quota.

    from pmbt.hfurl import signed_url, prep
    prep(con)                       # allow '*' in http paths (the signed URL contains 'filename*=')
    url = signed_url("trades.parquet")   # re-resolves automatically when < 10 min validity left
    con.execute(f"SELECT ... FROM read_parquet('{url}') ...")
"""
import re, time, urllib.request, urllib.error

REPO = "https://huggingface.co/datasets/SII-WANGZJ/Polymarket_data/resolve/main/"
_cache = {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def signed_url(name="trades.parquet", min_valid_s=600, tries=30):
    u, exp = _cache.get(name, (None, 0))
    if u and exp - time.time() > min_valid_s:
        return u
    opener = urllib.request.build_opener(_NoRedirect)
    for i in range(tries):
        try:
            opener.open(urllib.request.Request(REPO + name, method="GET"), timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers["Location"]
                m = re.search(r"Expires=(\d+)", loc)
                exp = int(m.group(1)) if m else time.time() + 1800
                _cache[name] = (loc, exp)
                return loc
            time.sleep(min(10 * (i + 1), 120))
        except Exception:
            time.sleep(min(10 * (i + 1), 120))
    raise RuntimeError(f"could not resolve {name}")


def prep(con):
    try:  # only needed (and only exists) on some DuckDB versions
        con.execute("SET allow_asterisks_in_http_paths = true")
    except Exception:
        pass
    return con

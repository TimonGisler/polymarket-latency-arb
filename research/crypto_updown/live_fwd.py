#!/usr/bin/env python3
"""Forward recorder for the #21c latency-arb test (read-only public data; no orders, no auth).

Streams (every record carries our LOCAL receive time in ms, `r`):
  pm    : Polymarket CLOB market websocket, one connection per BTC/ETH 5m & 15m up/down window
          (current + next window, discovered via gamma slugs <coin>-updown-<5m|15m>-<start_ts>). Raw messages
          (only with --raw: ~4 GB/day for BTC 5m alone).
  pmc   : the same, compact (default, ~0.2 GB/day for BTC 5m). Up token only (Down is its mirror), levels within
          BAND of the best bid/ask only. ts = server timestamp ms, start = window start (slug suffix). Rows:
            ["b", r, ts-r, start, [[price,size]..bids], [[price,size]..asks]]      book snapshot
            ["c", r, ts-r, start, price, size, "B"|"S", best_bid, best_ask]        level change (size = new level size)
            ["t", r, ts-r, start, is_up_token, price, size, "B"|"S"]               print (taker side, on the token traded)
            ["s", r, 0, start] / ["e", r, 0, start, err]                           (re)subscribed: book reset / error
  bn    : Binance spot trades via data-stream.binance.vision (btcusdt, ethusdt): [r, T_trade_ms, price, qty, buyer_is_maker]
  cb    : Coinbase Exchange 'matches' BTC-USD / ETH-USD: [r, time_iso, price, size, side]
  cl    : Polymarket RTDS crypto_prices_chainlink (+ crypto_prices): [r, topic, symbol, ts_ms, value]
  meta  : market metadata (slug, condition_id, token ids, start/end) as discovered
Output: data/ext/crypto/live/<YYYYmmdd_HH>_<stream>.jsonl.gz (hourly files).
Run:    docker compose up -d recorder   (docker-compose.yml: BTC 5m, compact, runs until stopped)
"""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import asyncio, collections, gzip, json, os, shutil, sys, time, argparse, urllib.request
import websockets

OUT = ROOT + "/data/ext/crypto/live"
os.makedirs(OUT, exist_ok=True)
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
COINS = ["btc", "eth"]
TFS = {"5m": 300, "15m": 900}
RAW = False
STARTED = int(time.time() * 1000)
BAND = 0.15          # compact mode keeps levels within this of the best bid/ask (replay walks only ask + 2c)
MIN_FREE_GB = 7.0    # stop writing below this (as Python counts it, ~0.6 GB above `df` Avail): the LP recorder shares the disk and stops at 5 GB


def compact(m, r, msg):
    """raw market-websocket message -> compact rows (see module docstring)"""
    up = m["tokens"][m["outcomes"].index("Up")]; st = m["start"]
    d = json.loads(msg)
    for e in (d if isinstance(d, list) else [d]):
        t = e.get("event_type"); dt = int(e.get("timestamp") or r) - r
        if t == "price_change":
            for c in e["price_changes"]:
                if c["asset_id"] != up:
                    continue
                p = float(c["price"])
                if float(c["best_bid"]) - BAND <= p <= float(c["best_ask"]) + BAND:
                    SINK.write("pmc", ["c", r, dt, st, c["price"], c["size"], c["side"][0], c["best_bid"], c["best_ask"]])
        elif t == "book":
            if e["asset_id"] != up:
                continue
            bb = max([float(l["price"]) for l in e["bids"]] or [0]); ba = min([float(l["price"]) for l in e["asks"]] or [1])
            SINK.write("pmc", ["b", r, dt, st, [[l["price"], l["size"]] for l in e["bids"] if float(l["price"]) >= bb - BAND],
                               [[l["price"], l["size"]] for l in e["asks"] if float(l["price"]) <= ba + BAND]])
        elif t == "last_trade_price":
            SINK.write("pmc", ["t", r, dt, st, int(e["asset_id"] == up), e["price"], e["size"], e["side"][0]])


def now_ms():
    return int(time.time() * 1000)


class Sink:
    """hourly-rotated gzip jsonl writers per stream"""
    def __init__(self):
        self.f = {}
        self.n = {}
        self.full = False   # set by flusher when the disk is nearly full
        self.last = {}      # stream -> last record (pmc: last level change), for data/status.json
        self.lag = collections.deque(maxlen=500)   # Binance: our receive time minus trade time, ms

    def write(self, stream, rec):
        if self.full:
            return
        key = time.strftime("%Y%m%d_%H", time.gmtime())
        h = self.f.get(stream)
        if h is None or h[0] != key:
            if h:
                h[1].close()
            h = (key, gzip.open(f"{OUT}/{key}_{stream}.jsonl.gz", "at", compresslevel=5))
            self.f[stream] = h
        h[1].write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.n[stream] = self.n.get(stream, 0) + 1
        if stream != "pmc" or (rec[0] == "c" and rec[3] * 1000 <= rec[1]):   # pmc: the running window, not the next
            self.last[stream] = rec
        if stream == "bn":
            self.lag.append(rec[0] - rec[2])

    def flush(self):
        for _, fh in self.f.values():
            fh.flush()


SINK = Sink()


def gamma(slugs):
    url = "https://gamma-api.polymarket.com/markets?limit=50&" + "&".join("slug=" + s for s in slugs)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


async def pm_market(m, stop_at):
    """one websocket connection per market window; reconnect on error until stop_at"""
    toks = m["tokens"]
    while time.time() < stop_at:
        try:
            async with websockets.connect(PM_WS, max_size=2 ** 24, ping_interval=None, open_timeout=15) as ws:
                await ws.send(json.dumps({"assets_ids": toks, "type": "market"}))
                if RAW:
                    SINK.write("pm", {"r": now_ms(), "slug": m["slug"], "sub": toks})
                else:
                    SINK.write("pmc", ["s", now_ms(), 0, m["start"]])
                last_ping = time.time()
                while time.time() < stop_at:
                    if time.time() - last_ping > 8:
                        await ws.send("PING"); last_ping = time.time()
                    try:
                        msg = await asyncio.wait_for(ws.recv(), 5)
                    except asyncio.TimeoutError:
                        continue
                    r = now_ms()
                    if msg == "PONG":
                        continue
                    if RAW:
                        SINK.write("pm", {"r": r, "slug": m["slug"], "m": msg})
                    else:
                        compact(m, r, msg)
        except Exception as e:
            if RAW:
                SINK.write("pm", {"r": now_ms(), "slug": m["slug"], "err": repr(e)[:200]})
            else:
                SINK.write("pmc", ["e", now_ms(), 0, m["start"], repr(e)[:200]])
            await asyncio.sleep(1)


async def discovery(stop_all):
    active = {}
    while time.time() < stop_all:
        t = int(time.time())
        slugs = []
        for c in COINS:
            for tf, L in TFS.items():
                s0 = t - t % L
                for s in (s0, s0 + L):
                    slug = f"{c}-updown-{tf}-{s}"
                    if slug not in active:
                        slugs.append(slug)
        if slugs:
            try:
                for mk in gamma(slugs):
                    toks = json.loads(mk["clobTokenIds"]); outs = json.loads(mk["outcomes"])
                    slug = mk["slug"]; start = int(slug.rsplit("-", 1)[1]); L = TFS[slug.split("-")[2]]
                    m = {"slug": slug, "condition_id": mk["conditionId"], "tokens": toks, "outcomes": outs,
                         "start": start, "end": start + L, "fee": mk.get("feeSchedule"), "r": now_ms()}
                    SINK.write("meta", m)
                    stop_at = min(stop_all, start + L + 90)
                    active[slug] = asyncio.create_task(pm_market(m, stop_at))
            except Exception as e:
                print("discovery error", repr(e)[:200], flush=True)
        for s in [s for s, tk in active.items() if tk.done()]:
            pass
        await asyncio.sleep(20)


async def binance(stop_all):
    url = "wss://data-stream.binance.vision/stream?streams=" + "/".join(f"{c}usdt@trade" for c in COINS)
    while time.time() < stop_all:
        try:
            async with websockets.connect(url, max_size=2 ** 22, open_timeout=15) as ws:
                while time.time() < stop_all:
                    msg = await asyncio.wait_for(ws.recv(), 30)
                    r = now_ms(); d = json.loads(msg)["data"]
                    SINK.write("bn", [r, d["s"], d["T"], float(d["p"]), float(d["q"]), d["m"]])
        except Exception as e:
            print("binance err", repr(e)[:200], flush=True); await asyncio.sleep(2)


async def coinbase(stop_all):
    url = "wss://ws-feed.exchange.coinbase.com"
    while time.time() < stop_all:
        try:
            async with websockets.connect(url, max_size=2 ** 22, open_timeout=15) as ws:
                await ws.send(json.dumps({"type": "subscribe", "product_ids": [f"{c.upper()}-USD" for c in COINS], "channels": ["matches"]}))
                while time.time() < stop_all:
                    msg = await asyncio.wait_for(ws.recv(), 30)
                    r = now_ms(); d = json.loads(msg)
                    if d.get("type") in ("match", "last_match"):
                        SINK.write("cb", [r, d["product_id"], d["time"], float(d["price"]), float(d["size"]), d["side"]])
        except Exception as e:
            print("coinbase err", repr(e)[:200], flush=True); await asyncio.sleep(2)


async def rtds(stop_all):
    url = "wss://ws-live-data.polymarket.com"
    sub = {"action": "subscribe", "subscriptions": [{"topic": "crypto_prices_chainlink", "type": "*", "filters": ""},
                                                    {"topic": "crypto_prices", "type": "update", "filters": ""}]}
    while time.time() < stop_all:
        try:
            async with websockets.connect(url, max_size=2 ** 22, open_timeout=15, ping_interval=None) as ws:
                await ws.send(json.dumps(sub)); last = time.time()
                while time.time() < stop_all:
                    if time.time() - last > 5:
                        await ws.send("PING"); last = time.time()
                    try:
                        msg = await asyncio.wait_for(ws.recv(), 5)
                    except asyncio.TimeoutError:
                        continue
                    r = now_ms()
                    if not msg or msg == "PONG":
                        continue
                    try:
                        d = json.loads(msg); p = d.get("payload", {})
                        if p.get("symbol") in [f"{c}/usd" for c in COINS] + [f"{c}usdt" for c in COINS]:
                            SINK.write("cl", [r, d.get("topic"), p["symbol"], p.get("timestamp"), p.get("value")])
                    except Exception:
                        pass
        except Exception as e:
            print("rtds err", repr(e)[:200], flush=True); await asyncio.sleep(2)


async def flusher(stop_all):
    while time.time() < stop_all:
        await asyncio.sleep(10)
        SINK.flush()
        free = shutil.disk_usage(OUT).free / 1e9
        if (free < MIN_FREE_GB) != SINK.full:
            SINK.full = free < MIN_FREE_GB
            print(time.strftime("%H:%M:%S"), f"disk free {free:.1f} GB:", "PAUSED, not writing" if SINK.full else "writing again", flush=True)
        st = {"t": now_ms(), "started": STARTED, "free_gb": round(free, 2), "paused": SINK.full, "n": SINK.n, "last": SINK.last,
              "bn_lag_ms": sorted(SINK.lag)[len(SINK.lag) // 2] if SINK.lag else None}
        with open(ROOT + "/data/status.json.tmp", "w") as f:    # read by dashboard.py
            json.dump(st, f)
        os.replace(ROOT + "/data/status.json.tmp", ROOT + "/data/status.json")
        if int(time.time()) % 300 < 10:
            print(time.strftime("%m-%d %H:%M:%S"), f"free={free:.1f}GB", SINK.n, flush=True)


async def main(hours):
    stop_all = time.time() + hours * 3600
    await asyncio.gather(discovery(stop_all), binance(stop_all), coinbase(stop_all), rtds(stop_all), flusher(stop_all))
    SINK.flush()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=float, default=3.5)
    ap.add_argument("--coins", default="btc,eth"); ap.add_argument("--tfs", default="5m,15m")
    ap.add_argument("--raw", action="store_true", help="store raw Polymarket messages (stream pm) instead of compact rows (pmc)")
    a = ap.parse_args(); RAW = a.raw
    COINS[:] = a.coins.split(","); TFS = {k: TFS[k] for k in a.tfs.split(",")}
    asyncio.run(main(a.hours))

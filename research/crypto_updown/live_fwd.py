#!/usr/bin/env python3
"""Forward recorder for the #21c latency-arb test (read-only public data; no orders, no auth).

Streams (every record carries our LOCAL receive time in ms, `r`):
  pm    : Polymarket CLOB market websocket, one connection per BTC/ETH 5m & 15m up/down window
          (current + next window, discovered via gamma slugs <coin>-updown-<5m|15m>-<start_ts>). Raw messages.
  bn    : Binance spot trades via data-stream.binance.vision (btcusdt, ethusdt): [r, T_trade_ms, price, qty, buyer_is_maker]
  cb    : Coinbase Exchange 'matches' BTC-USD / ETH-USD: [r, time_iso, price, size, side]
  cl    : Polymarket RTDS crypto_prices_chainlink (+ crypto_prices): [r, topic, symbol, ts_ms, value]
  meta  : market metadata (slug, condition_id, token ids, start/end) as discovered
Output: data/ext/crypto/live/<YYYYmmdd_HH>_<stream>.jsonl.gz (hourly files).
Run:    nohup python3 research/crypto_updown/live_fwd.py --hours 3.5 > data/ext/crypto/live/live_fwd.out 2>&1 &
"""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import asyncio, gzip, json, os, sys, time, argparse, subprocess, traceback
import websockets

OUT = ROOT + "/data/ext/crypto/live"
os.makedirs(OUT, exist_ok=True)
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
COINS = ["btc", "eth"]
TFS = {"5m": 300, "15m": 900}


def now_ms():
    return int(time.time() * 1000)


class Sink:
    """hourly-rotated gzip jsonl writers per stream"""
    def __init__(self):
        self.f = {}
        self.n = {}

    def write(self, stream, rec):
        key = time.strftime("%Y%m%d_%H", time.gmtime())
        h = self.f.get(stream)
        if h is None or h[0] != key:
            if h:
                h[1].close()
            h = (key, gzip.open(f"{OUT}/{key}_{stream}.jsonl.gz", "at", compresslevel=5))
            self.f[stream] = h
        h[1].write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.n[stream] = self.n.get(stream, 0) + 1

    def flush(self):
        for _, fh in self.f.values():
            fh.flush()


SINK = Sink()


def gamma(slugs):
    url = "https://gamma-api.polymarket.com/markets?limit=50&" + "&".join("slug=" + s for s in slugs)
    r = subprocess.run(["curl", "-sS", "-m", "20", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
    return json.loads(r)


async def pm_market(m, stop_at):
    """one websocket connection per market window; reconnect on error until stop_at"""
    toks = m["tokens"]
    while time.time() < stop_at:
        try:
            async with websockets.connect(PM_WS, max_size=2 ** 24, ping_interval=None, open_timeout=15) as ws:
                await ws.send(json.dumps({"assets_ids": toks, "type": "market"}))
                SINK.write("pm", {"r": now_ms(), "slug": m["slug"], "sub": toks})
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
                    SINK.write("pm", {"r": r, "slug": m["slug"], "m": msg})
        except Exception as e:
            SINK.write("pm", {"r": now_ms(), "slug": m["slug"], "err": repr(e)[:200]})
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
    url = "wss://data-stream.binance.vision/stream?streams=btcusdt@trade/ethusdt@trade"
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
                await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD", "ETH-USD"], "channels": ["matches"]}))
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
                        if p.get("symbol") in ("btc/usd", "eth/usd", "btcusdt", "ethusdt"):
                            SINK.write("cl", [r, d.get("topic"), p["symbol"], p.get("timestamp"), p.get("value")])
                    except Exception:
                        pass
        except Exception as e:
            print("rtds err", repr(e)[:200], flush=True); await asyncio.sleep(2)


async def flusher(stop_all):
    while time.time() < stop_all:
        await asyncio.sleep(10)
        SINK.flush()
        if int(time.time()) % 300 < 10:
            print(time.strftime("%H:%M:%S"), SINK.n, flush=True)


async def main(hours):
    stop_all = time.time() + hours * 3600
    await asyncio.gather(discovery(stop_all), binance(stop_all), coinbase(stop_all), rtds(stop_all), flusher(stop_all))
    SINK.flush()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=float, default=3.5)
    a = ap.parse_args()
    asyncio.run(main(a.hours))

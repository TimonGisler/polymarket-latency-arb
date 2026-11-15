"""Assemble result.json (framework schema: one entry per idea) from out/summaries.json and the per-idea json outputs."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import json
from common import OUT
S = json.load(open(f"{OUT}/summaries.json"))
i1 = json.load(open(f"{OUT}/idea1.json")); i19 = json.load(open(f"{OUT}/idea19.json")); i19b = json.load(open(f"{OUT}/idea19b.json"))
i34 = json.load(open(f"{OUT}/idea34.json"))
res = {"area": "crypto up/down (Polymarket recurring 5m/15m/1h/4h windows)", "data_period": "2026-03-24..2026-05-18 (5m books); 2025-12..2026-04 (15m/1h/4h prices)",
       "incident_exclusion": "2026-04-29..2026-05-04 excluded from taker tests (recorded books do not converge to official outcomes)",
       "ideas": [
    {"idea": 1, "name": "complement arb within up/down markets", "verdict": "KILL",
     "variants": [{"name": "parity crossings per coin", "params": {"fee_rate": 0.07}, **{"per_coin": i1}}],
     "best_variant_chosen_in_sample": None,
     "notes": "Up/Down books are a single mirrored book (bu=1-ad, au=1-bd in >99.95% of 1 Hz ticks); crossings are single-tick recorder glitches in 2-5 windows per coin over 56 days."},
    {"idea": 19, "name": "gambler's fallacy / streak bias", "verdict": "KILL (5m); WEAK (15m fade |streak|>=4)",
     "variants": [{"name": "5m streak tables + opening-ask trade rules", **i19}, {"name": "15m/1h/4h (CLOB price history open + 0.5c/1.5c half-spread)", **i19b}],
     "best_variant_chosen_in_sample": "fade_15-minute_k4 (IS +3.3% p=0.11; OOS +8.3% p=0.011; +1.5c spread OOS +6.3% p=0.036)",
     "notes": "5m: opening mid already shifts against the streak by the same amount realized outcomes do. 15m signal is not significant IS and uses non-executable history prices -> forward-record before believing."},
    {"idea": 21, "name": S["21"]["name"], "verdict": "KILL", "variants": S["21"]["variants"], "best_variant_chosen_in_sample": S["21"]["best_variant_chosen_in_sample"],
     "notes": "Binance-only Phi model is worse than the market mid (market sees Chainlink); all buckets negative OOS. Logloss tables in out/idea21.json."},
    {"idea": "21c", "name": S["21c"]["name"], "verdict": "PROMISING-unconfirmed: historical edge survives bias audit at reduced size (+3-4% IS / +7% OOS at 500 ms with print-confirmed or conservative fills); 3.6 h forward test in today's regime +9-10% at >=3 bp Binance signal but p~0.02-0.10 -> needs multi-day forward recording", "variants": S["21c"]["variants"],
     "best_variant_chosen_in_sample": S["21c"]["best_variant_chosen_in_sample"],
     "audit": {k: json.load(open(f"{OUT}/{k}.json")) for k in ("audit_21c", "audit_stale_curve")},
     "forward_test": json.load(open(ROOT + "/research/crypto_updown/out/live_replay.json")),
     "notes": "Event = Binance aggTrade with |1s return|>=thr; fill at recorded book ask (1 Hz, first sample >= T+L) or first/worst real print after T+L; held to official resolution; "
              "survives +1c and 2x latency; held-out 2026-04-27..05-18 also positive. Capacity ~$150-600/day at <=100 sh. Mar-May 2026 regime (pre-TWAP); needs live forward test."},
    {"idea": 31, "name": S["31"]["name"], "verdict": "KILL", "variants": S["31"]["variants"], "best_variant_chosen_in_sample": None,
     "notes": "Trade-through fills with 1-s-stale quotes: spread +0.55c/sh vs 5-s markout -2.3c/sh (BTC) and rebate +0.34c/sh at full pro-rata; same-second quotes still ~-1c/sh."},
    {"idea": 33, "name": S["33"]["name"], "verdict": "KILL", "variants": S["33"]["variants"], "best_variant_chosen_in_sample": None,
     "notes": "Favourite at ask ~-1% (fee); maker on favourite -4..-7%; apparent wins were incident-day 1c glitches that fail print confirmation."},
    {"idea": 34, "name": S["34"]["name"], "verdict": "KILL (imbalance alone); lead-lag part -> see 21c", "variants": S["34"]["variants"],
     "best_variant_chosen_in_sample": S["34"]["best_variant_chosen_in_sample"], "regressions": i34 if isinstance(i34, dict) else None,
     "notes": "imbalance coefficient 0.6-1.5c per unit vs >=2.3c cost; predictive power is the Binance last-second return."},
]}
json.dump(res, open(ROOT + "/research/crypto_updown/result.json", "w"), indent=1, default=float)
import shutil, glob
for f in glob.glob(f"{OUT}/*.json") + glob.glob(f"{OUT}/*.csv"):
    shutil.copy(f, ROOT + "/research/crypto_updown/out/")
print("ok")

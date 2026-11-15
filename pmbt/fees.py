"""Polymarket fee model (docs.polymarket.com/trading/fees, checked 2026-10-13).

taker fee (USDC) = shares * rate * p * (1 - p); makers pay 0 and receive a rebate share of the
fee-equivalent of their filled maker volume. We always apply TODAY's schedule to historical
trades (conservative: most history pre-dates fees, but any bot we run will pay today's fees).
"""
import re

TAKER_RATE = {
    "crypto": 0.07,
    "sports": 0.05,
    "finance": 0.04,
    "politics": 0.04,
    "economics": 0.05,
    "culture": 0.05,
    "weather": 0.05,
    "other": 0.05,
    "mentions": 0.04,
    "tech": 0.04,
    "geopolitics": 0.0,
}
MAKER_REBATE_SHARE = {
    "crypto": 0.20, "sports": 0.15, "geopolitics": 0.0,
}  # everything else 0.25


def taker_rate(category: str) -> float:
    return TAKER_RATE.get(category, 0.05)


def rebate_share(category: str) -> float:
    return MAKER_REBATE_SHARE.get(category, 0.25)


def taker_fee_per_share(p, category="other"):
    """Fee in USDC per share bought/sold at price p (works on numpy arrays)."""
    return taker_rate(category) * p * (1 - p)


def taker_fee(shares, p, category="other"):
    return round_fee(shares * taker_fee_per_share(p, category))


def round_fee(x):
    try:
        return round(x, 5)
    except TypeError:  # numpy array
        return x.round(5)


def max_maker_rebate_per_share(p, category="other"):
    """Upper bound on rebate per filled maker share (if we were the only maker in the market)."""
    return rebate_share(category) * taker_rate(category) * p * (1 - p)


# ---------------------------------------------------------------------------------------------
# Heuristic category classifier (question / slug / event title). Ordered: first match wins.
# Used for (a) fee estimation, (b) category-level analysis. Not perfect, documented as such.
# ---------------------------------------------------------------------------------------------
_RULES = [
    ("crypto", r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|doge|dogecoin|bnb|hype|hyperliquid|crypto|"
               r"memecoin|airdrop|fdv|token launch|coinbase|binance|microstrategy|stablecoin|altcoin|"
               r"pump\.fun|up or down|updown)\b"),
    ("weather", r"\b(temperature|weather|rain|snow|hurricane|tornado|°f|°c|celsius|fahrenheit|heat|"
                r"precipitation|degrees)\b"),
    ("mentions", r"\b(say|mention|said|tweet|tweets|post|posts|truth social)\b.*\b(times|during|"
                 r"speech|press conference|interview|word)\b|\bmentions?\b|# of tweets|tweet count"),
    ("sports", r"\b(vs\.?|nfl|nba|mlb|nhl|ncaa|ufc|fifa|uefa|premier league|la liga|serie a|bundesliga|"
               r"ligue 1|champions league|world cup|super bowl|stanley cup|world series|grand slam|"
               r"wimbledon|us open|french open|australian open|f1|formula 1|grand prix|golf|pga|masters|"
               r"tennis|soccer|football|basketball|baseball|hockey|cricket|boxing|fight|match|game \d|"
               r"esports|lol|dota|cs2|counter-strike|valorant|win the series|spread|o/u|over/under|"
               r"total (goals|points|runs)|moneyline|mvp|draft|playoffs?|championship|cup|open)\b"),
    ("economics", r"\b(cpi|inflation|gdp|unemployment|jobs report|nonfarm|payrolls|fed |fomc|interest rate|"
                  r"rate cut|rate hike|bps|recession|pce|jobless|treasury|yield|ecb|boe|boj)\b"),
    ("finance", r"\b(s&p|nasdaq|dow|stock|stocks|shares|ipo|earnings|eps|revenue|market cap|nvidia|"
                r"apple|tesla|amazon|microsoft|google|meta|close (above|below)|spx|qqq|gold|oil|"
                r"crude|silver|largest company)\b"),
    ("geopolitics", r"\b(war|ceasefire|invade|invasion|military|strike on|missile|nato|ukraine|russia|"
                    r"israel|gaza|hamas|iran|hezbollah|china.*taiwan|taiwan|north korea|nuclear|"
                    r"sanction|troops|peace deal|regime|coup|putin|zelensky|netanyahu|khamenei)\b"),
    ("politics", r"\b(election|elected|president|presidential|senate|house|congress|governor|mayor|"
                 r"prime minister|parliament|vote|primary|nominee|nomination|democrat|republican|"
                 r"trump|biden|harris|vance|newsom|desantis|cabinet|impeach|supreme court|scotus|"
                 r"approval rating|poll|party|minister|chancellor|executive order|tariff|"
                 r"government shutdown|bill|legislation)\b"),
    ("tech", r"\b(ai|openai|gpt|chatgpt|gemini|claude|anthropic|llm|apple event|iphone|spacex|starship|"
             r"launch|elon|musk|x\.com|twitter|tiktok|app store|model)\b"),
    ("culture", r"\b(movie|box office|album|song|billboard|grammy|oscar|emmy|spotify|netflix|"
                r"rotten tomatoes|taylor swift|celebrity|pregnant|baby|married|divorce|youtube|"
                r"mrbeast|kardashian|time person of the year|eurovision|tv show|season)\b"),
]
_COMPILED = [(c, re.compile(r, re.I)) for c, r in _RULES]


def classify(text: str) -> str:
    if not text:
        return "other"
    for cat, rx in _COMPILED:
        if rx.search(text):
            return cat
    return "other"

"""Quickstart: the latest gold price, three forex quotes in one request, and the last 10 M5 candles.

    pip install tickfeed
    export TICKFEED_API_KEY=mdp_...        (Windows: set TICKFEED_API_KEY=mdp_...)
    python examples/quickstart.py
"""

import sys

from tickfeed import TickFeed, TickFeedError

LABEL = {"fresh": "live", "market_closed": "MARKET CLOSED - last price", "stale": "STALE FEED"}


def main() -> int:
    tf = TickFeed()
    try:
        p = tf.price("XAUUSD")
    except TickFeedError as exc:
        print(f"Price unavailable: {exc}")
        return 1
    print(f"{p['symbol']} bid {p['bid']} ask {p['ask']} spread {p['spread']} ({p['spread_points']} pts) "
          f"at {p['tick_time']} [{LABEL[p['freshness']]}, {p['age_seconds']:.0f}s old]")

    print("\nSeveral pairs in one request:")
    for q in tf.prices(["EURUSD", "GBPUSD", "USDJPY"])["prices"]:
        print(f"  {q['symbol']}  {q['bid']} / {q['ask']}  [{LABEL[q['freshness']]}]")

    page = tf.candles("XAUUSD", "M5", limit=10)
    print(f"\nLast {page['count']} XAUUSD M5 candles (UTC open time):")
    for c in page["candles"]:
        flag = "" if c["complete"] else "  <- still forming"
        print(f"  {c['time']}  O {c['open']}  H {c['high']}  L {c['low']}  C {c['close']}  vol {c['tick_volume']}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

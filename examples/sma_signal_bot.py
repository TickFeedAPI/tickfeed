"""Trading-bot skeleton: SMA crossover SIGNALS on completed candles. Data only - it never places orders.

Shows how a bot should consume market data correctly:
  * decide only on COMPLETED bars (complete=True); the forming bar is ignored
  * act only when the feed is fresh (skip when market_closed or stale)
  * process each closed bar once, keyed by its open time
  * back off on errors instead of hammering the API (the client retries 429/503 itself)

Wire your own execution layer where it says so.

    pip install tickfeed
    export TICKFEED_API_KEY=mdp_...
    python examples/sma_signal_bot.py --symbol EURUSD --timeframe M5 --fast 9 --slow 21 [--once]
"""

import argparse
import sys
import time

from tickfeed import TickFeed, TickFeedError

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def sma(values: list[float], n: int) -> float:
    return sum(values[-n:]) / n


def evaluate(tf: TickFeed, symbol: str, timeframe: str, fast: int, slow: int, last_bar: str | None):
    price = tf.price(symbol)
    if price["freshness"] != "fresh":
        return last_bar, f"skip: feed is {price['freshness']} (tick {price['age_seconds']:.0f}s old)"
    bars = [c for c in tf.candles(symbol, timeframe, limit=slow + 5)["candles"] if c["complete"]]
    if len(bars) < slow + 1:
        return last_bar, f"skip: only {len(bars)} completed bars"
    newest = bars[-1]["time"]
    if newest == last_bar:
        return last_bar, None  # nothing new has closed yet
    closes = [c["close"] for c in bars]
    prev_diff = sma(closes[:-1], fast) - sma(closes[:-1], slow)
    diff = sma(closes, fast) - sma(closes, slow)
    if prev_diff <= 0 < diff:
        signal = "BULLISH crossover"
    elif prev_diff >= 0 > diff:
        signal = "BEARISH crossover"
    else:
        signal = "no crossover"
    msg = (f"bar {newest} close {closes[-1]}  SMA{fast}={sma(closes, fast):.5f} SMA{slow}={sma(closes, slow):.5f}  "
           f"-> {signal}  (bid {price['bid']} / ask {price['ask']})")
    # >>> Your execution logic would go here. This example deliberately does not trade. <<<
    return newest, msg


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--timeframe", default="M5", choices=list(TF_SECONDS))
    p.add_argument("--fast", type=int, default=9)
    p.add_argument("--slow", type=int, default=21)
    p.add_argument("--once", action="store_true", help="evaluate once and exit")
    args = p.parse_args()
    if args.fast >= args.slow:
        p.error("--fast must be smaller than --slow")
    tf = TickFeed()
    poll = max(5, TF_SECONDS[args.timeframe] // 10)
    last_bar = None
    while True:
        try:
            last_bar, msg = evaluate(tf, args.symbol, args.timeframe, args.fast, args.slow, last_bar)
            if msg:
                print(time.strftime("%H:%M:%S"), msg, flush=True)
        except TickFeedError as exc:
            print(time.strftime("%H:%M:%S"), f"error: {exc}; retrying later", flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main())

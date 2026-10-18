"""Download a historical candle range to CSV for backtesting, following pagination.

    pip install tickfeed
    export TICKFEED_API_KEY=mdp_...
    python examples/download_history.py --symbol XAUUSD --timeframe H1 --days 90 --out xauusd_h1.csv

Notes for correct backtests:
  * Only completed bars are written (a still-forming last bar is dropped).
  * Gaps stay gaps. The script reports them so you can decide how your backtest treats market
    closures - nothing is ever invented.
  * Timestamps are UTC bar OPEN times.
  * Cost: one request unit per 100 bars (a 5,000-bar page costs 50 units).
"""

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tickfeed import TIMEFRAMES, TickFeed, parse_time

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--timeframe", default="H1", choices=list(TIMEFRAMES))
    p.add_argument("--days", type=float, default=30)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    out = args.out or Path(f"{args.symbol.lower()}_{args.timeframe.lower()}.csv")
    tf = TickFeed()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    rows, forming = [], 0
    for c in tf.iter_candles(args.symbol, args.timeframe, start, end):
        if c["complete"]:
            rows.append(c)
        else:
            forming += 1
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "open", "high", "low", "close", "tick_volume", "spread_points"])
        for c in rows:
            w.writerow([c["time"], c["open"], c["high"], c["low"], c["close"], c["tick_volume"], c["spread_points"]])

    step = TF_SECONDS[args.timeframe]
    gaps = []
    for a, b in zip(rows, rows[1:]):
        delta = (parse_time(b["time"]) - parse_time(a["time"])).total_seconds()
        if delta > step:
            gaps.append((a["time"], b["time"], int(delta // step) - 1))
    print(f"Wrote {len(rows)} completed {args.timeframe} bars to {out} "
          f"({rows[0]['time'] if rows else '-'} .. {rows[-1]['time'] if rows else '-'}); "
          f"dropped {forming} forming bar(s).")
    print(f"Gaps between bars: {len(gaps)} (weekends and daily breaks are normal; nothing was filled)")
    for a, b, n in gaps[:10]:
        print(f"  {a} -> {b}  ({n} missing bars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

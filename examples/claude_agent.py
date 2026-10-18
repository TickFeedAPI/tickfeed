"""AI agent example: Claude answers market questions using TickFeed as tools.

Uses the Anthropic Python SDK's tool runner: Claude decides which tools to call, the SDK runs them
(they call the TickFeed API through the tickfeed client) and loops until done.
The agent analyses data; it does not trade.

    pip install tickfeed anthropic
    export TICKFEED_API_KEY=mdp_...
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/claude_agent.py "How have gold and EURUSD moved over the last 6 hours?"

No glue code needed if you use an MCP app (Claude Code, Claude Desktop, Cursor, VS Code):
see the mcp/ folder in this repository.
"""

import json
import sys

import anthropic
from anthropic import beta_tool

from tickfeed import TickFeed, TickFeedError

tf = TickFeed()

SYSTEM = (
    "You are a market-data analyst. Use the tools to fetch real data before answering; never guess "
    "prices. All timestamps are UTC and candle `time` is the bar open time. Check `freshness` on "
    "prices: only `fresh` is live; `market_closed` is the last price before a scheduled closure; "
    "`stale` signals a feed problem. Treat candles with complete=false as still forming. Gaps between "
    "candles are real (closures or missing data). Describe what the data shows; do not give "
    "personalised financial advice or tell the user to buy or sell."
)


def _json(fn, *args, **kwargs) -> str:
    try:
        return json.dumps(fn(*args, **kwargs))
    except TickFeedError as exc:  # let Claude see and explain the failure
        return json.dumps({"error": exc.code, "message": exc.message})


@beta_tool
def get_prices(symbols: list[str]) -> str:
    """Get the latest bid/ask for one or more symbols, each with tick time (UTC), age and freshness label.

    Args:
        symbols: Up to 30 symbols, e.g. ["XAUUSD", "EURUSD"].
    """
    return _json(tf.prices, symbols)


@beta_tool
def get_candles(symbol: str, timeframe: str = "M5", limit: int = 100) -> str:
    """Get the most recent OHLC candles, oldest first. The last one may be incomplete.

    Args:
        symbol: Symbol, e.g. XAUUSD or GBPJPY.
        timeframe: One of M1, M5, M15, M30, H1, H4, D1.
        limit: Number of candles, 1-500.
    """
    return _json(tf.candles, symbol, timeframe, max(1, min(int(limit), 500)))


@beta_tool
def list_symbols() -> str:
    """List every supported symbol with its category (metal, major, minor, exotic) and session."""
    return _json(tf.symbols)


def main() -> int:
    question = " ".join(sys.argv[1:]) or "What is gold (XAUUSD) doing right now, and how did it move over the last 12 H1 bars?"
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5-5",
        max_tokens=16000,
        system=SYSTEM,
        tools=[get_prices, get_candles, list_symbols],
        messages=[{"role": "user", "content": question}],
    )
    final = None
    for message in runner:
        final = message
        for block in message.content:
            if block.type == "tool_use":
                print(f"[tool] {block.name}({json.dumps(block.input)})", file=sys.stderr)
    if final is None:
        return 1
    print("".join(b.text for b in final.content if b.type == "text"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# TickFeed

**Gold and forex market data your bot and your AI can trust.** Live bid/ask quotes and complete OHLC candle
history for **60 forex pairs and 11 metals**, over a REST API and a built-in MCP server for AI assistants.
Every price tells you how old it is, and no candle is ever made up.

[Website](https://tickfeed.pro) · [Developer guide](https://tickfeed.pro/developer-guide) ·
[API reference](https://api.tickfeed.pro/docs) · [MCP setup](https://tickfeed.pro/agents) ·
[Status](https://tickfeed.pro/status)

This repository holds the official **Python client**, **runnable examples** and **MCP configuration** for
Claude Code, Claude Desktop, Cursor, VS Code and Windsurf.

**$10 of free credit** when you sign up and confirm your email. No card needed. After that it's pay as you go
from $0.002 per request, with no subscription. [Create an account](https://tickfeed.pro/signup).

---

## Why TickFeed

- **Freshness on every price.** Each quote is labelled `fresh`, `market_closed` (weekend or daily break) or
  `stale` (a feed problem during trading hours), with its age in seconds. Your bot never mistakes Friday's
  close for a live price.
- **Candles that tell the truth.** Bars still forming are flagged `complete: false`. Gaps are reported, never
  filled with invented data.
- **One clock.** Everything is UTC, with daylight-saving changes handled for you.
- **Built for AI agents.** A native MCP server with six read-only tools, so Claude, Cursor or Copilot can
  answer market questions from live data.
- **Simple pricing.** $0.002 per price quote, $0.002 per 100 candles, failed requests are free. Billed in USD,
  GBP or EUR.

## Install

```bash
pip install tickfeed
```

Standard library only; no dependencies. Add `tickfeed[pandas]` for DataFrame helpers.

## Quickstart

```python
from tickfeed import TickFeed

tf = TickFeed()   # reads TICKFEED_API_KEY, or TickFeed(api_key="mdp_...")

gold = tf.price("XAUUSD")
print(gold["bid"], gold["ask"], gold["freshness"])          # e.g. 4165.76 4166.16 fresh

# Several pairs in one request (counts once against your rate limit)
for q in tf.prices(["EURUSD", "GBPUSD", "USDJPY"])["prices"]:
    print(q["symbol"], q["bid"], q["ask"])

# The last 100 five-minute candles, oldest first
for bar in tf.candles("EURUSD", "M5", limit=100)["candles"]:
    print(bar["time"], bar["close"], "" if bar["complete"] else "(forming)")

# Long history, paginated for you
from datetime import datetime, timedelta, timezone
start = datetime.now(timezone.utc) - timedelta(days=90)
bars = list(tf.iter_candles("XAUUSD", "H1", start))
```

Or with plain HTTP:

```bash
curl -H "X-API-Key: $TICKFEED_API_KEY" https://api.tickfeed.pro/v1/price/XAUUSD
curl -H "X-API-Key: $TICKFEED_API_KEY" "https://api.tickfeed.pro/v1/prices?symbols=EURUSD,GBPUSD,XAUUSD"
curl -H "X-API-Key: $TICKFEED_API_KEY" "https://api.tickfeed.pro/v1/candles/EURUSD?timeframe=H1&limit=200"
```

## Use it from an AI assistant (MCP)

Server URL: `https://api.tickfeed.pro/mcp` (Streamable HTTP).

**Claude app (web, desktop, mobile), ChatGPT and other apps with MCP sign-in:** add a custom connector with that
URL, then sign in with your TickFeed account and click **Approve**. No key or config file needed.

**Code editors and scripts:** authenticate with `Authorization: Bearer <your key>` or `X-API-Key`.

**Claude Code**

```bash
claude mcp add --transport http tickfeed https://api.tickfeed.pro/mcp \
  --header "Authorization: Bearer YOUR_TICKFEED_KEY"
```

Ready-made configs for every client are in [`mcp/`](mcp):

| Client | File |
|---|---|
| Claude Code (team `.mcp.json`) | [`claude-code.mcp.json`](mcp/claude-code.mcp.json) |
| Claude Desktop | [`claude_desktop_config.json`](mcp/claude_desktop_config.json) |
| Cursor | [`cursor.mcp.json`](mcp/cursor.mcp.json) |
| VS Code (Copilot) | [`vscode.mcp.json`](mcp/vscode.mcp.json) |
| Windsurf | [`windsurf.mcp_config.json`](mcp/windsurf.mcp_config.json) |

**Tools:** `list_symbols`, `get_price`, `get_prices`, `get_candles`, `find_gaps`, `get_feed_health`.
All are read-only.

**Try asking:**

- "Is the gold market open right now, and what's the latest XAUUSD price?"
- "Compare how EURUSD, GBPUSD and USDJPY moved over the last 24 hourly candles."
- "Were there any unexpected gaps in XAUUSD M1 data yesterday?"

## Examples

| Script | What it shows |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | A price, a batch of quotes and recent candles |
| [`sma_signal_bot.py`](examples/sma_signal_bot.py) | A bot that acts only on completed bars and fresh prices (signals only, no orders) |
| [`download_history.py`](examples/download_history.py) | Paginated history to CSV for backtesting, with gap reporting |
| [`claude_agent.py`](examples/claude_agent.py) | Claude answering market questions with TickFeed as tools |
| [`mcp_client.py`](examples/mcp_client.py) | Calling the MCP server from your own code |

## Coverage

| Group | Symbols |
|---|---|
| Metals (11) | XAUUSD, XAGUSD, XPTUSD, XPDUSD, XAUEUR, XAUGBP, XAUAUD, XAUCHF, XAUJPY, XAGEUR, XAGAUD |
| Majors (7) | EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD, NZDUSD |
| Crosses (21) | EURGBP, EURJPY, EURCHF, EURAUD, EURCAD, EURNZD, GBPJPY, GBPCHF, GBPAUD, GBPCAD, GBPNZD, AUDJPY, AUDCHF, AUDCAD, AUDNZD, NZDJPY, NZDCHF, NZDCAD, CADJPY, CADCHF, CHFJPY |
| Exotics (32) | USDSGD, USDHKD, USDCNH, USDTHB, USDMXN, USDZAR, USDTRY, USDPLN, USDCZK, USDHUF, USDNOK, USDSEK, USDDKK, EURSGD, EURHKD, EURNOK, EURSEK, EURDKK, EURPLN, EURTRY, EURZAR, GBPSGD, GBPNOK, GBPSEK, GBPDKK, GBPTRY, AUDSGD, CHFSGD, SGDJPY, NOKJPY, SEKJPY, NOKSEK |

Timeframes: M1, M5, M15, M30, H1, H4, D1. `tf.symbols()` (free) always returns the current list.

## Errors and retries

The client raises `TickFeedError` with `.status` and `.code` (for example `unsupported_symbol`,
`insufficient_balance`). It retries `429` (honouring `Retry-After`), `503` and connection errors with
exponential backoff, up to `max_retries` (default 3). See the
[developer guide](https://tickfeed.pro/developer-guide) for every error code.

## About the data

Prices are live OTC bid/ask quotes from a professional dealing feed, timestamped to the millisecond in UTC.
Spot forex and gold trade over the counter, so quotes can differ slightly between providers; they are not an
official benchmark such as the LBMA gold price. More on the [About page](https://tickfeed.pro/about).

TickFeed provides market data only. It does not give investment advice or execute trades.

## License

The code in this repository is MIT licensed. Use of the TickFeed API is subject to the
[Terms of Service](https://tickfeed.pro/terms).

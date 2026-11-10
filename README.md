# TickFeed

**Gold and forex market data your bot and your AI can trust.** Live bid/ask quotes, OHLC candles and raw
tick history for **60 forex pairs and 11 metals**, over a REST API and a built-in MCP server for AI assistants.
Every price tells you how old it is, and no candle is ever made up.

[Website](https://tickfeed.pro) · [Developer guide](https://tickfeed.pro/developer-guide) ·
[API reference](https://api.tickfeed.pro/docs) · [MCP setup](https://tickfeed.pro/agents) ·
[Status](https://tickfeed.pro/status)

This repository holds the official **Python client**, **runnable examples** and **MCP configuration** for
Claude Code, Claude Desktop, Cursor, VS Code and Windsurf.

**Free credit when you confirm your email**, no card needed: the current amount and any end date are on the
[sign-up page](https://tickfeed.pro/signup). After that it's pay as you go from $0.002 per request, with no
subscription.

**Try it before you sign up:** the [API playground](https://tickfeed.pro/playground) runs a real
`GET /v1/price` request for XAUUSD, EURUSD or GBPUSD in your browser, no account needed.

### From sign-up to your first request

1. [Create an account](https://tickfeed.pro/signup) and confirm your email with the code we send. The free credit
   is added to your balance at that moment.
2. In the dashboard, open **API keys** and create one. It is shown once, so save it (for example as
   `TICKFEED_API_KEY`).
3. Make a request (below). Every response carries an `X-Balance` header, and `tf.usage()` (free) shows your balance.
4. Add funds only when the balance runs low, or straight away if your account got no free credit: a request the
   balance can't cover returns `402 insufficient_balance`.

Turn on two-factor sign-in in the dashboard within 14 days of signing up. It doesn't block your first requests,
but after that deadline API access pauses until it is on.

---

## Why TickFeed

- **Freshness on every price.** Each quote is labelled `fresh`, `market_closed` (weekend or daily break) or
  `stale` (a feed problem during trading hours), with its age in seconds. Your bot never mistakes Friday's
  close for a live price.
- **Candles that tell the truth.** Bars still forming are flagged `complete: false`. Gaps are reported, never
  filled with invented data.
- **One clock.** Everything is UTC, with daylight-saving changes handled for you.
- **Built for AI agents.** A native MCP server with seven read-only tools, so Claude, Cursor or Copilot can
  answer market questions from live data.
- **Simple pricing.** $0.002 per price quote, $0.002 per 100 candles, $0.002 per 1,000 ticks; failed requests
  are free. Billed in USD, GBP or EUR.

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

### Seconds candles and raw ticks (client 0.2.0)

> **Not on PyPI yet.** `pip install tickfeed` currently installs **0.1.0**, which rejects `S1`, `S5`, `S15` and
> `S30` with `ValueError` before sending anything and has no `ticks()` method. The API itself already serves both.
> Until 0.2.0 is released on PyPI, call the REST endpoints directly (curl below).
> Check what you have with `python -c "import tickfeed; print(tickfeed.__version__)"`.

```python
from datetime import datetime, timedelta, timezone

from tickfeed import TickFeed

tf = TickFeed()

# One-second gold candles for the last minute (built from tick history: live only, no gap report)
for bar in tf.candles("XAUUSD", "S1", limit=60)["candles"]:
    print(bar["time"], bar["close"], bar["tick_volume"])

# The latest 100 raw ticks: every bid/ask change, UTC to the millisecond, oldest first
for t in tf.ticks("XAUUSD", limit=100)["ticks"]:
    print(t["time"], t["bid"], t["ask"])

# A longer range, following the server's next_start_time (ticks that share a millisecond are never split)
start = datetime.now(timezone.utc) - timedelta(minutes=5)
ticks = list(tf.iter_ticks("XAUUSD", start))
print(len(ticks), "ticks")
```

The same over plain HTTP, which works whatever client version you have:

```bash
curl -H "X-API-Key: $TICKFEED_API_KEY" "https://api.tickfeed.pro/v1/candles/XAUUSD?timeframe=S1&limit=60"
curl -H "X-API-Key: $TICKFEED_API_KEY" "https://api.tickfeed.pro/v1/ticks/XAUUSD?limit=100"
```

## Rate limits

Each account can make **120 requests per minute**, in a rolling 60-second window shared by all of its keys (extra
keys don't add capacity). Over the limit you get `429 rate_limited` with `Retry-After`, which the client honours.
`tf.prices([...])` fetches up to 30 symbols in one request: it uses one slot of the limit and is billed per symbol
returned. The `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers show where you stand.

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

**Tools (7, all read-only):** `list_symbols`, `get_price`, `get_prices`, `get_candles`, `get_ticks`, `find_gaps`,
`get_feed_health`. These are the MCP server's tools; the Python client calls the REST API directly and does not
need MCP.

**Try asking:**

- "Is the gold market open right now, and what's the latest XAUUSD price?"
- "Compare how EURUSD, GBPUSD and USDJPY moved over the last 24 hourly candles."
- "Were there any unexpected gaps in XAUUSD M1 data yesterday?"

## Examples

| Script | What it shows | Install |
|---|---|---|
| [`quickstart.py`](examples/quickstart.py) | A price, a batch of quotes and recent candles | `pip install tickfeed` |
| [`sma_signal_bot.py`](examples/sma_signal_bot.py) | A bot that acts only on completed bars and fresh prices (signals only, no orders) | `pip install tickfeed` |
| [`download_history.py`](examples/download_history.py) | Paginated history to CSV for backtesting, with gap reporting | `pip install tickfeed` |
| [`claude_agent.py`](examples/claude_agent.py) | Claude answering market questions with TickFeed as tools | `pip install tickfeed anthropic` |
| [`mcp_client.py`](examples/mcp_client.py) | Calling the MCP server from your own code | `pip install "mcp>=2"` |

## Coverage

| Group | Symbols |
|---|---|
| Metals (11) | XAUUSD, XAGUSD, XPTUSD, XPDUSD, XAUEUR, XAUGBP, XAUAUD, XAUCHF, XAUJPY, XAGEUR, XAGAUD |
| Majors (7) | EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD, NZDUSD |
| Crosses (21) | EURGBP, EURJPY, EURCHF, EURAUD, EURCAD, EURNZD, GBPJPY, GBPCHF, GBPAUD, GBPCAD, GBPNZD, AUDJPY, AUDCHF, AUDCAD, AUDNZD, NZDJPY, NZDCHF, NZDCAD, CADJPY, CADCHF, CHFJPY |
| Exotics (32) | USDSGD, USDHKD, USDCNH, USDTHB, USDMXN, USDZAR, USDTRY, USDPLN, USDCZK, USDHUF, USDNOK, USDSEK, USDDKK, EURSGD, EURHKD, EURNOK, EURSEK, EURDKK, EURPLN, EURTRY, EURZAR, GBPSGD, GBPNOK, GBPSEK, GBPDKK, GBPTRY, AUDSGD, CHFSGD, SGDJPY, NOKJPY, SEKJPY, NOKSEK |

Candle timeframes: S1, S5, S15, S30, M1, M5, M15, M30, H1, H4, D1 (the seconds timeframes need client 0.2.0 or
REST; see above). `tf.symbols()` (free) always returns the current list.

**History depth varies by instrument and timeframe.** Some daily and four-hour series go back years, one-minute
history is much shorter, and seconds candles and raw ticks cover about the last six months, rolling. Before you
plan a long backtest, check `history_from` in `tf.symbols()`: the earliest stored bar for every symbol and
timeframe.

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

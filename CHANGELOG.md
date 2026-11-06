# Changelog

## 0.2.0 (unreleased)

Not yet published to PyPI: `pip install tickfeed` still installs 0.1.0 until this version is released.

- `candles()`, `iter_candles()` and `candles_df()` accept the seconds timeframes `S1`, `S5`, `S15` and `S30`, which
  the API already served. 0.1.0 rejected them with `ValueError` before sending a request. Seconds candles are built
  from tick history (about the last six months), so `source="stored"` with a seconds timeframe raises `ValueError`.
- New `ticks()` for `GET /v1/ticks/{symbol}` (raw bid/ask changes, millisecond UTC timestamps) and `iter_ticks()`,
  which follows the server's `next_start_time` so ticks sharing a millisecond are never split, repeated or skipped.
- New constants `SECONDS_TIMEFRAMES` and `CANDLE_TIMEFRAMES` (all eleven). `TIMEFRAMES` is unchanged (`M1` to `D1`,
  the stored timeframes) so code that uses it for gap reports or stored history keeps working.
- `gaps()` raises `ValueError` for a seconds timeframe (the API has no gap report for them) instead of sending a
  request that returns 422.
- README: first-request steps in the order that works (confirm email, create key, call), rate-limit scope, current
  MCP tool list (7, including `get_ticks`), history depth, and install commands for each example.

## 0.1.0 (2026-10-18)

First public release of the official Python client.

- `TickFeed` client: `price`, `prices` (batch, up to 30 symbols), `candles`, `iter_candles` (pagination),
  `gaps`, `symbols`, `usage`, `health`, and `candles_df` (pandas).
- Typed errors (`TickFeedError`, `RateLimitedError`, `UnavailableError`) and automatic retries for 429/503.
- Examples: quickstart, SMA signal bot, history download, Claude agent, MCP client.
- MCP configuration for Claude Code, Claude Desktop, Cursor, VS Code and Windsurf.

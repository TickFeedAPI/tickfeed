# Changelog

## 0.1.0 (2026-10-18)

First public release of the official Python client.

- `TickFeed` client: `price`, `prices` (batch, up to 30 symbols), `candles`, `iter_candles` (pagination),
  `gaps`, `symbols`, `usage`, `health`, and `candles_df` (pandas).
- Typed errors (`TickFeedError`, `RateLimitedError`, `UnavailableError`) and automatic retries for 429/503.
- Examples: quickstart, SMA signal bot, history download, Claude agent, MCP client.
- MCP configuration for Claude Code, Claude Desktop, Cursor, VS Code and Windsurf.

# Claude Code

```bash
claude mcp add --transport http tickfeed https://api.tickfeed.pro/mcp \
  --header "Authorization: Bearer YOUR_TICKFEED_KEY"
```

Add `--scope user` to make TickFeed available in every project. Check it with `claude mcp list`.

To share with a team, commit [`.mcp.json`](claude-code.mcp.json) to your repository root; each person sets
`TICKFEED_API_KEY` in their own environment, so no key is committed.

"""Official Python client for the TickFeed market data API. Standard library only.

    from tickfeed import TickFeed

    tf = TickFeed()                      # reads TICKFEED_API_KEY, or pass api_key="mdp_..."
    price = tf.price("XAUUSD")
    if price["freshness"] == "fresh":
        print(price["bid"], price["ask"])

    quotes = tf.prices(["EURUSD", "GBPUSD", "USDJPY"])["prices"]   # several pairs, one request
    bars = tf.candles("EURUSD", "M5", limit=100)["candles"]

Errors raise TickFeedError (with .status and .code). 429 and 503 responses and connection errors
are retried with backoff (honouring Retry-After) up to ``max_retries`` times.

Docs: https://tickfeed.pro/developer-guide
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

__version__ = "0.1.0"
__all__ = ["TickFeed", "TickFeedError", "RateLimitedError", "UnavailableError", "parse_time", "TIMEFRAMES"]

DEFAULT_BASE_URL = "https://api.tickfeed.pro"
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


class TickFeedError(Exception):
    """An error returned by the API (``status`` is the HTTP status, ``code`` the API error code)."""

    def __init__(self, status: int | None, code: str, message: str):
        super().__init__(f"{code}: {message}" + (f" (HTTP {status})" if status else ""))
        self.status, self.code, self.message = status, code, message


class RateLimitedError(TickFeedError):
    """HTTP 429: too many requests. ``retry_after`` is the number of seconds to wait."""

    def __init__(self, status, code, message, retry_after: float):
        super().__init__(status, code, message)
        self.retry_after = retry_after


class UnavailableError(TickFeedError):
    """HTTP 503: the service is up but data is temporarily unavailable, or it is busy. Safe to retry."""


def _iso(value: datetime | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    """Parse an API timestamp (ISO 8601 with a 'Z' suffix) into an aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TickFeed:
    """Client for https://api.tickfeed.pro. Thread-safe; holds no connection state."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 15.0, max_retries: int = 3, user_agent: str | None = None):
        self.api_key = api_key or os.environ.get("TICKFEED_API_KEY")
        if not self.api_key:
            raise ValueError("No API key: pass api_key=... or set TICKFEED_API_KEY "
                             "(create one at https://tickfeed.pro/dashboard)")
        self.base_url = base_url.rstrip("/")
        self.timeout, self.max_retries = timeout, max_retries
        self.user_agent = user_agent or f"tickfeed-python/{__version__}"

    def __repr__(self) -> str:  # never show the key
        return f"TickFeed(base_url={self.base_url!r})"

    # ---- transport ---------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None, auth: bool = True) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if auth:
            headers["X-API-Key"] = self.api_key
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                err = self._error_from(e)
                if path == "/health" and e.code == 503:
                    return json.loads(err.raw) if getattr(err, "raw", None) else {"status": "down"}
                retryable = isinstance(err, (RateLimitedError, UnavailableError))
                if not retryable or attempt >= self.max_retries:
                    raise err from None
                delay = err.retry_after if isinstance(err, RateLimitedError) else self._backoff(attempt, err)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt >= self.max_retries:
                    raise TickFeedError(None, "connection_error", str(getattr(e, "reason", e))) from None
                delay = self._backoff(attempt)
            attempt += 1
            time.sleep(delay)

    @staticmethod
    def _backoff(attempt: int, err: TickFeedError | None = None) -> float:
        hinted = getattr(err, "retry_after", None)
        return hinted if hinted else min(30.0, 2 ** attempt) + random.uniform(0, 0.5)

    @staticmethod
    def _error_from(e: urllib.error.HTTPError) -> TickFeedError:
        raw = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
            code, message = body["error"]["code"], body["error"]["message"]
        except (ValueError, KeyError, TypeError):
            code, message = "http_error", raw[:200] or e.reason
        retry_after = e.headers.get("Retry-After") if e.headers else None
        if e.code == 429:
            err: TickFeedError = RateLimitedError(e.code, code, message, float(retry_after or 5))
        elif e.code == 503:
            err = UnavailableError(e.code, code, message)
            if retry_after:
                err.retry_after = float(retry_after)  # type: ignore[attr-defined]
        else:
            err = TickFeedError(e.code, code, message)
        err.raw = raw  # type: ignore[attr-defined]
        return err

    # ---- endpoints ------------------------------------------------------------------------
    def health(self) -> dict:
        """Service and feed health (no API key needed). Returns the body even when it reports 'down'."""
        return self._get("/health", auth=False)

    def symbols(self) -> dict:
        """Every supported symbol with its category, session and precision. Free."""
        return self._get("/v1/symbols")

    def usage(self) -> dict:
        """Your balance, unit price and recent spend. Free."""
        return self._get("/v1/usage")

    def price(self, symbol: str) -> dict:
        """Latest bid/ask. Check result['freshness'] ('fresh' | 'market_closed' | 'stale')."""
        return self._get(f"/v1/price/{urllib.parse.quote(symbol)}")

    def prices(self, symbols: Iterable[str]) -> dict:
        """Latest bid/ask for up to 30 symbols in one request: {'prices': [...]} in request order.
        Costs one unit per symbol and counts once against your rate limit."""
        names = [s.strip() for s in symbols if s and s.strip()]
        if not names:
            raise ValueError("symbols must contain at least one symbol")
        return self._get("/v1/prices", {"symbols": ",".join(names)})

    def candles(self, symbol: str, timeframe: str = "M5", limit: int = 100,
                start_time: datetime | str | None = None, end_time: datetime | str | None = None,
                source: str = "live") -> dict:
        """One page of OHLC candles, oldest first. The last bar may have complete=False."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {TIMEFRAMES}")
        return self._get(f"/v1/candles/{urllib.parse.quote(symbol)}", {
            "timeframe": timeframe, "limit": limit, "start_time": _iso(start_time),
            "end_time": _iso(end_time), "source": source,
        })

    def iter_candles(self, symbol: str, timeframe: str, start_time: datetime | str,
                     end_time: datetime | str | None = None, page_size: int = 5000,
                     source: str = "live") -> Iterator[dict]:
        """Yield every candle in [start_time, end_time], following pagination. Nothing is filled in:
        where the market was closed or data is missing, bars are simply absent."""
        cursor: datetime | str | None = start_time
        while cursor is not None:
            page = self.candles(symbol, timeframe, page_size, cursor, end_time, source)
            yield from page["candles"]
            cursor = page["next_start_time"] if page["truncated"] else None

    def gaps(self, symbol: str, timeframe: str = "M5", start_time: datetime | str | None = None,
             end_time: datetime | str | None = None) -> dict:
        """Missing intervals in stored history, each marked expected (market closed) or not."""
        return self._get(f"/v1/candles/{urllib.parse.quote(symbol)}/gaps", {
            "timeframe": timeframe, "start_time": _iso(start_time), "end_time": _iso(end_time)})

    def candles_df(self, symbol: str, timeframe: str = "M5", limit: int = 100,
                   completed_only: bool = True, **kwargs):
        """Candles as a pandas DataFrame indexed by UTC open time (requires ``pip install tickfeed[pandas]``).
        completed_only=True drops a still-forming last bar."""
        import pandas as pd

        rows = self.candles(symbol, timeframe, limit, **kwargs)["candles"]
        if completed_only:
            rows = [r for r in rows if r["complete"]]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df.set_index("time")

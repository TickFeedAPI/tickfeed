"""Official Python client for the TickFeed market data API. Standard library only.

    from tickfeed import TickFeed

    tf = TickFeed()                      # reads TICKFEED_API_KEY, or pass api_key="mdp_..."
    price = tf.price("XAUUSD")
    if price["freshness"] == "fresh":
        print(price["bid"], price["ask"])

    quotes = tf.prices(["EURUSD", "GBPUSD", "USDJPY"])["prices"]   # several pairs, one request
    bars = tf.candles("EURUSD", "M5", limit=100)["candles"]
    secs = tf.candles("XAUUSD", "S1", limit=60)["candles"]       # seconds bars, built from tick history
    ticks = tf.ticks("XAUUSD", limit=100)["ticks"]                 # raw bid/ask changes, millisecond UTC

Errors raise TickFeedError (with .status and .code). 429 and 503 responses and connection errors
are retried with backoff (honouring Retry-After) up to ``max_retries`` times.

Connections are kept open and reused (one per thread), so only the first request pays for the TCP and TLS
handshake. Create one client and reuse it; ``with TickFeed() as tf:`` or ``tf.close()`` closes the connections.

Docs: https://tickfeed.pro/developer-guide
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import random
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

__version__ = "0.2.0"
__all__ = ["TickFeed", "TickFeedError", "RateLimitedError", "UnavailableError", "parse_time", "TIMEFRAMES",
           "SECONDS_TIMEFRAMES", "CANDLE_TIMEFRAMES"]

DEFAULT_BASE_URL = "https://api.tickfeed.pro"
# Minute-and-longer timeframes: stored history, source="stored" and gap reports. Unchanged since 0.1.0.
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
# Seconds timeframes: built on request from tick history (about the last six months, rolling). Live only
# (no source="stored") and no gap report.
SECONDS_TIMEFRAMES = ("S1", "S5", "S15", "S30")
# Every timeframe GET /v1/candles accepts.
CANDLE_TIMEFRAMES = SECONDS_TIMEFRAMES + TIMEFRAMES


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
    """Client for https://api.tickfeed.pro. Thread-safe: each thread reuses its own keep-alive connection.

    Proxies are taken from the environment like urllib does (HTTPS_PROXY / HTTP_PROXY / NO_PROXY, and the system
    settings on Windows and macOS), read once when the client is created."""

    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 15.0, max_retries: int = 3, user_agent: str | None = None):
        self.api_key = api_key or os.environ.get("TICKFEED_API_KEY")
        if not self.api_key:
            raise ValueError("No API key: pass api_key=... or set TICKFEED_API_KEY "
                             "(create one at https://tickfeed.pro/dashboard)")
        self.base_url = base_url.rstrip("/")
        self.timeout, self.max_retries = timeout, max_retries
        self.user_agent = user_agent or f"tickfeed-python/{__version__}"
        u = urllib.parse.urlsplit(self.base_url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError(f"base_url must be an http(s) URL, got {base_url!r}")
        self._scheme, self._host = u.scheme, u.hostname
        self._port = u.port or (443 if u.scheme == "https" else 80)
        self._prefix = u.path.rstrip("/")
        self._proxy = self._proxy_for(u.scheme, u.hostname)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._conns: set[http.client.HTTPConnection] = set()

    def __repr__(self) -> str:  # never show the key
        return f"TickFeed(base_url={self.base_url!r})"

    def __enter__(self) -> "TickFeed":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Close every open connection (all threads). The client stays usable: the next request reconnects."""
        with self._lock:
            conns, self._conns = self._conns, set()
        for conn in conns:
            conn.close()

    # ---- transport ---------------------------------------------------------------------
    @staticmethod
    def _proxy_for(scheme: str, host: str) -> urllib.parse.SplitResult | None:
        proxy = urllib.request.getproxies().get(scheme)
        if not proxy or urllib.request.proxy_bypass(host):
            return None
        return urllib.parse.urlsplit(proxy if "://" in proxy else f"http://{proxy}")

    def _proxy_auth(self) -> dict[str, str]:
        p = self._proxy
        if p is None or p.username is None:
            return {}
        cred = f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}"
        return {"Proxy-Authorization": "Basic " + base64.b64encode(cred.encode()).decode()}

    def _new_connection(self) -> http.client.HTTPConnection:
        p = self._proxy
        if self._scheme == "https":
            ctx = ssl.create_default_context()  # verifies the certificate and host name, like urllib
            if p is None:
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    self._host, self._port, timeout=self.timeout, context=ctx)
            else:  # CONNECT tunnel through the proxy, then TLS to the API host
                conn = http.client.HTTPSConnection(p.hostname, p.port or 80, timeout=self.timeout, context=ctx)
                conn.set_tunnel(self._host, self._port, headers=self._proxy_auth())
        elif p is None:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=self.timeout)
        else:  # plain http through a proxy: absolute URLs (see _target)
            conn = http.client.HTTPConnection(p.hostname, p.port or 80, timeout=self.timeout)
        with self._lock:
            self._conns.add(conn)
        return conn

    def _target(self, path_and_query: str) -> str:
        if self._scheme == "http" and self._proxy is not None:
            return f"http://{self._host}:{self._port}{self._prefix}{path_and_query}"
        return f"{self._prefix}{path_and_query}"

    def _drop(self) -> None:
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            with self._lock:
                self._conns.discard(conn)
            conn.close()

    def _send(self, path_and_query: str, headers: dict[str, str]) -> tuple[int, Any, bytes]:
        """One GET on this thread's connection: (status, headers, body). A connection that the server or a proxy
        closed while it sat idle is replaced and the request sent once more straight away. That retry does not
        count against max_retries: the request never got an answer on the dead connection."""
        if self._scheme == "http" and self._proxy is not None:
            headers = {**headers, **self._proxy_auth()}
        for fresh in (False, True):
            conn = getattr(self._local, "conn", None)
            if conn is None or conn not in self._conns:  # first use on this thread, or close() was called
                conn = self._local.conn = self._new_connection()
                self._local.used = 0
            reused = self._local.used > 0
            try:
                conn.request("GET", self._target(path_and_query), headers=headers)
                resp = conn.getresponse()
                body = resp.read()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                    http.client.RemoteDisconnected, http.client.BadStatusLine) as e:
                self._drop()
                if reused and not fresh:
                    continue
                raise ConnectionError(str(e) or type(e).__name__) from None
            except (OSError, http.client.HTTPException):
                self._drop()  # state unknown (timeout, DNS, TLS, truncated body): never reuse it
                raise
            self._local.used += 1
            if resp.will_close:  # the server said Connection: close
                self._drop()
            return resp.status, resp.headers, body
        raise AssertionError("unreachable")

    def _get(self, path: str, params: dict[str, Any] | None = None, auth: bool = True) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        path_and_query = path + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if auth:
            headers["X-API-Key"] = self.api_key
        attempt = 0
        while True:
            try:
                status, resp_headers, body = self._send(path_and_query, headers)
            except (OSError, http.client.HTTPException) as e:  # includes TimeoutError and ConnectionError
                if attempt >= self.max_retries:
                    raise TickFeedError(None, "connection_error", str(e) or type(e).__name__) from None
                delay = self._backoff(attempt)
            else:
                if 200 <= status < 300:
                    return json.loads(body)
                err = self._error_from(status, resp_headers, body)
                if path == "/health" and status == 503:
                    return json.loads(err.raw) if getattr(err, "raw", None) else {"status": "down"}
                retryable = isinstance(err, (RateLimitedError, UnavailableError))
                if not retryable or attempt >= self.max_retries:
                    raise err from None
                delay = err.retry_after if isinstance(err, RateLimitedError) else self._backoff(attempt, err)
            attempt += 1
            time.sleep(delay)

    @staticmethod
    def _backoff(attempt: int, err: TickFeedError | None = None) -> float:
        hinted = getattr(err, "retry_after", None)
        return hinted if hinted else min(30.0, 2 ** attempt) + random.uniform(0, 0.5)

    @staticmethod
    def _error_from(status: int, headers: Any, body: bytes) -> TickFeedError:
        raw = body.decode("utf-8", "replace")
        try:
            data = json.loads(raw)
            code, message = data["error"]["code"], data["error"]["message"]
        except (ValueError, KeyError, TypeError):
            code, message = "http_error", raw[:200] or http.client.responses.get(status, "")
        retry_after = headers.get("Retry-After") if headers else None
        location = headers.get("Location") if headers else None
        if 300 <= status < 400 and location:  # redirects are not followed: an API key must never be re-sent elsewhere
            code, message = "redirect", (f"The server redirected to {location}. Set base_url to that address "
                                         "(https). If base_url was http://, rotate the key: it was sent unencrypted.")
        if status == 429:
            err: TickFeedError = RateLimitedError(status, code, message, float(retry_after or 5))
        elif status == 503:
            err = UnavailableError(status, code, message)
            if retry_after:
                err.retry_after = float(retry_after)  # type: ignore[attr-defined]
        else:
            err = TickFeedError(status, code, message)
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
        """One page of OHLC candles, oldest first. The last bar may have complete=False.

        timeframe is one of CANDLE_TIMEFRAMES. Seconds timeframes (S1, S5, S15, S30) are built from tick history
        (about the last six months) and are live only: source="stored" raises ValueError for them."""
        if timeframe not in CANDLE_TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {CANDLE_TIMEFRAMES}")
        if timeframe in SECONDS_TIMEFRAMES and source == "stored":
            raise ValueError(f"{timeframe} candles are built from tick history and are not stored; use source='live'")
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
        """Missing intervals in stored history, each marked expected (market closed) or not.
        Stored timeframes only (TIMEFRAMES): seconds candles are built on request and have no gap report."""
        if timeframe in SECONDS_TIMEFRAMES:
            raise ValueError(f"{timeframe} has no gap report (seconds candles are not stored); "
                             f"use one of {TIMEFRAMES}")
        return self._get(f"/v1/candles/{urllib.parse.quote(symbol)}/gaps", {
            "timeframe": timeframe, "start_time": _iso(start_time), "end_time": _iso(end_time)})

    def ticks(self, symbol: str, limit: int = 1000, start_time: datetime | str | None = None,
              end_time: datetime | str | None = None) -> dict:
        """One page of raw ticks (every bid/ask change), oldest first: {'ticks': [{'time', 'bid', 'ask'}, ...]}.

        With start_time: the first ``limit`` ticks from start_time (up to end_time or now); if more exist,
        'truncated' is True and 'next_start_time' starts the next page. Without: the latest ``limit`` ticks up to
        end_time (or now). limit is 1-10,000 (default 1,000). Times are UTC with milliseconds, and several ticks
        can share one millisecond. History covers about the last six months (rolling; see 'notes').
        Cost: one unit per started block of 1,000 ticks returned."""
        return self._get(f"/v1/ticks/{urllib.parse.quote(symbol)}", {
            "limit": limit, "start_time": _iso(start_time), "end_time": _iso(end_time)})

    def iter_ticks(self, symbol: str, start_time: datetime | str, end_time: datetime | str | None = None,
                   page_size: int = 10000) -> Iterator[dict]:
        """Yield every tick in [start_time, end_time], following the server's next_start_time. Pages end on a
        whole millisecond, so ticks that share a timestamp are never split, repeated or skipped."""
        cursor: datetime | str | None = start_time
        while cursor is not None:
            page = self.ticks(symbol, page_size, cursor, end_time)
            yield from page["ticks"]
            cursor = page["next_start_time"] if page["truncated"] else None

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

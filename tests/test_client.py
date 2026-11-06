"""Client tests against a local stub server (no network, no API key needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from tickfeed import (CANDLE_TIMEFRAMES, SECONDS_TIMEFRAMES, TIMEFRAMES, RateLimitedError, TickFeed,
                      TickFeedError, UnavailableError)

CALLS = []
SCRIPT = []  # queued (status, body, headers) responses; default is a price


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        CALLS.append((url.path, parse_qs(url.query), {k.lower(): v for k, v in self.headers.items()}))
        status, body, headers = SCRIPT.pop(0) if SCRIPT else (200, {"symbol": "XAUUSD", "bid": 1.0}, {})
        if callable(body):  # a response computed from the query (see the tick paging test)
            body = body(parse_qs(url.query))
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def reset():
    CALLS.clear()
    SCRIPT.clear()


def test_key_from_env_and_never_in_repr(monkeypatch, base):
    monkeypatch.setenv("TICKFEED_API_KEY", "mdp_secret")
    tf = TickFeed(base_url=base)
    assert "mdp_secret" not in repr(tf)
    tf.price("XAUUSD")
    path, _, headers = CALLS[0]
    assert path == "/v1/price/XAUUSD" and headers["x-api-key"] == "mdp_secret"
    assert headers["user-agent"].startswith("tickfeed-python/")


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TICKFEED_API_KEY", raising=False)
    with pytest.raises(ValueError):
        TickFeed()


def test_batch_prices(base):
    SCRIPT.append((200, {"prices": []}, {}))
    TickFeed("k", base_url=base).prices(["EURUSD", " GBPUSD ", ""])
    path, query, _ = CALLS[0]
    assert path == "/v1/prices" and query["symbols"] == ["EURUSD,GBPUSD"]
    with pytest.raises(ValueError):
        TickFeed("k", base_url=base).prices([])


def test_candles_params_and_pagination(base):
    SCRIPT.append((200, {"candles": [{"time": "a"}], "truncated": True, "next_start_time": "2026-01-01T00:05:00Z"}, {}))
    SCRIPT.append((200, {"candles": [{"time": "b"}], "truncated": False, "next_start_time": None}, {}))
    bars = list(TickFeed("k", base_url=base).iter_candles("EURUSD", "M5", "2026-01-01T00:00:00Z"))
    assert [b["time"] for b in bars] == ["a", "b"]
    assert CALLS[1][1]["start_time"] == ["2026-01-01T00:05:00Z"] and CALLS[0][1]["timeframe"] == ["M5"]
    with pytest.raises(ValueError):
        TickFeed("k", base_url=base).candles("EURUSD", "M2")


def test_errors_are_typed(base):
    SCRIPT.append((404, {"error": {"code": "unsupported_symbol", "message": "nope"}}, {}))
    with pytest.raises(TickFeedError) as err:
        TickFeed("k", base_url=base, max_retries=0).price("BTCUSD")
    assert err.value.status == 404 and err.value.code == "unsupported_symbol"


def test_retries_429_and_503(base, monkeypatch):
    monkeypatch.setattr("tickfeed.time.sleep", lambda s: None)
    SCRIPT.append((429, {"error": {"code": "rate_limited", "message": "slow down"}}, {"Retry-After": "1"}))
    SCRIPT.append((503, {"error": {"code": "busy", "message": "busy"}}, {"Retry-After": "5"}))
    assert TickFeed("k", base_url=base).price("XAUUSD")["bid"] == 1.0
    assert len(CALLS) == 3

    SCRIPT.extend([(429, {"error": {"code": "rate_limited", "message": "x"}}, {"Retry-After": "1"})] * 2)
    with pytest.raises(RateLimitedError):
        TickFeed("k", base_url=base, max_retries=1).price("XAUUSD")
    SCRIPT.extend([(503, {"error": {"code": "upstream_unavailable", "message": "x"}}, {})] * 2)
    with pytest.raises(UnavailableError):
        TickFeed("k", base_url=base, max_retries=1).price("XAUUSD")


def test_health_returns_body_when_down(base):
    SCRIPT.append((503, {"status": "down", "reasons": ["feed"]}, {}))
    assert TickFeed("k", base_url=base).health()["status"] == "down"
    assert "x-api-key" not in CALLS[0][2]


# ---- 0.2.0: seconds candles and raw ticks ---------------------------------------------------------------------
CANDLES = {"symbol": "XAUUSD", "timeframe": "S1", "source": "live", "count": 1, "truncated": False,
           "next_start_time": None, "notes": [],
           "candles": [{"time": "2026-11-06T12:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                        "tick_volume": 3, "spread_points": 20, "complete": True}]}


def test_timeframe_constants():
    assert CANDLE_TIMEFRAMES == ("S1", "S5", "S15", "S30", "M1", "M5", "M15", "M30", "H1", "H4", "D1")
    assert TIMEFRAMES == ("M1", "M5", "M15", "M30", "H1", "H4", "D1")  # unchanged: stored history and gaps
    assert SECONDS_TIMEFRAMES == ("S1", "S5", "S15", "S30")


@pytest.mark.parametrize("timeframe", ["S1", "S5", "S15", "S30", "M5", "D1"])
def test_candles_accepts_every_documented_timeframe(base, timeframe):
    SCRIPT.append((200, CANDLES, {}))
    TickFeed("k", base_url=base).candles("XAUUSD", timeframe, limit=60, start_time="2026-11-06T12:00:00Z")
    path, query, _ = CALLS[0]
    assert path == "/v1/candles/XAUUSD"
    assert query == {"timeframe": [timeframe], "limit": ["60"], "start_time": ["2026-11-06T12:00:00Z"],
                     "source": ["live"]}


def test_candles_default_timeframe_unchanged(base):
    SCRIPT.append((200, CANDLES, {}))
    TickFeed("k", base_url=base).candles("EURUSD")
    assert CALLS[0][1]["timeframe"] == ["M5"] and CALLS[0][1]["limit"] == ["100"]


@pytest.mark.parametrize("timeframe", ["M2", "S2", "s1", "1m", "W1", ""])
def test_candles_rejects_unsupported_timeframes_before_any_request(base, timeframe):
    with pytest.raises(ValueError):
        TickFeed("k", base_url=base).candles("XAUUSD", timeframe)
    assert CALLS == []


def test_seconds_restrictions_stay_specific(base):
    tf = TickFeed("k", base_url=base)
    with pytest.raises(ValueError, match="not stored"):
        tf.candles("XAUUSD", "S5", source="stored")
    with pytest.raises(ValueError, match="no gap report"):
        tf.gaps("XAUUSD", "S1")
    assert CALLS == []
    SCRIPT.extend([(200, CANDLES, {}), (200, {"gaps": []}, {})])
    tf.candles("XAUUSD", "M1", source="stored")  # stored minute bars still allowed
    tf.gaps("XAUUSD", "M1")
    assert CALLS[0][1]["source"] == ["stored"] and CALLS[1][0] == "/v1/candles/XAUUSD/gaps"


def test_iter_candles_follows_pagination_for_seconds(base):
    SCRIPT.append((200, {"candles": [{"time": "2026-11-06T12:00:00Z"}], "truncated": True,
                         "next_start_time": "2026-11-06T12:00:01Z"}, {}))
    SCRIPT.append((200, {"candles": [{"time": "2026-11-06T12:00:01Z"}], "truncated": False,
                         "next_start_time": None}, {}))
    bars = list(TickFeed("k", base_url=base).iter_candles("XAUUSD", "S1", "2026-11-06T12:00:00Z", page_size=1))
    assert [b["time"] for b in bars] == ["2026-11-06T12:00:00Z", "2026-11-06T12:00:01Z"]
    assert [c[1]["timeframe"] for c in CALLS] == [["S1"], ["S1"]]
    assert CALLS[1][1]["start_time"] == ["2026-11-06T12:00:01Z"]
    with pytest.raises(ValueError):
        next(TickFeed("k", base_url=base).iter_candles("XAUUSD", "S1", "2026-11-06T12:00:00Z", source="stored"))


def test_candles_df_with_seconds(base):
    pytest.importorskip("pandas")
    forming = dict(CANDLES["candles"][0], time="2026-11-06T12:00:01Z", complete=False)
    SCRIPT.append((200, dict(CANDLES, candles=CANDLES["candles"] + [forming]), {}))
    df = TickFeed("k", base_url=base).candles_df("XAUUSD", "S1", limit=2)
    assert list(df.index.astype(str)) == ["2026-11-06 12:00:00+00:00"] and CALLS[0][1]["timeframe"] == ["S1"]


TICKS = {"symbol": "XAUUSD", "count": 2, "truncated": False, "next_start_time": None,
         "notes": ["Tick history for XAUUSD is available from 2026-05-06 00:00:00 UTC (about the last six months, rolling)."],
         "ticks": [{"time": "2026-11-06T12:00:00.123Z", "bid": 4041.99, "ask": 4042.21},
                   {"time": "2026-11-06T12:00:00.123Z", "bid": 4041.98, "ask": 4042.21}]}


def test_ticks_forwards_parameters_and_returns_body(base):
    from datetime import datetime, timedelta, timezone
    SCRIPT.append((200, TICKS, {}))
    start = datetime(2026, 11, 6, 13, 0, tzinfo=timezone(timedelta(hours=1)))  # converted to UTC
    out = TickFeed("k", base_url=base).ticks("XAUUSD", limit=500, start_time=start,
                                             end_time=datetime(2026, 11, 6, 12, 5))  # naive = UTC
    path, query, headers = CALLS[0]
    assert path == "/v1/ticks/XAUUSD" and headers["x-api-key"] == "k"
    assert query == {"limit": ["500"], "start_time": ["2026-11-06T12:00:00Z"], "end_time": ["2026-11-06T12:05:00Z"]}
    assert out == TICKS and out["ticks"][0] == {"time": "2026-11-06T12:00:00.123Z", "bid": 4041.99, "ask": 4042.21}


def test_ticks_defaults_and_errors(base):
    SCRIPT.append((200, TICKS, {}))
    TickFeed("k", base_url=base).ticks("XAUUSD")
    assert CALLS[0][1] == {"limit": ["1000"]}
    SCRIPT.append((422, {"error": {"code": "invalid_parameters", "message": "limit must be between 1 and 10000"}}, {}))
    with pytest.raises(TickFeedError) as err:
        TickFeed("k", base_url=base, max_retries=0).ticks("XAUUSD", limit=20000)
    assert err.value.status == 422 and err.value.code == "invalid_parameters"


def _tick_server(data):
    """Pages like GET /v1/ticks: the first `limit` ticks at or after start_time, cut back to a whole millisecond,
    next_start_time = the first tick of the next page."""
    def page(query):
        start, limit = query["start_time"][0], int(query["limit"][0])
        rest = [t for t in data if t["time"] >= start]
        if len(rest) <= limit:
            return {"symbol": "XAUUSD", "count": len(rest), "truncated": False, "next_start_time": None, "ticks": rest}
        cut = limit
        while cut > 0 and rest[cut - 1]["time"] == rest[limit]["time"]:
            cut -= 1
        return {"symbol": "XAUUSD", "count": cut, "truncated": True, "next_start_time": rest[limit]["time"],
                "ticks": rest[:cut]}
    return page


def test_iter_ticks_keeps_ticks_that_share_a_millisecond(base):
    ms = ["000", "000", "001", "001", "001", "002", "005", "005", "009"]
    data = [{"time": f"2026-11-06T12:00:00.{m}Z", "bid": 1.0 + i / 100, "ask": 1.1 + i / 100}
            for i, m in enumerate(ms)]
    SCRIPT.extend([(200, _tick_server(data), {})] * 6)
    got = list(TickFeed("k", base_url=base).iter_ticks("XAUUSD", "2026-11-06T12:00:00.000Z", page_size=3))
    assert got == data  # nothing repeated, nothing skipped
    starts = [c[1]["start_time"][0] for c in CALLS]
    # The cursor is exactly the server's next_start_time: pages break between milliseconds, never inside one,
    # and the client never invents a cursor such as "last tick + 1 ms".
    assert starts == ["2026-11-06T12:00:00.000Z", "2026-11-06T12:00:00.001Z", "2026-11-06T12:00:00.002Z",
                      "2026-11-06T12:00:00.009Z"]

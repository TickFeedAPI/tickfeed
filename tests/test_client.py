"""Client tests against a local stub server (no network, no API key needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from tickfeed import RateLimitedError, TickFeed, TickFeedError, UnavailableError

CALLS = []
SCRIPT = []  # queued (status, body, headers) responses; default is a price


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        CALLS.append((url.path, parse_qs(url.query), {k.lower(): v for k, v in self.headers.items()}))
        status, body, headers = SCRIPT.pop(0) if SCRIPT else (200, {"symbol": "XAUUSD", "bid": 1.0}, {})
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

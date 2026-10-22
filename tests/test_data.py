import logging

import pandas as pd
import pytest

from signalbot.data import fetch_candles, is_stale


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def test_yahoo_parsing_drops_nulls_and_open_candle(monkeypatch):
    now = pd.Timestamp("2024-01-01T12:00:30Z")
    stamps = [
        int(pd.Timestamp("2024-01-01T11:59:00Z").timestamp()),
        int(pd.Timestamp("2024-01-01T11:58:00Z").timestamp()),
        int(pd.Timestamp("2024-01-01T12:00:00Z").timestamp()),
    ]
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": stamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [None, 1.1, 1.2],
                                "high": [None, 1.2, 1.3],
                                "low": [None, 1.0, 1.1],
                                "close": [None, 1.15, 1.25],
                            }
                        ]
                    },
                }
            ]
        }
    }
    requests_seen = {}

    def fake_get(url, **kwargs):
        requests_seen.update(url=url, **kwargs)
        return FakeResponse(payload)

    monkeypatch.setattr("signalbot.data.requests.get", fake_get)
    candles = fetch_candles("EURUSD", "1m", limit=10, now=now)

    assert len(candles) == 1
    assert candles.iloc[0]["close"] == pytest.approx(1.15)
    assert candles.iloc[0]["time"] == pd.Timestamp("2024-01-01T11:58:00Z")
    assert requests_seen["url"].endswith("/EURUSD=X")
    assert requests_seen["params"] == {"interval": "1m", "range": "1d"}
    assert requests_seen["headers"]["User-Agent"] == "Mozilla/5.0"


def test_yahoo_one_minute_history_clamps_to_seven_days(monkeypatch, caplog):
    seen = {}
    body = {"chart": {"result": [], "error": None}}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse(body)

    monkeypatch.setattr("signalbot.data.requests.get", fake_get)
    with caplog.at_level(logging.WARNING, logger="signalbot.data"):
        fetch_candles(
            "GBPUSD",
            "1m",
            days=30,
            now=pd.Timestamp("2024-01-10T12:00:00Z"),
        )

    assert seen["params"]["range"] == "7d"
    assert "limited to 7 days" in caplog.text


def test_binance_parsing_and_pair_routing(monkeypatch):
    now = pd.Timestamp("2024-01-01T12:00:30Z")
    start_times = [
        int(pd.Timestamp("2024-01-01T11:59:00Z").timestamp() * 1000),
        int(pd.Timestamp("2024-01-01T12:00:00Z").timestamp() * 1000),
    ]
    rows = [
        [start_times[0], "42000", "42010", "41990", "42005", "1", 0, 0, 0, 0, 0, 0],
        [start_times[1], "42005", "42020", "42000", "42015", "1", 0, 0, 0, 0, 0, 0],
    ]
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse(rows)

    monkeypatch.setattr("signalbot.data.requests.get", fake_get)
    candles = fetch_candles("BTCUSDT", "1m", limit=10, now=now)

    assert len(candles) == 1
    assert candles.iloc[0]["close"] == pytest.approx(42005)
    assert seen["url"] == "https://data-api.binance.vision/api/v3/klines"
    assert seen["params"] == {"symbol": "BTCUSDT", "interval": "1m", "limit": 10}


def test_forex_and_unknown_pair_routing(monkeypatch):
    seen = []

    def fake_get(url, **kwargs):
        seen.append(url)
        return FakeResponse({"chart": {"result": [], "error": None}})

    monkeypatch.setattr("signalbot.data.requests.get", fake_get)
    fetch_candles(
        "USDJPY",
        "5m",
        limit=20,
        now=pd.Timestamp("2024-01-01T12:00:00Z"),
    )
    assert seen == [
        "https://query1.finance.yahoo.com/v8/finance/chart/USDJPY=X"
    ]
    with pytest.raises(ValueError, match="Unsupported pair format"):
        fetch_candles("EURUSD-OTC", "1m", limit=10)


def test_is_stale_uses_three_intervals_after_last_close():
    candles = pd.DataFrame(
        {"time": [pd.Timestamp("2024-01-01T12:00:00Z")]}
    )

    assert not is_stale(candles, "1m", now=pd.Timestamp("2024-01-01T12:03:00Z"))
    assert is_stale(candles, "1m", now=pd.Timestamp("2024-01-01T12:04:01Z"))
    assert is_stale(pd.DataFrame(), "1m")

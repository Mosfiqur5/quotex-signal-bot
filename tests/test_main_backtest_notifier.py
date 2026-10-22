import csv
import logging

import pandas as pd
import pytest

from signalbot.backtest import data_quality, main as backtest_main, run_backtest
from signalbot.main import (
    cooldown_active,
    load_state,
    resolve_pending_signals,
    resolve_result,
    run_iteration,
)
from signalbot.notifier import Notifier
from tests.helpers import make_config


@pytest.mark.parametrize(
    ("direction", "entry", "exit_price", "expected"),
    [
        ("UP", 1.1, 1.2, "WIN"),
        ("UP", 1.1, 1.0, "LOSS"),
        ("DOWN", 1.1, 1.0, "WIN"),
        ("DOWN", 1.1, 1.2, "LOSS"),
        ("UP", 1.1, 1.1, "DRAW"),
    ],
)
def test_result_resolution(direction, entry, exit_price, expected):
    assert resolve_result(direction, entry, exit_price) == expected


def test_cooldown_blocks_only_within_configured_candles():
    cfg = make_config(cooldown_candles=5)
    last = pd.Timestamp("2024-01-01T12:00:00Z")

    assert cooldown_active(last, last + pd.Timedelta(minutes=4), cfg)
    assert not cooldown_active(last, last + pd.Timedelta(minutes=5), cfg)
    assert not cooldown_active(None, last, cfg)


def test_pending_signal_resolution_updates_totals_and_csv(tmp_path):
    class Collector:
        def __init__(self):
            self.messages = []

        def send(self, text):
            self.messages.append(text)

    entry_time = pd.Timestamp("2024-01-01T12:00:00Z")
    state = {
        "pending_signals": [
            {
                "pair": "EURUSD",
                "direction": "UP",
                "entry_price": 1.1,
                "entry_time": entry_time.isoformat(),
                "expiry_time": (entry_time + pd.Timedelta(minutes=1)).isoformat(),
            }
        ],
        "wins": 0,
        "losses": 0,
        "draws": 0,
    }
    candles = pd.DataFrame(
        {
            "time": [entry_time],
            "close": [1.2],
        }
    )
    collector = Collector()
    csv_path = tmp_path / "signals.csv"

    resolve_pending_signals(
        "EURUSD", candles, state, collector, csv_path, interval="1m"
    )

    assert state["pending_signals"] == []
    assert state["wins"] == 1
    assert len(collector.messages) == 2
    with csv_path.open(encoding="utf-8", newline="") as results_file:
        records = list(csv.DictReader(results_file))
    assert records[0]["result"] == "WIN"
    assert records[0]["exit_price"] == "1.2"


def test_iteration_persists_signal_and_caller_applies_cooldown(
    monkeypatch, tmp_path
):
    class Collector:
        def __init__(self):
            self.messages = []

        def send(self, text):
            self.messages.append(text)

    cfg = make_config(pairs=("EURUSD",))
    candle_time = pd.Timestamp("2024-01-01T08:14:00Z")
    candles = pd.DataFrame(
        {
            "time": [candle_time],
            "close": [1.1241],
            "rsi": [27.3],
        }
    )
    monkeypatch.setattr("signalbot.main.fetch_candles", lambda *args, **kwargs: candles)
    monkeypatch.setattr("signalbot.main.is_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "signalbot.main.add_indicators", lambda frame, config: frame
    )
    monkeypatch.setattr("signalbot.main.signal", lambda frame: "UP")
    collector = Collector()
    state = {
        "pending_signals": [],
        "last_signal_candles": {},
        "wins": 0,
        "losses": 0,
        "draws": 0,
    }
    state_path = tmp_path / "state.json"

    run_iteration(cfg, collector, state, state_path, tmp_path / "signals.csv")
    run_iteration(cfg, collector, state, state_path, tmp_path / "signals.csv")

    assert len(collector.messages) == 1
    assert "(CALL)" in collector.messages[0]
    assert "next candle" in collector.messages[0]
    assert len(state["pending_signals"]) == 1
    assert state["pending_signals"][0]["entry_price"] == pytest.approx(1.1241)
    assert load_state(state_path) == state


def test_backtest_stats_breakeven_and_dollar_profit(monkeypatch):
    cfg = make_config(cooldown_candles=5, payout_pct=80)
    times = pd.date_range("2024-01-01T00:00:00Z", periods=9, freq="min")
    candles = pd.DataFrame(
        {
            "time": times,
            "close": [10, 10, 11, 10, 10, 10, 10, 10, 11],
        }
    )
    actions = {1: "UP", 7: "DOWN"}
    monkeypatch.setattr(
        "signalbot.backtest.signal",
        lambda frame: actions.get(len(frame) - 1),
    )

    stats, records = run_backtest(candles, cfg, "EURUSD")

    assert stats["signals"] == 2
    assert (stats["wins"], stats["losses"], stats["draws"]) == (1, 1, 0)
    assert stats["win_rate_pct"] == pytest.approx(50)
    assert stats["breakeven_win_rate_pct"] == pytest.approx(55.5555556)
    assert stats["net_profit_usd"] == pytest.approx(-0.2)
    assert [record["result"] for record in records] == ["WIN", "LOSS"]


def test_data_quality_percentages():
    candles = pd.DataFrame(
        {
            "high": [1.0, 2.0, 3.0, 4.0],
            "low": [1.0, 1.0, 3.0, 3.0],
            "close": [10.0, 10.0, 11.0, 11.0],
        }
    )

    quality = data_quality(candles)

    assert quality["flat_candle_pct"] == pytest.approx(50)
    assert quality["unchanged_close_pct"] == pytest.approx(200 / 3)


def test_backtest_main_warns_for_snapshot_quality(
    monkeypatch, capsys, tmp_path
):
    cfg = make_config()
    candles = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="min"),
            "high": [1.0, 1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0, 1.0],
        }
    )
    monkeypatch.setattr("signalbot.backtest.load_config", lambda: cfg)
    monkeypatch.setattr(
        "signalbot.backtest.fetch_candles", lambda *args, **kwargs: candles
    )
    monkeypatch.chdir(tmp_path)

    assert backtest_main(["--pair", "EURUSD", "--days", "1"]) == 0

    output = capsys.readouterr().out
    assert "flat candles 100.00%" in output
    assert "unchanged closes 100.00%" in output
    assert (
        "WARNING: low-quality price data (snapshot prices) — "
        "this backtest result is NOT reliable."
    ) in output


def test_notifier_posts_telegram_payload_and_prints(monkeypatch, capsys):
    cfg = make_config(telegram_bot_token="fake-token", telegram_chat_id="123")
    requests_seen = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        requests_seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("signalbot.notifier.requests.post", fake_post)
    notifier = Notifier(cfg)

    assert notifier.send("Test signal")
    assert requests_seen["url"] == (
        "https://api.telegram.org/botfake-token/sendMessage"
    )
    assert requests_seen["json"] == {"chat_id": "123", "text": "Test signal"}
    assert requests_seen["timeout"] == 10
    assert capsys.readouterr().out == "Test signal\n"


def test_notifier_is_console_only_without_token(monkeypatch, capsys, caplog):
    cfg = make_config()

    def no_request(*args, **kwargs):
        pytest.fail("Console-only mode must not call Telegram.")

    monkeypatch.setattr("signalbot.notifier.requests.post", no_request)
    with caplog.at_level(logging.INFO, logger="signalbot.notifier"):
        notifier = Notifier(cfg)
        assert not notifier.send("Signal one")
        assert not notifier.send("Signal two")

    assert capsys.readouterr().out == "Signal one\nSignal two\n"
    assert caplog.text.count("console-only mode") == 1

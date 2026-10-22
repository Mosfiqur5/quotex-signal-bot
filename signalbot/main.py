import argparse
import csv
from datetime import timezone
import json
import logging
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import pandas as pd

from signalbot.config import ConfigError, load_config
from signalbot.data import fetch_candles, interval_delta, is_stale
from signalbot.notifier import Notifier
from signalbot.strategy import add_indicators, signal

STATE_PATH = Path("state.json")
SIGNALS_PATH = Path("signals.csv")
SIGNAL_COLUMNS = [
    "pair",
    "direction",
    "entry_time",
    "entry_price",
    "exit_price",
    "result",
]
logger = logging.getLogger(__name__)


def _iso_utc(value) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def load_state(path=STATE_PATH):
    defaults = {
        "pending_signals": [],
        "last_signal_candles": {},
        "wins": 0,
        "losses": 0,
        "draws": 0,
    }
    path = Path(path)
    if not path.exists():
        return defaults
    with path.open(encoding="utf-8") as state_file:
        defaults.update(json.load(state_file))
    return defaults


def save_state(state, path=STATE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2)
    temporary_path.replace(path)


def configure_logging():
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/signalbot.log", encoding="utf-8"),
        ],
    )


def cooldown_active(last_signal_time, current_candle_time, cfg) -> bool:
    if last_signal_time is None or cfg.cooldown_candles == 0:
        return False
    last = pd.Timestamp(last_signal_time)
    current = pd.Timestamp(current_candle_time)
    if last.tzinfo is None:
        last = last.tz_localize("UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    elapsed = (current - last).total_seconds()
    cooldown = cfg.cooldown_candles * cfg.interval_minutes * 60
    return elapsed < cooldown


def resolve_result(direction: str, entry_price: float, exit_price: float) -> str:
    if exit_price == entry_price:
        return "DRAW"
    moved_up = exit_price > entry_price
    if (direction == "UP" and moved_up) or (direction == "DOWN" and not moved_up):
        return "WIN"
    return "LOSS"


def _write_signal_result(record, path=SIGNALS_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=SIGNAL_COLUMNS)
        if needs_header:
            writer.writeheader()
        writer.writerow({column: record[column] for column in SIGNAL_COLUMNS})


def _notify_result(pending, exit_price, result, state, notifier, csv_path):
    record = {
        "pair": pending["pair"],
        "direction": pending["direction"],
        "entry_time": pending["entry_time"],
        "entry_price": float(pending["entry_price"]),
        "exit_price": float(exit_price),
        "result": result,
    }
    _write_signal_result(record, csv_path)
    counter_key = {"WIN": "wins", "LOSS": "losses", "DRAW": "draws"}[result]
    state[counter_key] += 1
    icon = {"WIN": "✅", "LOSS": "❌", "DRAW": "➖"}[result]
    notifier.send(
        f"{icon} {result} — {pending['pair']} {pending['direction']}\n"
        f"Entry: {float(pending['entry_price']):.5f} | Exit: {float(exit_price):.5f}"
    )
    decisive = state["wins"] + state["losses"]
    win_rate = state["wins"] / decisive * 100 if decisive else 0.0
    notifier.send(
        f"Totals: {state['wins']} wins | {state['losses']} losses | "
        f"{state['draws']} draws | win rate {win_rate:.1f}%"
    )


def resolve_pending_signals(
    pair, candles, state, notifier, csv_path=SIGNALS_PATH, interval="1m"
):
    candle_close_times = candles["time"] + interval_delta(interval)
    remaining = []
    for pending in state["pending_signals"]:
        if pending["pair"] != pair:
            remaining.append(pending)
            continue
        expiry_time = pd.Timestamp(pending["expiry_time"])
        matching = candles.loc[candle_close_times == expiry_time]
        if matching.empty:
            remaining.append(pending)
            continue
        exit_price = float(matching["close"].iloc[-1])
        result = resolve_result(
            pending["direction"], float(pending["entry_price"]), exit_price
        )
        _notify_result(pending, exit_price, result, state, notifier, csv_path)
    state["pending_signals"] = remaining


def format_signal_message(pair, direction, entry_time, price, rsi, cfg) -> str:
    localized = pd.Timestamp(entry_time).to_pydatetime().astimezone(ZoneInfo(cfg.timezone))
    arrow, call_put = ("⬆️", "CALL") if direction == "UP" else ("⬇️", "PUT")
    expiry_label = f"{cfg.expiry_min} min"
    return (
        f"📊 {pair}\n"
        f"Direction: {direction} {arrow} ({call_put})\n"
        f"Expiry: {expiry_label}\n"
        f"Entry: {localized:%H:%M} ({cfg.timezone}) — next candle\n"
        f"Price: {float(price):.5f} | RSI: {float(rsi):.1f}\n"
        "⚠️ Signal only, no guarantee. Trade at your own risk."
    )


def run_iteration(cfg, notifier, state, state_path=STATE_PATH, csv_path=SIGNALS_PATH):
    for pair in cfg.pairs:
        try:
            candles = fetch_candles(
                pair,
                cfg.interval,
                limit=500,
                base_url=cfg.binance_data_url,
            )
            if candles.empty:
                logger.warning("%s: no candles returned; skipping.", pair)
                continue

            resolve_pending_signals(
                pair, candles, state, notifier, csv_path, cfg.interval
            )
            if is_stale(candles, cfg.interval):
                logger.info("%s: market data is stale; market may be closed.", pair)
                continue

            indicators = add_indicators(candles, cfg)
            direction = signal(indicators)
            if direction is None:
                logger.info("%s: no signal.", pair)
                continue

            current = indicators.iloc[-1]
            candle_time = pd.Timestamp(current["time"])
            last_time = state["last_signal_candles"].get(pair)
            if cooldown_active(last_time, candle_time, cfg):
                logger.info("%s: %s signal suppressed by cooldown.", pair, direction)
                continue

            entry_time = candle_time + interval_delta(cfg.interval)
            expiry_time = entry_time + pd.Timedelta(minutes=cfg.expiry_min)
            pending = {
                "pair": pair,
                "direction": direction,
                "entry_price": float(current["close"]),
                "entry_time": _iso_utc(entry_time),
                "expiry_time": _iso_utc(expiry_time),
            }
            state["pending_signals"].append(pending)
            state["last_signal_candles"][pair] = _iso_utc(candle_time)
            notifier.send(
                format_signal_message(
                    pair,
                    direction,
                    entry_time,
                    current["close"],
                    current["rsi"],
                    cfg,
                )
            )
        except Exception:
            logger.exception("Failed to process pair %s; continuing with other pairs.", pair)
    save_state(state, state_path)


def _seconds_until_next_close(interval):
    seconds = int(interval_delta(interval).total_seconds())
    return seconds - (time.time() % seconds) + 3


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send public-market trading signals.")
    parser.add_argument("--once", action="store_true", help="run one iteration and exit")
    args = parser.parse_args(argv)
    configure_logging()
    try:
        cfg = load_config()
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    notifier = Notifier(cfg)
    state = load_state()
    logger.info("Starting signal-only bot: %s, interval=%s.", ",".join(cfg.pairs), cfg.interval)
    while True:
        try:
            run_iteration(cfg, notifier, state)
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            return 0
        except Exception:
            logger.exception("Iteration failed; the bot will retry.")
        if args.once:
            return 0
        try:
            time.sleep(_seconds_until_next_close(cfg.interval))
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

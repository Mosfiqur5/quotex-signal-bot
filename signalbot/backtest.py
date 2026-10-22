import argparse

import pandas as pd

from signalbot.config import load_config
from signalbot.data import fetch_candles, interval_delta
from signalbot.main import resolve_result
from signalbot.strategy import add_indicators, signal

BACKTEST_COLUMNS = [
    "pair",
    "direction",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "result",
    "net_profit_usd",
]


def data_quality(candles: pd.DataFrame):
    if candles.empty:
        return {"flat_candle_pct": 0.0, "unchanged_close_pct": 0.0}

    flat_candle_pct = candles["high"].eq(candles["low"]).mean() * 100
    close_diffs = candles["close"].diff().iloc[1:]
    unchanged_close_pct = (
        close_diffs.eq(0).sum() / len(close_diffs) * 100 if len(close_diffs) else 0.0
    )
    return {
        "flat_candle_pct": float(flat_candle_pct),
        "unchanged_close_pct": float(unchanged_close_pct),
    }


def run_backtest(candles: pd.DataFrame, cfg, pair: str):
    if candles.empty:
        raise ValueError("Backtest data is empty.")
    indicators = add_indicators(candles.reset_index(drop=True), cfg)
    expiry_bars = cfg.expiry_min // cfg.interval_minutes
    records = []
    last_signal_index = None

    for index in range(len(indicators)):
        direction = signal(indicators.iloc[: index + 1])
        if direction is None:
            continue
        if (
            last_signal_index is not None
            and index - last_signal_index < cfg.cooldown_candles
        ):
            continue
        last_signal_index = index
        exit_index = index + expiry_bars
        if exit_index >= len(indicators):
            continue

        entry = indicators.iloc[index]
        exit_candle = indicators.iloc[exit_index]
        entry_price = float(entry["close"])
        exit_price = float(exit_candle["close"])
        result = resolve_result(direction, entry_price, exit_price)
        profit = (
            cfg.payout_pct / 100
            if result == "WIN"
            else -1.0 if result == "LOSS" else 0.0
        )
        records.append(
            {
                "pair": pair,
                "direction": direction,
                "entry_time": entry["time"],
                "entry_price": entry_price,
                "exit_time": exit_candle["time"] + interval_delta(cfg.interval),
                "exit_price": exit_price,
                "result": result,
                "net_profit_usd": profit,
            }
        )

    wins = sum(record["result"] == "WIN" for record in records)
    losses = sum(record["result"] == "LOSS" for record in records)
    draws = sum(record["result"] == "DRAW" for record in records)
    decisive = wins + losses
    return {
        "signals": len(records),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate_pct": wins / decisive * 100 if decisive else 0.0,
        "breakeven_win_rate_pct": 100 / (100 + cfg.payout_pct) * 100,
        "net_profit_usd": sum(record["net_profit_usd"] for record in records),
    }, records


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backtest public-market signals.")
    parser.add_argument("--pair")
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args(argv)
    if args.days <= 0:
        parser.error("--days must be positive")

    cfg = load_config()
    pair = (args.pair or cfg.pairs[0]).upper()
    candles = fetch_candles(
        pair, cfg.interval, days=args.days, base_url=cfg.binance_data_url
    )
    if candles.empty:
        raise RuntimeError(f"No candles available for {pair}.")
    stats, records = run_backtest(candles, cfg, pair)
    quality = data_quality(candles)
    print(
        f"Pair: {pair} | Interval: {cfg.interval} | "
        f"Candles: {len(candles)} | Expiry: {cfg.expiry_min} min"
    )
    print(
        f"Data quality: flat candles {quality['flat_candle_pct']:.2f}% | "
        f"unchanged closes {quality['unchanged_close_pct']:.2f}%"
    )
    if (
        quality["flat_candle_pct"] > 50
        or quality["unchanged_close_pct"] > 30
    ):
        print(
            "WARNING: low-quality price data (snapshot prices) — "
            "this backtest result is NOT reliable."
        )
    print(f"Signals: {stats['signals']}")
    print(
        f"Wins: {stats['wins']} | Losses: {stats['losses']} | Draws: {stats['draws']}"
    )
    print(f"Win rate (excluding draws): {stats['win_rate_pct']:.2f}%")
    print(
        f"Breakeven win rate at {cfg.payout_pct:g}% payout: "
        f"{stats['breakeven_win_rate_pct']:.2f}%"
    )
    print(f"Net profit ($1 per trade): ${stats['net_profit_usd']:.2f}")
    pd.DataFrame(records, columns=BACKTEST_COLUMNS).to_csv(
        "backtest_signals.csv", index=False
    )
    print("Saved signals to backtest_signals.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

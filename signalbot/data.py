from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Optional

import pandas as pd
import requests


logger = logging.getLogger(__name__)
DEFAULT_BINANCE_DATA_URL = "https://data-api.binance.vision"
CANDLE_COLUMNS = ["time", "open", "high", "low", "close"]
_BINANCE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


def interval_delta(interval: str) -> timedelta:
    if interval not in {"1m", "5m"}:
        raise ValueError("interval must be 1m or 5m")
    return timedelta(minutes=int(interval[:-1]))


def _utc_now(now=None) -> pd.Timestamp:
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if current.tzinfo is None:
        return current.tz_localize("UTC")
    return current.tz_convert("UTC")


def _route_pair(pair: str) -> str:
    if re.fullmatch(r"[A-Z0-9]+USDT", pair):
        return "binance"
    if re.fullmatch(r"[A-Z]{6}", pair):
        return "yahoo"
    raise ValueError(
        f"Unsupported pair format '{pair}'. Use a USDT pair or a six-letter forex pair."
    )


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CANDLE_COLUMNS)


def _finalize_candles(frame: pd.DataFrame, interval: str, now=None) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()
    result = frame[CANDLE_COLUMNS].copy()
    result["time"] = pd.to_datetime(result["time"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = (
        result.dropna(subset=CANDLE_COLUMNS)
        .drop_duplicates(subset=["time"])
        .sort_values("time")
        .reset_index(drop=True)
    )
    current = _utc_now(now)
    result = result[result["time"] + interval_delta(interval) <= current]
    return result.reset_index(drop=True)


def _fetch_binance_page(pair, interval, base_url, limit, start_ms=None, end_ms=None):
    params = {"symbol": pair, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    response = requests.get(
        f"{base_url.rstrip('/')}/api/v3/klines", params=params, timeout=15
    )
    response.raise_for_status()
    rows = response.json()
    if not rows:
        return _empty_frame()
    raw = pd.DataFrame(rows, columns=_BINANCE_COLUMNS)
    return pd.DataFrame(
        {
            "time": pd.to_datetime(raw["open_time"], unit="ms", utc=True),
            "open": pd.to_numeric(raw["open"], errors="coerce"),
            "high": pd.to_numeric(raw["high"], errors="coerce"),
            "low": pd.to_numeric(raw["low"], errors="coerce"),
            "close": pd.to_numeric(raw["close"], errors="coerce"),
        }
    )


def _fetch_binance(pair, interval, limit, days, base_url, now):
    if days is None:
        frame = _fetch_binance_page(pair, interval, base_url, limit)
        return _finalize_candles(frame, interval, now).tail(limit).reset_index(drop=True)

    current = _utc_now(now)
    end_ms = int(current.timestamp() * 1000)
    cursor_ms = int((current - timedelta(days=days)).timestamp() * 1000)
    interval_ms = int(interval_delta(interval).total_seconds() * 1000)
    pages = []
    while cursor_ms <= end_ms:
        page = _fetch_binance_page(
            pair, interval, base_url, 1000, start_ms=cursor_ms, end_ms=end_ms
        )
        if page.empty:
            break
        pages.append(page)
        next_cursor = int(page["time"].iloc[-1].timestamp() * 1000) + interval_ms
        if next_cursor <= cursor_ms:
            break
        cursor_ms = next_cursor
        if len(page) < 1000:
            break
    combined = pd.concat(pages, ignore_index=True) if pages else _empty_frame()
    return _finalize_candles(combined, interval, now)


def _fetch_yahoo(pair, interval, limit, days, now):
    range_days = days if days is not None else 1
    if interval == "1m" and range_days > 7:
        logger.warning("Yahoo 1m history is limited to 7 days; clamping the request.")
        range_days = 7
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}=X",
        params={"interval": interval, "range": f"{range_days}d"},
        headers=_YAHOO_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return _empty_frame()
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_list = result.get("indicators", {}).get("quote") or []
    quote = quote_list[0] if quote_list else {}
    values = {}
    for column in ["open", "high", "low", "close"]:
        series = list(quote.get(column) or [])
        values[column] = (series + [None] * len(timestamps))[: len(timestamps)]
    frame = pd.DataFrame(values)
    frame["time"] = pd.to_datetime(timestamps, unit="s", utc=True)
    frame = _finalize_candles(frame, interval, now)
    return frame.tail(limit).reset_index(drop=True) if days is None else frame


def fetch_candles(
    pair: str,
    interval: str,
    limit: Optional[int] = None,
    days: Optional[int] = None,
    *,
    base_url: str = DEFAULT_BINANCE_DATA_URL,
    now=None,
) -> pd.DataFrame:
    if interval not in {"1m", "5m"}:
        raise ValueError("interval must be 1m or 5m")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if days is not None and days <= 0:
        raise ValueError("days must be positive")
    if days is not None and limit is not None:
        raise ValueError("Specify either limit or days, not both.")
    if limit is None and days is None:
        limit = 500
    if limit is not None and limit > 1000:
        raise ValueError("limit cannot exceed 1000; use days for longer history.")

    normalized_pair = pair.strip().upper()
    route = _route_pair(normalized_pair)
    if route == "binance":
        return _fetch_binance(
            normalized_pair, interval, limit, days, base_url, now
        )
    return _fetch_yahoo(normalized_pair, interval, limit, days, now)


def is_stale(df: pd.DataFrame, interval: str, now=None) -> bool:
    if df.empty:
        return True
    last_time = pd.Timestamp(df["time"].iloc[-1])
    if last_time.tzinfo is None:
        last_time = last_time.tz_localize("UTC")
    else:
        last_time = last_time.tz_convert("UTC")
    age = _utc_now(now) - (last_time + interval_delta(interval))
    return age > interval_delta(interval) * 3

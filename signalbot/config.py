from dataclasses import dataclass
import os
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when configuration values are invalid."""


@dataclass(frozen=True)
class Config:
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    pairs: Tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "BTCUSDT")
    interval: str = "1m"
    expiry_min: int = 1
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_low: float = 30.0
    rsi_high: float = 70.0
    cooldown_candles: int = 5
    payout_pct: float = 80.0
    timezone: str = "Asia/Dhaka"
    binance_data_url: str = "https://data-api.binance.vision"

    @property
    def interval_minutes(self) -> int:
        return int(self.interval[:-1])


def load_config(env_file: Optional[str] = None) -> Config:
    load_dotenv(dotenv_path=env_file, override=False)
    try:
        interval = os.getenv("INTERVAL", "1m").strip().lower()
        cfg = Config(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip() or None,
            pairs=tuple(
                pair.strip().upper()
                for pair in os.getenv(
                    "PAIRS", "EURUSD,GBPUSD,USDJPY,BTCUSDT"
                ).split(",")
                if pair.strip()
            ),
            interval=interval,
            expiry_min=int(os.getenv("EXPIRY_MIN", "1")),
            bb_period=int(os.getenv("BB_PERIOD", "20")),
            bb_std=float(os.getenv("BB_STD", "2")),
            rsi_period=int(os.getenv("RSI_PERIOD", "14")),
            rsi_low=float(os.getenv("RSI_LOW", "30")),
            rsi_high=float(os.getenv("RSI_HIGH", "70")),
            cooldown_candles=int(os.getenv("COOLDOWN_CANDLES", "5")),
            payout_pct=float(os.getenv("PAYOUT_PCT", "80")),
            timezone=os.getenv("TIMEZONE", "Asia/Dhaka").strip(),
            binance_data_url=os.getenv(
                "BINANCE_DATA_URL", "https://data-api.binance.vision"
            ).rstrip("/"),
        )
    except ValueError as exc:
        raise ConfigError(f"Invalid numeric setting: {exc}") from exc

    if cfg.interval not in {"1m", "5m"}:
        raise ConfigError("INTERVAL must be 1m or 5m.")
    if cfg.expiry_min <= 0 or cfg.expiry_min % cfg.interval_minutes:
        raise ConfigError(
            "EXPIRY_MIN must be positive and a multiple of the interval minutes."
        )
    if cfg.bb_period < 2 or cfg.rsi_period < 1:
        raise ConfigError("BB_PERIOD must be at least 2 and RSI_PERIOD must be positive.")
    if cfg.bb_std <= 0:
        raise ConfigError("BB_STD must be positive.")
    if not (0 <= cfg.rsi_low < cfg.rsi_high <= 100):
        raise ConfigError("RSI_LOW and RSI_HIGH must satisfy 0 <= LOW < HIGH <= 100.")
    if cfg.cooldown_candles < 0:
        raise ConfigError("COOLDOWN_CANDLES cannot be negative.")
    if cfg.payout_pct <= 0:
        raise ConfigError("PAYOUT_PCT must be positive.")
    if not cfg.pairs:
        raise ConfigError("PAIRS must contain at least one pair.")
    try:
        ZoneInfo(cfg.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Unknown TIMEZONE: {cfg.timezone}") from exc
    return cfg

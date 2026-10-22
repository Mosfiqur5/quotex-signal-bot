from signalbot.config import Config


def make_config(**overrides):
    values = {
        "telegram_bot_token": None,
        "telegram_chat_id": None,
        "pairs": ("EURUSD", "GBPUSD", "USDJPY", "BTCUSDT"),
        "interval": "1m",
        "expiry_min": 1,
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_low": 30.0,
        "rsi_high": 70.0,
        "cooldown_candles": 5,
        "payout_pct": 80.0,
        "timezone": "Asia/Dhaka",
        "binance_data_url": "https://data-api.binance.vision",
    }
    values.update(overrides)
    return Config(**values)

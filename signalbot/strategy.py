import pandas as pd

from signalbot.config import Config


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    result = df.copy()
    close = pd.to_numeric(result["close"], errors="coerce")
    rolling = close.rolling(window=cfg.bb_period, min_periods=cfg.bb_period)
    result["bb_middle"] = rolling.mean()
    deviation = rolling.std(ddof=0)
    result["bb_upper"] = result["bb_middle"] + cfg.bb_std * deviation
    result["bb_lower"] = result["bb_middle"] - cfg.bb_std * deviation

    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(
        alpha=1 / cfg.rsi_period, min_periods=cfg.rsi_period, adjust=False
    ).mean()
    avg_loss = losses.ewm(
        alpha=1 / cfg.rsi_period, min_periods=cfg.rsi_period, adjust=False
    ).mean()
    relative_strength = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + relative_strength)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0)
    result["rsi"] = rsi
    result.attrs.update(df.attrs)
    result.attrs["rsi_low"] = cfg.rsi_low
    result.attrs["rsi_high"] = cfg.rsi_high
    return result


def signal(df: pd.DataFrame):
    if df.empty:
        return None
    current = df.iloc[-1]
    if any(pd.isna(current.get(column)) for column in ("bb_lower", "bb_upper", "rsi")):
        return None
    rsi_low = float(df.attrs.get("rsi_low", 30))
    rsi_high = float(df.attrs.get("rsi_high", 70))
    if current["close"] < current["bb_lower"] and current["rsi"] < rsi_low:
        return "UP"
    if current["close"] > current["bb_upper"] and current["rsi"] > rsi_high:
        return "DOWN"
    return None

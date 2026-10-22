import numpy as np
import pandas as pd
import pytest

from signalbot.strategy import add_indicators, signal
from tests.helpers import make_config


def test_bollinger_uses_population_standard_deviation_and_rsi_wilder_extremes():
    cfg = make_config(bb_period=20, bb_std=2, rsi_period=14)
    rising = pd.DataFrame({"close": range(1, 31)})
    falling = pd.DataFrame({"close": range(30, 0, -1)})

    rising_indicators = add_indicators(rising, cfg)
    falling_indicators = add_indicators(falling, cfg)
    expected_std = np.std(np.arange(1, 21), ddof=0)

    assert rising_indicators.iloc[19]["bb_middle"] == pytest.approx(10.5)
    assert rising_indicators.iloc[19]["bb_upper"] == pytest.approx(
        10.5 + 2 * expected_std
    )
    assert rising_indicators["rsi"].dropna().iloc[-1] == pytest.approx(100)
    assert falling_indicators["rsi"].dropna().iloc[-1] == pytest.approx(0)


@pytest.mark.parametrize(
    ("close", "lower", "upper", "rsi", "expected"),
    [
        (90, 95, 105, 25, "UP"),
        (110, 95, 105, 75, "DOWN"),
        (100, 95, 105, 50, None),
    ],
)
def test_signals_use_band_and_rsi_conditions(close, lower, upper, rsi, expected):
    frame = pd.DataFrame(
        {
            "close": [close],
            "bb_lower": [lower],
            "bb_upper": [upper],
            "rsi": [rsi],
        }
    )
    frame.attrs["rsi_low"] = 30
    frame.attrs["rsi_high"] = 70

    assert signal(frame) == expected

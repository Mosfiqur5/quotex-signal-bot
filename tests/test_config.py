import pytest

from signalbot.config import ConfigError, load_config


def test_expiry_must_be_a_positive_interval_multiple(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERVAL", "5m")
    monkeypatch.setenv("EXPIRY_MIN", "1")

    with pytest.raises(ConfigError, match="multiple of the interval minutes"):
        load_config(env_file=tmp_path / "missing.env")


def test_expiry_accepts_multiple_of_five_minutes(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERVAL", "5m")
    monkeypatch.setenv("EXPIRY_MIN", "10")

    cfg = load_config(env_file=tmp_path / "missing.env")

    assert cfg.expiry_min == 10
    assert cfg.interval_minutes == 5

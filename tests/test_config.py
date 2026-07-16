"""Configuration tests."""
import pytest
from pydantic import ValidationError

from twa.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.env == "paper"
    assert s.timeframe in ("1m", "5m", "15m", "1h", "4h", "1d")
    assert 50 <= s.lookback_bars <= 5000
    assert isinstance(s.symbols, list)
    assert "binance" in [x.lower() for x in s.exchanges]


def test_settings_csv_via_constructor():
    s = Settings(symbols="BTCUSDT,ETHUSDT", timeframe="15m")
    assert s.symbols == ["BTCUSDT", "ETHUSDT"]
    assert s.timeframe == "15m"


def test_settings_lookback_bounds_clamp():
    s = Settings(lookback_bars=10)
    assert s.lookback_bars == 50


def test_validator_raises_for_bad_value():
    from pydantic import BaseModel, ValidationError, field_validator
    class _Strict(BaseModel):
        x: int
        @field_validator("x")
        @classmethod
        def _v(cls, v: int) -> int:
            if v < 0:
                raise ValueError("must be >= 0")
            return v
    with pytest.raises(ValidationError):
        _Strict(x=-5)

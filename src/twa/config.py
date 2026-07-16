"""Typed configuration via Pydantic Settings. Reads from env / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level application settings.

    All fields can be supplied through environment variables (TWA_* prefix).
    Defaults permit running paper / tests out-of-the-box without any secrets.
    """

    model_config = SettingsConfigDict(
        env_prefix="TWA_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["paper", "live", "test"] = "paper"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    data_dir: Path = Field(default=Path("./data"))
    timezone: str = "UTC"

    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d"] = "1h"
    lookback_bars: int = 500

    exchanges: List[str] = Field(default_factory=lambda: ["binance", "bybit", "coinbase"])
    http_timeout_s: float = 15.0
    http_concurrency: int = 8
    ws_enabled: bool = True

    news_enabled: bool = True
    news_refresh_s: int = 180
    news_sources: List[str] = Field(default_factory=lambda: ["cryptopanic", "rss"])
    cryptopanic_public_key: Optional[str] = None

    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_min_interval_s: int = 120

    ml_enabled: bool = False
    ml_model_path: Path = Field(default=Path("./models/calibrator.joblib"))

    heartbeat_s: int = 30
    metrics_port: int = 9100

    risk_max_confidence: float = 0.95
    risk_news_dampen: float = 0.5
    risk_cooldown_s: int = 900

    @field_validator("symbols", "exchanges", "news_sources", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if v is None:
            return []
        return list(v)

    @field_validator("lookback_bars")
    @classmethod
    def _positive(cls, v: int) -> int:
        return max(50, min(5000, int(v)))


def get_settings() -> Settings:
    """Return a fresh Settings instance (process-cached via pydantic-settings)."""
    return Settings()


def reload_settings() -> Settings:
    """Alias for `get_settings()` retained for compatibility."""
    return Settings()

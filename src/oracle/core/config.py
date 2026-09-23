"""
Oracle Layer — Core Configuration
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # API Server
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    ws_host: str = Field(default="0.0.0.0", alias="WS_HOST")
    ws_port: int = Field(default=8001, alias="WS_PORT")
    rate_limit_rpm: int = Field(default=60, alias="RATE_LIMIT_RPM")

    # Database
    database_url: str = Field(default="postgresql://oracle:oracle@localhost:5432/oracle_layer", alias="DATABASE_URL")
    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")

    # Macro Data Sources
    eia_api_key: Optional[str] = Field(default=None, alias="EIA_API_KEY")
    fred_api_key: Optional[str] = Field(default=None, alias="FRED_API_KEY")
    noaa_api_token: Optional[str] = Field(default=None, alias="NOAA_API_TOKEN")
    polymarket_api_key: Optional[str] = Field(default=None, alias="POLYMARKET_API_KEY")

    # TypeSafe / Jev
    typesafe_api_key: Optional[str] = Field(default=None, alias="TYPE SAFE_API_KEY")
    typesafe_base_url: str = Field(default="https://api.typesafe.ai/v1", alias="TYPE SAFE_BASE_URL")
    jev_model: str = Field(default="jev", alias="JEV_MODEL")
    jev_timeout_ms: int = Field(default=5000, alias="JEV_TIMEOUT_MS")
    jev_max_retries: int = Field(default=3, alias="JEV_MAX_RETRIES")

    # Higgsfield
    higgsfield_api_key: Optional[str] = Field(default=None, alias="HIGGSFIELD_API_KEY")
    higgsfield_workspace_id: Optional[str] = Field(default=None, alias="HIGGSFIELD_WORKSPACE_ID")
    higgsfield_video_model: str = Field(default="seedance_2_5", alias="HIGGSFIELD_VIDEO_MODEL")
    higgsfield_video_duration: int = Field(default=30, alias="HIGGSFIELD_VIDEO_DURATION")
    higgsfield_video_aspect: str = Field(default="16:9", alias="HIGGSFIELD_VIDEO_ASPECT")
    higgsfield_video_resolution: str = Field(default="1080p", alias="HIGGSFIELD_VIDEO_RESOLUTION")

    # Telegram
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_chat_ids: List[int] = Field(default=[], alias="TELEGRAM_ALLOWED_CHAT_IDS")
    telegram_webhook_url: Optional[str] = Field(default=None, alias="TELEGRAM_WEBHOOK_URL")

    # Feature Flags
    enable_macro_pipeline: bool = Field(default=True, alias="ENABLE_MACRO_PIPELINE")
    enable_market_analysis: bool = Field(default=True, alias="ENABLE_MARKET_ANALYSIS")
    enable_jev_judgment: bool = Field(default=True, alias="ENABLE_JEV_JUDGMENT")
    enable_higgsfield_explainers: bool = Field(default=True, alias="ENABLE_HIGGSFIELD_EXPLAINERS")
    enable_telegram_bot: bool = Field(default=True, alias="ENABLE_TELEGRAM_BOT")
    enable_websocket_api: bool = Field(default=True, alias="ENABLE_WEBSOCKET_API")
    enable_web_dashboard: bool = Field(default=False, alias="ENABLE_WEB_DASHBOARD")

    # Calibration
    calibration_lookback_days: int = Field(default=180, alias="CALIBRATION_LOOKBACK_DAYS")
    calibration_min_samples: int = Field(default=100, alias="CALIBRATION_MIN_SAMPLES")
    calibration_method: str = Field(default="temperature_scaling", alias="CALIBRATION_METHOD")

    # Explainer
    explainer_trigger_move_pct: float = Field(default=3.0, alias="EXPLAINER_TRIGGER_MOVE_PCT")
    explainer_max_age_hours: int = Field(default=4, alias="EXPLAINER_MAX_AGE_HOURS")
    explainer_video_duration: int = Field(default=30, alias="EXPLAINER_VIDEO_DURATION")

    # Wallet Intelligence
    wallet_min_trades: int = Field(default=30, alias="WALLET_MIN_TRADES")
    wallet_max_trades_per_day: int = Field(default=50, alias="WALLET_MAX_TRADES_PER_DAY")
    wallet_min_clusters: int = Field(default=10, alias="WALLET_MIN_CLUSTERS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings
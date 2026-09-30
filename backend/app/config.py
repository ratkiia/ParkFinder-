"""Application settings, loaded from environment variables (prefix ``PARKFINDER_``) or ``.env``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARKFINDER_", env_file=".env", extra="ignore")

    app_name: str = "ParkFinder API"
    version: str = "0.1.0"

    # Security
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_per_minute: int = Field(default=60, ge=1)
    rate_limit_burst: int = Field(default=20, ge=1)
    max_bbox_span_deg: float = Field(default=1.0, gt=0, le=10)

    # Upstream providers
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    contact_email: str | None = None
    nominatim_min_interval_seconds: float = Field(default=1.0, ge=0)

    # Timeouts / retries
    connect_timeout: float = Field(default=5.0, gt=0)
    read_timeout: float = Field(default=25.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)
    max_retry_after_seconds: float = Field(default=5.0, ge=0)

    # Caching
    cache_ttl_seconds: float = Field(default=300, gt=0)
    geocode_cache_ttl_seconds: float = Field(default=86_400, gt=0)
    cache_max_entries: int = Field(default=256, ge=1)
    bbox_snap_deg: float = Field(default=0.01, gt=0)

    # Results
    max_results: int = Field(default=500, ge=1, le=2000)

    # Fallback data
    enable_sample_fallback: bool = True
    sample_data_path: Path = REPO_ROOT / "assets" / "parks.sample.json"

    # Logging / traceability
    log_level: str = "INFO"
    log_to_file: bool = True
    log_dir: Path = BACKEND_ROOT / "logs"
    log_file_name: str = "api.log"
    log_max_bytes: int = Field(default=5_000_000, ge=10_000)
    log_backup_count: int = Field(default=5, ge=0)

    @property
    def user_agent(self) -> str:
        """Identifying User-Agent required by the OpenStreetMap usage policies."""
        contact = f"; contact: {self.contact_email}" if self.contact_email else ""
        return f"ParkFinder/{self.version} (park-finder demo{contact})"


@lru_cache
def get_settings() -> Settings:
    return Settings()

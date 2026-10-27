"""Settings, read from environment variables (Cloud Run sets these from Secret Manager)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always the project's own .env, whichever folder uvicorn is started from.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Review sources. A source with no key is skipped, and the response says so.
    google_places_api_key: str = ""
    # A second, browser-visible key for the map (restrict it to the Maps JavaScript API and your
    # site's address). Without it the results page simply shows no map.
    google_maps_browser_key: str = ""
    # Map ID from Google Cloud console > Map management. DEMO_MAP_ID works for testing.
    google_map_id: str = "DEMO_MAP_ID"
    # Optional, paid. Without it US rows get a free "See on Yelp" link instead of a Yelp rating.
    yelp_api_key: str = ""

    # Tripadvisor, via its Terra API. Billed per item after a one-time free allowance.
    tripadvisor_api_key: str = ""
    tripadvisor_base_url: str = "https://terra.tripadvisor.com/api"
    # Billable items per UTC day before Tripadvisor is skipped until midnight. 0 = no cap.
    tripadvisor_daily_entity_limit: int = 30
    # Markets that use Tripadvisor, comma-separated.
    tripadvisor_markets: str = "us,tw"
    # One Michelin list per market (Michelin has no public API).
    michelin_us_csv_path: str = "data/michelin_us.csv"
    michelin_tw_csv_path: str = "data/michelin_tw.csv"

    # Storage: "memory" for local runs and tests, "firestore" on GCP.
    store: str = "memory"
    gcp_project: str = ""
    firestore_database: str = "(default)"

    # How long a search result is reused before calling the review APIs again.
    cache_ttl_hours: float = 6.0

    # Optional: if set, callers must send this value in the X-API-Key header.
    service_api_key: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

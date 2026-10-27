"""Data shapes shared by the sources, the aggregator and the API."""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Market(str, Enum):
    us = "us"
    tw = "tw"


class Review(BaseModel):
    source: str
    review_id: str
    rating: float | None = None
    text: str = ""
    language: str | None = None
    published_at: datetime | None = None


class SourceRating(BaseModel):
    source: str
    source_id: str
    name: str
    rating: float | None = None
    review_count: int | None = None
    url: str | None = None
    rating_image_url: str | None = Field(None, description="Tripadvisor bubble image, required when showing its rating")


class Link(BaseModel):
    label: str
    url: str


class Hours(BaseModel):
    weekday_text: list[str] = Field(default_factory=list, description="Monday first, as Google writes them")
    periods: list[dict] = Field(default_factory=list, description="Google's opening periods (day 0 = Sunday)")
    utc_offset_minutes: int | None = None
    open_now: bool | None = Field(None, description="Worked out when the response is sent, in the restaurant's local time")
    today: str | None = Field(None, description="Today's hours, e.g. '11:00 AM – 9:00 PM'")


class Place(BaseModel):
    """A restaurant as one source describes it."""
    source: str
    source_id: str
    name: str
    address: str = ""
    price_level: int | None = None  # 1-4, i.e. $ to $$$$
    cuisine: str | None = None
    rating: float | None = None
    review_count: int | None = None
    url: str | None = None
    lat: float | None = None
    lng: float | None = None
    rating_image_url: str | None = None
    hours: Hours | None = None
    price_range: str | None = None  # e.g. "$20–30"
    business_status: str | None = None  # OPERATIONAL, CLOSED_TEMPORARILY, CLOSED_PERMANENTLY
    reviews: list[Review] = Field(default_factory=list)


class RecentRating(BaseModel):
    average: float | None = None
    review_count: int = 0
    low_confidence: bool = True
    window_days: int = 90


class Suggestion(BaseModel):
    place_id: str
    main: str
    secondary: str = ""
    text: str = ""


class ResultRow(BaseModel):
    rank: int | None = None
    name: str
    address: str
    place_id: str | None = None
    lat: float | None = None
    lng: float | None = None
    price: str | None = None
    price_range: str | None = Field(None, description="Typical spend per person, e.g. '$20–30'")
    hours: Hours | None = None
    business_status: str | None = None
    cuisine: str | None = None
    ratings: list[SourceRating]
    all_time_rating: float | None = Field(None, description="Review-count-weighted average across sources")
    recent_3_months: RecentRating
    michelin: str | None = None
    top_dishes: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list, description="Other sites to check by hand, e.g. Yelp")
    source_status: dict[str, str] = Field(
        default_factory=dict,
        description="Per source: matched, no_match, not_checked, limit or error",
    )
    directions_url: str | None = Field(None, description="Opens Google Maps directions from the viewer's location")
    distance_km: float | None = Field(None, description="From the searched address (near-an-address mode only)")
    score: float | None = None


class Alternative(BaseModel):
    """Another branch matching the name (single-restaurant mode)."""
    name: str
    address: str
    place_id: str
    distance_km: float | None = Field(None, description="From the typed location")


class Center(BaseModel):
    lat: float
    lng: float
    label: str
    radius_km: float


class ResultTable(BaseModel):
    mode: str = Field("single", description="single (one restaurant) or nearby (closest to an address)")
    query: dict
    market: Market
    center: Center | None = Field(None, description="The searched address (nearby mode only)")
    alternatives: list[Alternative] = Field(
        default_factory=list, description="Other branches matching the name, closest to the location first")
    generated_at: datetime
    sources_used: list[str]
    sources_skipped: list[str]
    rows: list[ResultRow]
    notes: list[str]

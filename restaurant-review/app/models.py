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
    cuisine: str | None = None
    ratings: list[SourceRating]
    all_time_rating: float | None = Field(None, description="Review-count-weighted average across sources")
    recent_3_months: RecentRating
    michelin: str | None = None
    top_dishes: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list, description="Other sites to check by hand, e.g. Yelp")
    score: float | None = None


class ResultTable(BaseModel):
    query: dict
    market: Market
    generated_at: datetime
    sources_used: list[str]
    sources_skipped: list[str]
    rows: list[ResultRow]
    notes: list[str]

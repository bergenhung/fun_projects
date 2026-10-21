"""Yelp Fusion API (paid plan needed for the reviews endpoint). Used for US restaurants."""
import logging
from datetime import datetime, timezone

import httpx

from app.models import Place, Review

log = logging.getLogger(__name__)

BASE = "https://api.yelp.com/v3"


class Yelp:
    name = "yelp"

    def __init__(self, api_key: str, client: httpx.AsyncClient):
        self.api_key = api_key
        self.client = client

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    async def find(self, name: str, address: str, lat: float | None, lng: float | None) -> Place | None:
        """Find the Yelp listing for a restaurant another source already identified."""
        params: dict = {"term": name, "limit": 3, "categories": "restaurants,food"}
        if lat is not None and lng is not None:
            params.update(latitude=lat, longitude=lng, radius=300)
        else:
            params["location"] = address
        resp = await self.client.get(f"{BASE}/businesses/search", params=params, headers=self._headers)
        if resp.status_code != 200:
            log.warning("yelp search failed", extra={"status": resp.status_code, "body": resp.text[:300]})
            return None
        businesses = resp.json().get("businesses", [])
        best = _best_match(name, businesses)
        if not best:
            log.info("yelp no match", extra={"restaurant": name})
            return None
        place = self._to_place(best)
        place.reviews = await self._reviews(best["id"])
        return place

    async def _reviews(self, business_id: str) -> list[Review]:
        resp = await self.client.get(
            f"{BASE}/businesses/{business_id}/reviews",
            params={"sort_by": "newest", "limit": 7},
            headers=self._headers,
        )
        if resp.status_code != 200:
            # Starter plans have no reviews endpoint; the rating still counts.
            log.warning("yelp reviews unavailable", extra={"status": resp.status_code})
            return []
        out = []
        for r in resp.json().get("reviews", []):
            out.append(
                Review(
                    source=self.name,
                    review_id=r["id"],
                    rating=r.get("rating"),
                    text=r.get("text", ""),
                    language="en",
                    published_at=_parse_yelp_time(r.get("time_created")),
                )
            )
        return out

    def _to_place(self, b: dict) -> Place:
        coords = b.get("coordinates") or {}
        return Place(
            source=self.name,
            source_id=b["id"],
            name=b.get("name", ""),
            address=", ".join((b.get("location") or {}).get("display_address", [])),
            price_level=len(b["price"]) if b.get("price") else None,
            cuisine=", ".join(c["title"] for c in b.get("categories", [])) or None,
            rating=b.get("rating"),
            review_count=b.get("review_count"),
            url=(b.get("url") or "").split("?")[0] or None,
            lat=coords.get("latitude"),
            lng=coords.get("longitude"),
        )


def _best_match(name: str, businesses: list[dict]) -> dict | None:
    from app.matching import similarity

    scored = [(similarity(name, b.get("name", "")), b) for b in businesses]
    scored = [s for s in scored if s[0] >= 0.6]
    return max(scored, key=lambda s: s[0])[1] if scored else None


def _parse_yelp_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Yelp returns local time without a zone, e.g. "2026-08-29 19:41:13". Treated as UTC; a few hours don't matter here.
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

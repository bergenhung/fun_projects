"""Google Places API (New). Gives the all-time rating, review count and up to 5 reviews per place."""
import logging
from datetime import datetime

import httpx

from app.models import Market, Place, Review

log = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    f"places.{f}"
    for f in (
        "id", "displayName", "formattedAddress", "rating", "userRatingCount", "priceLevel",
        "googleMapsUri", "location", "primaryTypeDisplayName", "reviews",
    )
)
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
DETAILS_FIELD_MASK = FIELD_MASK.replace("places.", "")
AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
LOCATION_TYPES = ["locality", "sublocality", "neighborhood", "administrative_area_level_1", "postal_code"]
FOOD_TYPES = {"restaurant", "food", "cafe", "bar", "bakery", "meal_takeaway", "meal_delivery"}
PRICE_TO_ENUM = {
    1: "PRICE_LEVEL_INEXPENSIVE",
    2: "PRICE_LEVEL_MODERATE",
    3: "PRICE_LEVEL_EXPENSIVE",
    4: "PRICE_LEVEL_VERY_EXPENSIVE",
}
ENUM_TO_PRICE = {v: k for k, v in PRICE_TO_ENUM.items()}
LANG = {Market.us: ("en", "US"), Market.tw: ("zh-TW", "TW")}


class GooglePlaces:
    name = "google"

    def __init__(self, api_key: str, client: httpx.AsyncClient):
        self.api_key = api_key
        self.client = client

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        market: Market,
        price_levels: list[int] | None = None,
        min_rating: float | None = None,
        limit: int = 20,
    ) -> list[Place]:
        language, region = LANG[market]
        body: dict = {
            "textQuery": query,
            "languageCode": language,
            "regionCode": region,
            "includedType": "restaurant",
            "pageSize": max(1, min(limit, 20)),
        }
        if price_levels:
            body["priceLevels"] = [PRICE_TO_ENUM[p] for p in price_levels if p in PRICE_TO_ENUM]
        if min_rating:
            body["minRating"] = min_rating
        resp = await self.client.post(
            SEARCH_URL,
            json=body,
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK},
        )
        if resp.status_code != 200:
            log.error("google places search failed", extra={"status": resp.status_code, "body": resp.text[:500]})
            resp.raise_for_status()
        places = [self._to_place(p) for p in resp.json().get("places", [])]
        log.info("google places search", extra={"query": query, "results": len(places)})
        return places

    async def details(self, place_id: str, market: Market, session_token: str | None = None) -> Place | None:
        """Look up one place by ID (used when the person picked an autocomplete suggestion).
        Passing the autocomplete session token closes the session, which Google bills as one unit."""
        language, region = LANG[market]
        params = {"languageCode": language, "regionCode": region}
        if session_token:
            params["sessionToken"] = session_token
        resp = await self.client.get(
            DETAILS_URL.format(place_id=place_id),
            params=params,
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": DETAILS_FIELD_MASK},
        )
        if resp.status_code in (400, 404):
            log.info("google place not found", extra={"place_id": place_id, "status": resp.status_code})
            return None
        if resp.status_code != 200:
            log.error("google place details failed", extra={"status": resp.status_code, "body": resp.text[:500]})
            resp.raise_for_status()
        return self._to_place(resp.json())

    async def autocomplete(self, text: str, kind: str, session_token: str | None = None) -> list[dict]:
        """Suggestions as the person types. kind is "restaurant" or "location"."""
        language = "zh-TW" if _has_cjk(text) else "en"
        body: dict = {"input": text, "languageCode": language}
        if kind == "location":
            body["includedPrimaryTypes"] = LOCATION_TYPES
        if session_token:
            body["sessionToken"] = session_token
        resp = await self.client.post(AUTOCOMPLETE_URL, json=body, headers={"X-Goog-Api-Key": self.api_key})
        if resp.status_code != 200:
            log.error("google autocomplete failed", extra={"status": resp.status_code, "body": resp.text[:500]})
            resp.raise_for_status()
        out = []
        for s in resp.json().get("suggestions", []):
            p = s.get("placePrediction")
            if not p:
                continue
            types = set(p.get("types", []))
            # Primary-type filters would drop e.g. "ramen_restaurant", so filter on the full type list instead.
            if kind == "restaurant" and not types & FOOD_TYPES and not any(t.endswith("_restaurant") for t in types):
                continue
            fmt = p.get("structuredFormat") or {}
            out.append({
                "place_id": p.get("placeId"),
                "main": (fmt.get("mainText") or {}).get("text") or (p.get("text") or {}).get("text", ""),
                "secondary": (fmt.get("secondaryText") or {}).get("text", ""),
                "text": (p.get("text") or {}).get("text", ""),
            })
        return out

    def _to_place(self, p: dict) -> Place:
        reviews = []
        for r in p.get("reviews", []):
            text = (r.get("originalText") or r.get("text") or {})
            reviews.append(
                Review(
                    source=self.name,
                    # The review resource name is stable, so it doubles as an ID for de-duplication.
                    review_id=r.get("name") or f"{p['id']}:{r.get('publishTime')}",
                    rating=r.get("rating"),
                    text=text.get("text", ""),
                    language=text.get("languageCode"),
                    published_at=_parse_time(r.get("publishTime")),
                )
            )
        loc = p.get("location") or {}
        return Place(
            source=self.name,
            source_id=p["id"],
            name=(p.get("displayName") or {}).get("text", ""),
            address=p.get("formattedAddress", ""),
            price_level=ENUM_TO_PRICE.get(p.get("priceLevel", "")),
            cuisine=(p.get("primaryTypeDisplayName") or {}).get("text"),
            rating=p.get("rating"),
            review_count=p.get("userRatingCount"),
            url=p.get("googleMapsUri"),
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            reviews=reviews,
        )


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

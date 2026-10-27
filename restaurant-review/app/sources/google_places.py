"""Google Places API (New). Gives the all-time rating, review count and up to 5 reviews per place."""
import logging
import re
from datetime import datetime

import httpx

from app.models import Hours, Market, Place, Review

log = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    f"places.{f}"
    for f in (
        "id", "displayName", "formattedAddress", "rating", "userRatingCount", "priceLevel",
        "googleMapsUri", "location", "primaryTypeDisplayName", "reviews",
        # Hours and price range: no extra cost, since reviews already put requests in Google's top tier.
        "regularOpeningHours", "utcOffsetMinutes", "priceRange", "businessStatus",
    )
)
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
DETAILS_FIELD_MASK = FIELD_MASK.replace("places.", "")
AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
# The Geocoding API handles street intersections, which place search often doesn't. It must be
# enabled for the key; if it isn't, lookups fall back to place search.
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
INTERSECTION = re.compile(r"\s(?:&|and|at|@|/)\s|&|[A-Za-z]/[A-Za-z]|與|和.+路|交叉口|路口", re.I)


def is_intersection(text: str) -> bool:
    """'1st St & Mission St', 'Main and 5th', '忠孝東路與敦化南路'..."""
    return bool(INTERSECTION.search(text or ""))
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
        language: str | None = None,
        center: tuple[float, float] | None = None,
        radius_m: float | None = None,
    ) -> list[Place]:
        """Text search for restaurants. With center and radius_m, results are ranked by distance
        from that point (closest first); Google may still include a few just outside the radius."""
        default_language, region = LANG[market]
        language = language or default_language
        body: dict = {
            "textQuery": query,
            "languageCode": language,
            "regionCode": region,
            "includedType": "restaurant",
            "pageSize": max(1, min(limit, 20)),
        }
        if center:
            body["locationBias"] = {"circle": {
                "center": {"latitude": center[0], "longitude": center[1]},
                "radius": min(max(radius_m or 1000, 1), 50000),
            }}
            body["rankPreference"] = "DISTANCE"
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
        if resp.status_code == 400 and session_token:
            # The session token only affects billing; never let it block the lookup.
            log.warning("google place details rejected with session token; retrying without",
                        extra={"body": resp.text[:300]})
            return await self.details(place_id, market)
        if resp.status_code in (400, 404):
            log.info("google place not found", extra={"place_id": place_id, "status": resp.status_code,
                                                      "body": resp.text[:300]})
            return None
        if resp.status_code != 200:
            log.error("google place details failed", extra={"status": resp.status_code, "body": resp.text[:500]})
            resp.raise_for_status()
        return self._to_place(resp.json())

    async def locate(self, address: str, place_id: str | None = None, session_token: str | None = None,
                     region: str | None = None) -> tuple[float, float, str] | None:
        """Coordinates for an address: the place picked from autocomplete if given, otherwise the
        best text match. Only location fields are requested, which Google bills at its lowest tier."""
        headers = {"X-Goog-Api-Key": self.api_key}
        if place_id:
            params = {"sessionToken": session_token} if session_token else {}
            resp = await self.client.get(DETAILS_URL.format(place_id=place_id), params=params,
                                         headers={**headers, "X-Goog-FieldMask": "location,formattedAddress"})
            if resp.status_code == 400 and session_token:
                return await self.locate(address, place_id)
            if resp.status_code == 200 and (loc := resp.json().get("location")):
                return loc["latitude"], loc["longitude"], resp.json().get("formattedAddress") or address
            log.info("address place id lookup failed; using the text", extra={"status": resp.status_code})
        if not address:
            return None
        if is_intersection(address):
            if found := await self.geocode(address, region):
                return found
        resp = await self.client.post(
            SEARCH_URL, json={"textQuery": address, "pageSize": 1, **({"regionCode": region} if region else {})},
            headers={**headers, "X-Goog-FieldMask": "places.location,places.formattedAddress"},
        )
        if resp.status_code != 200:
            log.error("google address lookup failed", extra={"status": resp.status_code, "body": resp.text[:500]})
            resp.raise_for_status()
        places = resp.json().get("places", [])
        if not places or "location" not in places[0]:
            return None
        loc = places[0]["location"]
        return loc["latitude"], loc["longitude"], places[0].get("formattedAddress") or address

    async def geocode(self, address: str, region: str | None = None) -> tuple[float, float, str] | None:
        """Address or intersection -> coordinates, via the Geocoding API. None if not found or the
        API isn't enabled for this key (the caller then falls back to place search)."""
        params = {"address": address, "key": self.api_key}
        if region:
            params["region"] = region.lower()
        data = await self._geocoding(params)
        if not data:
            return None
        r = data["results"][0]
        loc = r["geometry"]["location"]
        return loc["lat"], loc["lng"], r.get("formatted_address") or address

    async def reverse_geocode(self, lat: float, lng: float, language: str = "en") -> str | None:
        """Coordinates -> a readable address, for a dropped pin or 'my location'."""
        data = await self._geocoding({"latlng": f"{lat},{lng}", "key": self.api_key, "language": language})
        return data["results"][0].get("formatted_address") if data else None

    async def _geocoding(self, params: dict) -> dict | None:
        try:
            resp = await self.client.get(GEOCODE_URL, params=params)
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            log.warning("google geocoding request failed")
            return None
        status = data.get("status")
        if status == "OK" and data.get("results"):
            return data
        if status != "ZERO_RESULTS":
            # Usually REQUEST_DENIED: the Geocoding API isn't enabled, or the key is restricted.
            log.warning("google geocoding unavailable; enable the Geocoding API for this key",
                        extra={"status": status, "error": data.get("error_message", "")[:200]})
        return None

    async def autocomplete(self, text: str, kind: str, session_token: str | None = None,
                           bias: tuple[float, float] | None = None) -> list[dict]:
        """Suggestions as the person types. kind is "restaurant", "location" (cities, districts)
        or "address" (anything with a location: street addresses, landmarks, hotels)."""
        language = "zh-TW" if _has_cjk(text) else "en"
        body: dict = {"input": text, "languageCode": language}
        if kind == "location":
            body["includedPrimaryTypes"] = LOCATION_TYPES
        if session_token:
            body["sessionToken"] = session_token
        if bias:
            # Favour this area (e.g. the Location field) over the person's own location.
            body["locationBias"] = {"circle": {"center": {"latitude": bias[0], "longitude": bias[1]},
                                               "radius": 30000}}
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
            hours=_hours(p),
            price_range=_price_range(p.get("priceRange")),
            business_status=p.get("businessStatus"),
            reviews=reviews,
        )


CURRENCY = {"USD": "$", "TWD": "NT$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _hours(p: dict) -> Hours | None:
    oh = p.get("regularOpeningHours") or {}
    if not oh.get("weekdayDescriptions") and not oh.get("periods"):
        return None
    return Hours(weekday_text=oh.get("weekdayDescriptions", []), periods=oh.get("periods", []),
                 utc_offset_minutes=p.get("utcOffsetMinutes"))


def _price_range(pr: dict | None) -> str | None:
    """{"startPrice": {"currencyCode": "USD", "units": "20"}, "endPrice": {...}} -> "$20–30"."""
    if not pr or not pr.get("startPrice"):
        return None
    start, end = pr["startPrice"], pr.get("endPrice") or {}
    code = start.get("currencyCode", "")
    sym = CURRENCY.get(code, f"{code} ")
    lo = f"{int(start.get('units', 0)):,}"
    if end.get("units"):
        return f"{sym}{lo}–{int(end['units']):,}"
    return f"{sym}{lo}+"


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

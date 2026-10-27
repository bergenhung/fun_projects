"""Tripadvisor via its Terra API (https://docs.terra.tripadvisor.com): rating, review count and
a few recent reviews per restaurant.

Cost control. Terra bills per "entity": every location a search returns counts as one, and each
details or reviews call counts as one. Errors aren't billed. So this module:
- finds the restaurant by name (narrowed to its postal code), falling back to a nearby search
  around Google's coordinates for names written differently on each site, asking for at most
  SEARCH_SIZE results each time;
- remembers the Tripadvisor ID for each Google place for 30 days (no-matches for 7), so later
  lookups skip the search and cost 2 entities (details + reviews);
- stops for the rest of the UTC day once TRIPADVISOR_DAILY_ENTITY_LIMIT is reached, or as soon as
  Tripadvisor answers 429 (over your plan's limit).

Display rules. Wherever its rating appears, Tripadvisor requires its bubble-rating image, a link
to the listing and a credit. The results page shows all three.

Response fields. Terra's public reference documents the endpoints but not every field name in the
Location and Review objects, so parsing below accepts the likely variants. The first response
of each kind is logged ("tripadvisor sample response") so any mismatch is easy to spot and fix.
"""
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.matching import similarity
from app.models import Market, Place, Review

log = logging.getLogger(__name__)

SEARCH_SIZE = 3            # each returned location is billed, so keep this small
NAME_SEARCH_MAX_KM = 1.0   # a same-named result further than this from Google's pin is another branch
COUNTRY = {Market.us: "US", Market.tw: "TW"}
SEARCH_RADIUS_KM = 0.3
NAME_MATCH = 0.6
# When names differ by language (Google: 鼎泰豐, Tripadvisor: Din Tai Fung), accept the
# nearest result if it's practically at the same spot and nothing else is close.
SAME_SPOT_KM = 0.03
LOCATION_ID_TTL_HOURS = 24 * 30
NO_MATCH_TTL_HOURS = 24 * 7
REVIEW_LANGUAGE = {Market.us: "en", Market.tw: "primary"}  # "primary" = as written, so local reviews
NAME_LOCALES = {Market.us: ["en"], Market.tw: ["zh-TW", "en"]}


class BudgetExhausted(Exception):
    pass


class Tripadvisor:
    name = "tripadvisor"

    def __init__(self, api_key: str, client: httpx.AsyncClient, store, base_url: str, daily_limit: int,
                 markets: set[Market] | None = None):
        self.api_key = api_key
        self.client = client
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.daily_limit = daily_limit
        self.markets = markets if markets is not None else {Market.us, Market.tw}
        self._day = ""
        self._spent_today = 0
        self._blocked_day = ""
        self._locale_ok = True
        self._last_status = 0
        self._sampled: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def enabled_for(self, market: Market) -> bool:
        return self.enabled and market in self.markets

    @property
    def spent_today(self) -> int:
        self._roll_day()
        return self._spent_today

    def _roll_day(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._spent_today = today, 0
        return today

    async def _get(self, path: str, params: list[tuple[str, str]], max_entities: int, kind: str) -> dict | None:
        today = self._roll_day()
        if self._blocked_day == today:
            raise BudgetExhausted()
        if self.daily_limit and self._spent_today + max_entities > self.daily_limit:
            raise BudgetExhausted()
        resp = await self.client.get(
            f"{self.base_url}{path}",
            params=[("version", "1"), *params],
            headers={"X-API-Key": self.api_key, "accept": "application/json"},
        )
        self._last_status = resp.status_code
        if resp.status_code == 429:
            self._blocked_day = today
            log.warning("tripadvisor plan limit reached (429); paused until midnight UTC")
            raise BudgetExhausted()
        if resp.status_code in (401, 403):
            log.error("tripadvisor rejected the API key; check TRIPADVISOR_API_KEY", extra={"status": resp.status_code})
            return None
        if resp.status_code != 200:
            log.warning("tripadvisor call failed", extra={"kind": kind, "status": resp.status_code, "body": resp.text[:300]})
            return None
        data = resp.json()
        billed = len(data.get("data", [])) if kind in ("nearby", "search") else 1
        self._spent_today += billed
        if kind not in self._sampled:
            self._sampled.add(kind)
            log.info("tripadvisor sample response", extra={"kind": kind, "sample": resp.text[:1500]})
        return data

    async def find(self, google_place_id: str, name: str, lat: float | None, lng: float | None,
                   market: Market, address: str = "") -> tuple[Place | None, str]:
        """Tripadvisor listing for a restaurant Google already found.
        Returns (place, status); status is "matched", "no_match", "limit" or "error"."""
        try:
            status, location_id, location = await self._locate(google_place_id, name, lat, lng, market, address)
            if status != "matched":
                return None, status
            if location is None or _rating(location) is None:
                location = await self._get(f"/locations/{location_id}", self._locale_params(market), 1, "details")
                if not location:
                    return None, "error"
            place = _to_place(location_id, location)
            reviews = await self._get(f"/locations/{location_id}/reviews",
                                      [("language", REVIEW_LANGUAGE[market]), ("size", "10")], 1, "reviews")
            if reviews:
                place.reviews = [r for r in (_to_review(x) for x in reviews.get("data", [])) if r]
            return place, "matched"
        except BudgetExhausted:
            log.warning("tripadvisor skipped: daily limit reached", extra={"limit": self.daily_limit})
            return None, "limit"

    def _locale_params(self, market: Market) -> list[tuple[str, str]]:
        return [("locale", loc) for loc in NAME_LOCALES[market]] if self._locale_ok else []

    async def _search(self, path: str, params: list[tuple[str, str]], market: Market, kind: str) -> dict | None:
        found = await self._get(path, params + self._locale_params(market), SEARCH_SIZE, kind)
        if found is None and self._locale_ok and self._last_status in (400, 422):
            # If Terra doesn't accept the locale format, stop sending it and retry once.
            self._locale_ok = False
            found = await self._get(path, params, SEARCH_SIZE, kind)
        return found

    async def _locate(self, google_place_id, name, lat, lng, market, address) -> tuple[str, str, dict | None]:
        """Returns (status, location_id, location-if-already-fetched)."""
        # Per market too: a lookup made with the wrong country (and found nothing) mustn't stick.
        key = f"ta-id|{market.value}|{google_place_id}"
        if cached := await self.store.get_cached(key):
            return ("matched", cached["location_id"], None) if cached.get("location_id") else ("no_match", "", None)

        best, errored = None, False
        # 1) By name, narrowed to the postal code. Ranking is by name, so a restaurant inside a
        #    busy mall or food court is still found.
        postal = postal_code(address)
        params = [("query", name), ("search_type", "NAME"), ("category", "RESTAURANT"),
                  ("country_code", COUNTRY[market]), ("size", str(SEARCH_SIZE))]
        if postal:
            params.append(("postal_code", postal))
        found = await self._search("/locations/search", params, market, "search")
        if found is None:
            errored = True
        else:
            best = match_by_name(name, found.get("data", []), lat, lng, narrowed=bool(postal))

        # 2) Nearby, for names written differently on each site (鼎泰豐 vs Din Tai Fung).
        if not best and lat is not None and lng is not None:
            params = [("lat", str(lat)), ("lon", str(lng)), ("radius", str(SEARCH_RADIUS_KM)), ("unit", "KM"),
                      ("category", "RESTAURANT"), ("sort", "distance,asc"), ("size", str(SEARCH_SIZE))]
            found = await self._search("/locations/nearby", params, market, "nearby")
            if found is None:
                errored = True
            else:
                best = match(name, found.get("data", []))

        location_id = str(best["id"]) if best and best.get("id") is not None else ""
        if not location_id:
            if errored:
                return "error", "", None  # not a confirmed no-match, so don't remember it
            log.info("tripadvisor no match", extra={"restaurant": name, "postal_code": postal})
        await self.store.set_cached(key, {"location_id": location_id},
                                    LOCATION_ID_TTL_HOURS if location_id else NO_MATCH_TTL_HOURS)
        return ("matched", location_id, best) if location_id else ("no_match", "", None)


# ---------- parsing ----------

def match(name: str, results: list[dict]) -> dict | None:
    scored = []
    for r in results:
        score = max((similarity(name, n) for n in _names(r)), default=0.0)
        if score >= NAME_MATCH:
            scored.append((score, r))
    if scored:
        return max(scored, key=lambda s: s[0])[1]
    # Position fallback, only when the names can't be compared because they're in different
    # scripts. Two same-script names that don't match are simply different restaurants.
    close = [r for r in results if (_num(r.get("distance_kilometers")) or 99) <= SAME_SPOT_KM * 2]
    if len(close) == 1 and (_num(close[0].get("distance_kilometers")) or 99) <= SAME_SPOT_KM:
        names = _names(close[0])
        if names and not any(_has_cjk(n) == _has_cjk(name) for n in names):
            return close[0]
    return None


def match_by_name(name: str, results: list[dict], lat: float | None, lng: float | None,
                  narrowed: bool) -> dict | None:
    """Best name match from a name search. Chains have many branches, so the result must also be
    near Google's pin when Tripadvisor gives coordinates, or the search must have been narrowed to
    the restaurant's postal code with only one same-named result."""
    named = [(max((similarity(name, n) for n in _names(r)), default=0.0), r) for r in results]
    named = [(score, r) for score, r in named if score >= NAME_MATCH]
    if not named:
        return None
    located = []
    for score, r in named:
        c = _coords(r)
        if c and lat is not None and lng is not None:
            km = _km(lat, lng, *c)
            if km <= NAME_SEARCH_MAX_KM:
                located.append((km, -score, r))
    if located:
        return min(located, key=lambda t: (t[0], t[1]))[2]
    if any(_coords(r) for _, r in named):
        return None  # coordinates known, and none of the same-named places is close: other branches
    if narrowed and len(named) == 1:
        return named[0][1]
    return None


def _coords(loc: dict) -> tuple[float, float] | None:
    for obj in (loc.get("coordinates"), loc.get("geo"), loc.get("location"), loc.get("position"), loc):
        if isinstance(obj, dict):
            la = _num(obj.get("latitude", obj.get("lat")))
            lo = _num(obj.get("longitude", obj.get("lon", obj.get("lng"))))
            if la is not None and lo is not None:
                return la, lo
    return None


def _km(lat1, lng1, lat2, lng2) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def postal_code(address: str) -> str:
    """US ZIP ("Santa Clara, CA 95050, USA") or Taiwan postal code ("110台北市…", "Taipei City, Taiwan 110")."""
    if not address:
        return ""
    if m := re.search(r"\b[A-Z]{2} (\d{5})(?:-\d{4})?\b", address):
        return m.group(1)
    if m := re.match(r"\s*(\d{3,6})(?=\D)", address):
        return m.group(1)
    if m := re.search(r"Taiwan (\d{3,6})\b", address):
        return m.group(1)
    return ""


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _names(loc: dict) -> list[str]:
    out = []
    for key in ("names", "name"):
        v = loc.get(key)
        items = v if isinstance(v, list) else [v]
        for item in items:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for k in ("value", "name", "text", "localized_name"):
                    if isinstance(item.get(k), str):
                        out.append(item[k])
    return [n for n in out if n]


def _overall(loc: dict) -> dict:
    tr = loc.get("traveler_ratings") or {}
    return tr.get("overall") or {} if isinstance(tr, dict) else {}


def _rating(loc: dict) -> float | None:
    o = _overall(loc)
    for v in (o.get("rating"), o.get("value"), o.get("average"), o.get("score"), loc.get("rating")):
        if (n := _num(v)) is not None:
            return n
    return None


def _count(loc: dict) -> int | None:
    o = _overall(loc)
    for v in (o.get("count"), o.get("review_count"), o.get("num_reviews"), o.get("total_count"),
              loc.get("num_reviews"), loc.get("review_count"), (loc.get("reviews") or {}).get("total_count")
              if isinstance(loc.get("reviews"), dict) else None):
        if (n := _num(v)) is not None:
            return int(n)
    return None


def _web_url(location_id: str, loc: dict) -> str:
    for v in (loc.get("web_url"), loc.get("url"), (loc.get("urls") or {}).get("web") if isinstance(loc.get("urls"), dict) else None,
              (loc.get("links") or {}).get("web") if isinstance(loc.get("links"), dict) else None):
        if isinstance(v, str) and v.startswith("http"):
            return v
    geo = loc.get("geo_id")
    if geo:
        return f"https://www.tripadvisor.com/Restaurant_Review-g{geo}-d{location_id}"
    name = next(iter(_names(loc)), "")
    return f"https://www.tripadvisor.com/Search?q={quote(name)}"


def _to_place(location_id: str, loc: dict) -> Place:
    return Place(
        source="tripadvisor",
        source_id=str(location_id),
        name=next(iter(_names(loc)), ""),
        rating=_rating(loc),
        review_count=_count(loc),
        url=_web_url(location_id, loc),
        rating_image_url=_overall(loc).get("icon_url") or loc.get("rating_image_url"),
    )


def _to_review(r: dict) -> Review | None:
    rid = r.get("id") or r.get("review_id")
    if rid is None:
        return None
    rating = r.get("rating")
    if isinstance(rating, dict):
        rating = rating.get("overall") or rating.get("value")
    published = None
    for k in ("published_date", "published_at", "publish_date", "created_at", "date"):
        if isinstance(r.get(k), str):
            try:
                published = datetime.fromisoformat(r[k].replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                pass
    text = " ".join(x for x in (_text(r.get("title")), _text(r.get("text") or r.get("body") or r.get("content"))) if x)
    return Review(source="tripadvisor", review_id=str(rid), rating=_num(rating), text=text,
                  language=r.get("language") or r.get("lang"), published_at=published)


def _text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("value") or v.get("text") or ""
    return ""


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None

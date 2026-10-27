"""Builds the cross-site rating table. Google Places finds restaurants in both markets; the other
sources depend on the market (see ReviewService._sources)."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app.dishes import extract_dishes
from app.matching import has_cjk, similarity
from app.models import Alternative, Center, Link, Market, Place, RecentRating, Review, ResultRow, ResultTable, SourceRating
from app.sources.google_places import GooglePlaces
from app.sources.michelin import Michelin
from app.sources.tripadvisor import Tripadvisor
from app.sources.yelp import Yelp

log = logging.getLogger(__name__)

TW_HINTS = (
    "taiwan", "taipei", "new taipei", "taichung", "tainan", "kaohsiung", "hsinchu", "taoyuan", "keelung",
    "taitung", "hualien", "yilan", "台灣", "臺灣", "台北", "臺北", "新北", "台中", "臺中", "台南", "臺南",
    "高雄", "新竹", "桃園", "基隆", "台東", "臺東", "花蓮", "宜蘭",
)
RECENT_DAYS = 90
REGION = {Market.us: "US", Market.tw: "TW"}
BRANCH_SEARCH_RADIUS_M = 20000  # look for branches around the typed location
MAX_ALTERNATIVES = 4
PICKED_PLACE_MAX_KM = 50  # a picked suggestion further than this from the typed location is another branch
MIN_RECENT_FOR_CONFIDENCE = 5
PRIOR_MEAN = 3.8   # Bayesian prior: a typical restaurant rating
PRIOR_WEIGHT = 50  # how many "virtual reviews" the prior counts as


class NotFound(Exception):
    pass


class SourceUnavailable(Exception):
    pass


def market_at(lat: float, lng: float) -> Market:
    """Taiwan (including Penghu, Kinmen and Matsu) by coordinates; anything else is US."""
    return Market.tw if 21.8 <= lat <= 26.5 and 118.0 <= lng <= 122.2 else Market.us


def detect_market(location: str, explicit: Market | None) -> Market:
    if explicit:
        return explicit
    loc = (location or "").lower()
    if any(h in loc for h in ("usa", "united states", "美國", "美国")):
        return Market.us  # an explicit country wins over a Taiwan-sounding street or dish name
    return Market.tw if any(h in loc for h in TW_HINTS) else Market.us


def bayesian(rating: float | None, count: int | None) -> float | None:
    """Pulls ratings with few reviews toward the prior, so a 5.0 from 3 reviews doesn't beat a 4.7 from 2,000."""
    if rating is None:
        return None
    n = count or 0
    return (PRIOR_MEAN * PRIOR_WEIGHT + rating * n) / (PRIOR_WEIGHT + n)


def price_label(level: int | None) -> str | None:
    return "$" * level if level else None


class ReviewService:
    def __init__(self, google: GooglePlaces, yelp: Yelp, michelin: dict[Market, Michelin], store, settings,
                 tripadvisor: Tripadvisor | None = None):
        self.google = google
        self.yelp = yelp
        self.michelin = michelin
        self.tripadvisor = tripadvisor
        self.store = store
        self.settings = settings
        # Popular prefixes ("ram", "rame") repeat a lot; reuse suggestions for an hour.
        self._suggest_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
        self._locate_cache: dict[tuple[str, str], tuple[float, tuple[float, float, str]]] = {}

    def _sources(self, market: Market) -> list:
        """US: Google, Tripadvisor, Yelp (only with a paid key), Michelin.
        Taiwan: Google, Tripadvisor, Michelin. TRIPADVISOR_MARKETS picks where Tripadvisor is used."""
        sources = [self.google]
        if self.tripadvisor and market in self.tripadvisor.markets:
            sources.append(self.tripadvisor)
        if market == Market.us and self.yelp.enabled:
            # Yelp is paid, so without a key it's left out quietly instead of listed as skipped.
            sources.append(self.yelp)
        sources.append(self.michelin[market])
        return sources

    def _source_status(self, market: Market) -> tuple[list[str], list[str]]:
        used, skipped = [], []
        for src in self._sources(market):
            (used if src.enabled else skipped).append(src.name)
        return used, skipped

    async def verify(
        self,
        name: str,
        location: str,
        market: Market | None,
        place_id: str | None = None,
        session_token: str | None = None,
    ) -> ResultTable:
        self._require_google()
        explicit = market
        market = detect_market(location, market)
        query = {"name": name, "location": location}
        cache_key = f"verify|{market.value}|{place_id or ''}|{name.lower()}|{location.lower()}"
        if cached := await self.store.get_cached(cache_key):
            log.info("cache hit", extra={"cache_key": cache_key})
            return ResultTable(**cached)

        if place_id:
            # Picked from autocomplete: no guessing which restaurant was meant.
            best = await self.google.details(place_id, market, session_token)
            if not best:
                if name:
                    # Fall back to a name search rather than giving up.
                    log.info("place id lookup failed; searching by name", extra={"place_id": place_id})
                    return await self.verify(name, location, explicit, None, None)
                raise NotFound("That restaurant couldn't be found. Try searching by name.")
            if location and name and best.lat is not None:
                # A suggestion can be for another branch (Google favours the person's own area),
                # so make sure the picked restaurant is actually where they said.
                try:
                    area = await self._locate(location)
                except Exception:
                    area = None
                if area and distance_km(area[0], area[1], best.lat, best.lng) > PICKED_PLACE_MAX_KM:
                    log.info("picked restaurant is far from the location; searching by name there",
                             extra={"picked": best.address, "location": location})
                    return await self.verify(name, location, explicit, None, None)
            # The restaurant's own address decides the market (language, sources), not the typed text.
            actual = detect_market(best.address, None)
            if not explicit and actual != market:
                market = actual
                best = await self.google.details(place_id, market) or best  # re-fetch in the local language
            query["name"] = query["name"] or best.name
        else:
            if not name:
                raise NotFound("Enter a restaurant name.")
            text = f"{name} {location}".strip()
            # Put the location on the map first (a city, district, street or landmark), so that when
            # a chain has several branches the one closest to it is chosen.
            area = None
            if location:
                try:
                    area = await self._locate(location, region=REGION[market])
                except Exception:
                    log.warning("couldn't locate the location; using text search only", extra={"location": location})
            center = area[:2] if area else None
            search = dict(limit=10, center=center, radius_m=BRANCH_SEARCH_RADIUS_M) if center else dict(limit=5)
            candidates = await self.google.search(text, market, **search)
            matches = _matches_by_name(name, candidates)
            if not matches and candidates and not any(has_cjk(c.name) == has_cjk(name) for c in candidates):
                # Typed "Din Tai Fung" but Google answered in Chinese ("鼎泰豐"), or the reverse.
                # Ask again in the typed name's language, match there, then keep the local-language
                # version of the same places (their names and reviews suit the market better).
                other = await self.google.search(text, market, language="zh-TW" if has_cjk(name) else "en", **search)
                by_id = {c.source_id: c for c in candidates}
                matches = [by_id.get(m.source_id, m) for m in _matches_by_name(name, other)]
                if matches:
                    log.info("matched across languages", extra={"typed": name, "matched": matches[0].name})
            if center:
                matches.sort(key=lambda p: distance_km(*center, p.lat, p.lng) if p.lat is not None else 1e9)
            best = matches[0] if matches else None
            alternatives = [
                Alternative(name=m.name, address=m.address, place_id=m.source_id,
                            distance_km=round(distance_km(*center, m.lat, m.lng), 2) if center and m.lat is not None else None)
                for m in matches[1:1 + MAX_ALTERNATIVES]
            ]
            if not best:
                seen = [f"{c.name} ({c.address})" for c in candidates[:3]]
                log.info("verify no match", extra={"typed": name, "location": location, "market": market.value,
                                                   "google_returned": seen})
                found = f" Google returned: {'; '.join(seen)}." if seen else " Google returned no restaurants."
                raise NotFound(
                    f"No restaurant matching '{name}' near '{location}'.{found} "
                    "Try picking it from the suggestions as you type."
                )
        row = await self._build_row(best, market)
        table = self._table(query, market, [row])
        if not place_id:
            table.alternatives = alternatives
        await self.store.set_cached(cache_key, table.model_dump(mode="json"), self.settings.cache_ttl_hours)
        return table

    async def nearby(
        self,
        address: str,
        market: Market | None,
        count: int = 3,
        within_km: float = 1.0,
        cuisine: str | None = None,
        price_levels: list[int] | None = None,
        min_rating: float | None = None,
        sort: str = "distance",
        place_id: str | None = None,
        session_token: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
    ) -> ResultTable:
        """The `count` restaurants closest to a starting point, found on Google, each then looked up
        on Tripadvisor and Michelin. The start is an address, cross streets ("1st St & Mission St,
        San Francisco"), or a point on the map / the person's location (lat, lng)."""
        self._require_google()
        if lat is not None and lng is not None:
            market = market or market_at(lat, lng)
            label = await self._describe_point(lat, lng, market) or address or f"the pin at {lat:.5f}, {lng:.5f}"
        else:
            located = await self._locate(address, place_id, session_token)
            if not located:
                raise NotFound(f"Couldn't find '{address}'. Try picking it from the suggestions, "
                               "or drop a pin on the map instead.")
            lat, lng, label = located
            market = detect_market(f"{address} {label}", market)
        query = {"address": address, "count": count, "within_km": within_km, "cuisine": cuisine,
                 "price": price_levels, "min_rating": min_rating, "sort": sort}
        # Rounded to ~10 m, so the same address typed or picked shares the cache.
        cache_key = (f"nearby|{market.value}|{lat:.4f},{lng:.4f}|"
                     f"{sorted((k, str(v).lower()) for k, v in query.items() if k != 'address')}")
        if cached := await self.store.get_cached(cache_key):
            log.info("cache hit", extra={"cache_key": cache_key})
            return ResultTable(**cached)

        text = f"{cuisine} restaurant" if cuisine else "restaurant"
        found = await self.google.search(text, market, price_levels=price_levels, min_rating=min_rating,
                                         limit=20, center=(lat, lng), radius_m=within_km * 1000)
        # Google's distance ranking is a bias, so measure and enforce the radius here.
        candidates = sorted(
            ((distance_km(lat, lng, p.lat, p.lng), p) for p in found
             if p.lat is not None and p.lng is not None and p.business_status != "CLOSED_PERMANENTLY"),
            key=lambda t: t[0],
        )
        candidates = [(d, p) for d, p in candidates if d <= within_km][:count]
        if not candidates:
            filters = " with those filters" if (cuisine or price_levels or min_rating) else ""
            raise NotFound(f"No restaurants{filters} within {within_km:g} km of {label}. Try a larger distance.")

        rows = list(await asyncio.gather(*(self._build_row(p, market) for _, p in candidates)))
        for row, (d, _) in zip(rows, candidates):
            row.distance_km = round(d, 2)
        if sort == "rating":
            rows.sort(key=lambda r: r.score or 0, reverse=True)
        for i, r in enumerate(rows, 1):
            r.rank = i
        table = self._table(query, market, rows)
        table.mode = "nearby"
        table.center = Center(lat=lat, lng=lng, label=label, radius_km=within_km)
        await self.store.set_cached(cache_key, table.model_dump(mode="json"), self.settings.cache_ttl_hours)
        return table

    async def _locate(self, address: str, place_id: str | None = None,
                      session_token: str | None = None, region: str | None = None) -> tuple[float, float, str] | None:
        """Coordinates for an address or area. Addresses don't move, so lookups are remembered
        for a day and repeat searches skip the Google call. `region` ("US", "TW") resolves
        ambiguous names like 信義區 within that country."""
        loc_key = (place_id or "", address.strip().lower(), region or "")
        hit = self._locate_cache.get(loc_key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        located = await self.google.locate(address, place_id, session_token, region=region)
        if located:
            if len(self._locate_cache) > 5000:
                self._locate_cache.clear()
            self._locate_cache[loc_key] = (time.monotonic() + 86400, located)
        return located

    async def locate_point(self, address: str, place_id: str | None = None,
                           session_token: str | None = None) -> tuple[float, float, str] | None:
        """For the map picker: move the pin to an address or cross streets."""
        self._require_google()
        return await self._locate(address, place_id, session_token)

    async def _describe_point(self, lat: float, lng: float, market: Market) -> str | None:
        """A readable address for a dropped pin (remembered for a day, like address lookups)."""
        key = ("pin", f"{lat:.5f},{lng:.5f}", market.value)
        hit = self._locate_cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        label = await self.google.reverse_geocode(lat, lng, "zh-TW" if market == Market.tw else "en")
        if label:
            self._locate_cache[key] = (time.monotonic() + 86400, label)
        return label

    async def autocomplete(self, text: str, kind: str, session_token: str | None = None,
                           near: str | None = None) -> list[dict]:
        """Suggestions while typing. `near` (e.g. the Location field) makes Google favour that area
        instead of wherever the person happens to be."""
        self._require_google()
        near = (near or "").strip()
        key = (kind, text.strip().lower(), near.lower())
        now = time.monotonic()
        if (hit := self._suggest_cache.get(key)) and hit[0] > now:
            return hit[1]
        bias = None
        if near:
            try:
                if located := await self._locate(near):
                    bias = located[:2]
            except Exception:
                log.warning("couldn't locate the area for suggestions; using no bias", extra={"near": near})
        results = await self.google.autocomplete(text.strip(), kind, session_token, bias=bias)
        if len(self._suggest_cache) > 2000:
            self._suggest_cache.clear()
        self._suggest_cache[key] = (now + 3600, results)
        return results

    def _require_google(self):
        if not self.google.enabled:
            raise SourceUnavailable(
                "GOOGLE_PLACES_API_KEY is not set. Add it to the .env file in the project folder "
                "(GOOGLE_PLACES_API_KEY=your-key) and restart the server."
            )

    async def _build_row(self, place: Place, market: Market, with_tripadvisor: bool = True) -> ResultRow:
        ratings = [SourceRating(source=place.source, source_id=place.source_id, name=place.name,
                                rating=place.rating, review_count=place.review_count, url=place.url)]
        new_reviews: list[Review] = list(place.reviews)
        michelin_label = None

        status: dict[str, str] = {"google": "matched"}
        if self.tripadvisor and self.tripadvisor.enabled_for(market):
            if not with_tripadvisor:
                status["tripadvisor"] = "not_checked"
            else:
                try:
                    ta, status["tripadvisor"] = await self.tripadvisor.find(
                        place.source_id, place.name, place.lat, place.lng, market, place.address)
                except Exception:
                    log.exception("tripadvisor lookup failed", extra={"restaurant": place.name})
                    ta, status["tripadvisor"] = None, "error"
                if ta:
                    ratings.append(SourceRating(source=ta.source, source_id=ta.source_id, name=ta.name,
                                                rating=ta.rating, review_count=ta.review_count, url=ta.url,
                                                rating_image_url=ta.rating_image_url))
                    new_reviews += ta.reviews

        if market == Market.us and self.yelp.enabled:
            try:
                yp = await self.yelp.find(place.name, place.address, place.lat, place.lng)
            except Exception:
                log.exception("yelp lookup failed", extra={"restaurant": place.name})
                yp = None
                status["yelp"] = "error"
            status.setdefault("yelp", "matched" if yp else "no_match")
            if yp:
                ratings.append(SourceRating(source=yp.source, source_id=yp.source_id, name=yp.name,
                                            rating=yp.rating, review_count=yp.review_count, url=yp.url))
                new_reviews += yp.reviews
        guide = self.michelin.get(market)
        if guide and guide.enabled:
            if entry := guide.lookup(place.name, place.address):
                michelin_label = f"{entry.distinction} ({entry.year})" if entry.year else entry.distinction

        # Save what we saw, and compute history-based columns from everything saved so far.
        all_reviews = await self.store.add_reviews(f"google:{place.source_id}", new_reviews)

        return ResultRow(
            name=place.name,
            address=place.address,
            place_id=place.source_id,
            lat=place.lat,
            lng=place.lng,
            price=price_label(place.price_level),
            price_range=place.price_range,
            hours=place.hours,
            business_status=place.business_status,
            cuisine=place.cuisine,
            ratings=ratings,
            all_time_rating=_weighted_rating(ratings),
            recent_3_months=_recent(all_reviews),
            michelin=michelin_label,
            top_dishes=extract_dishes(all_reviews),
            links=_manual_links(place, market, has_yelp_rating=any(r.source == "yelp" for r in ratings),
                                in_michelin_list=michelin_label is not None),
            directions_url=_directions_url(place),
            source_status=status,
            score=_score(ratings),
        )

    def _table(self, query: dict, market: Market, rows: list[ResultRow]) -> ResultTable:
        used, skipped = self._source_status(market)
        notes = [
            "All-time ratings come straight from each site.",
            f"The 3-month rating uses reviews saved by this service in the last {RECENT_DAYS} days; "
            "the sites return only a few reviews per request, so it grows more reliable over time.",
            "Top dishes are estimated from phrases in saved reviews.",
        ]
        notes.append("Michelin status comes from a list maintained with this service; update it after each guide release.")
        if "tripadvisor" in used:
            notes.append("Tripadvisor ratings and reviews © Tripadvisor; follow the rating to see the listing.")
        if market == Market.us and "yelp" not in used:
            notes.append("Yelp ratings aren't included (its API is paid); use each row's See on Yelp link.")
        if skipped:
            notes.append(f"Skipped (no API key or data): {', '.join(skipped)}.")
        return ResultTable(
            query=query, market=market, generated_at=datetime.now(timezone.utc),
            sources_used=used, sources_skipped=skipped, rows=rows, notes=notes,
        )


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance between two points on Earth."""
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _matches_by_name(name: str, places: list[Place], threshold: float = 0.6) -> list[Place]:
    """Every place whose name matches, best match first (several when it's a chain)."""
    scored = [(similarity(name, p.name), i, p) for i, p in enumerate(places)]
    return [p for s, i, p in sorted(scored, key=lambda t: (-t[0], t[1])) if s >= threshold]


def _best_by_name(name: str, places: list[Place], threshold: float = 0.6) -> Place | None:
    best = max(places, key=lambda p: similarity(name, p.name), default=None)
    return best if best and similarity(name, best.name) >= threshold else None


def _directions_url(place: Place) -> str:
    """A Google Maps directions link (free, no key). Google Maps starts from the viewer's own
    location and lets them pick driving, transit, walking or cycling; on phones it opens the app."""
    params = {"api": "1", "destination": f"{place.name}, {place.address}".strip(", ")}
    if place.source == "google" and place.source_id:
        params["destination_place_id"] = place.source_id
    return f"https://www.google.com/maps/dir/?{urlencode(params)}"


MICHELIN_SEARCH = {Market.us: "https://guide.michelin.com/us/en/search", Market.tw: "https://guide.michelin.com/tw/zh_TW/search"}


def _manual_links(place: Place, market: Market, has_yelp_rating: bool, in_michelin_list: bool = False) -> list[Link]:
    """Links the person opens themselves: free, and within each site's normal use."""
    links = []
    if not in_michelin_list:
        # Michelin has no API; this searches the Guide's own site for the restaurant.
        links.append(Link(label="Check Michelin Guide",
                          url=f"{MICHELIN_SEARCH[market]}?{urlencode({'q': place.name})}"))
    if market == Market.us and not has_yelp_rating:
        # Yelp has little Taiwan coverage; with a paid key the rating is already shown.
        # Street address narrows the search to the right branch; fall back to name only.
        loc = place.address.replace(", USA", "").replace(", United States", "")
        params = urlencode({"find_desc": place.name, "find_loc": loc} if loc else {"find_desc": place.name})
        links.append(Link(label="See on Yelp", url=f"https://www.yelp.com/search?{params}"))
    return links


def _weighted_rating(ratings: list[SourceRating]) -> float | None:
    rated = [r for r in ratings if r.rating is not None]
    if not rated:
        return None
    weights = [max(r.review_count or 0, 1) for r in rated]
    return round(sum(r.rating * w for r, w in zip(rated, weights)) / sum(weights), 2)


def _score(ratings: list[SourceRating]) -> float | None:
    parts = [(bayesian(r.rating, r.review_count), max(r.review_count or 0, 1)) for r in ratings if r.rating is not None]
    if not parts:
        return None
    return round(sum(s * w for s, w in parts) / sum(w for _, w in parts), 3)


def _recent(reviews: list[Review]) -> RecentRating:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = [r.rating for r in reviews if r.rating is not None and r.published_at and r.published_at >= cutoff]
    return RecentRating(
        average=round(sum(recent) / len(recent), 2) if recent else None,
        review_count=len(recent),
        low_confidence=len(recent) < MIN_RECENT_FOR_CONFIDENCE,
        window_days=RECENT_DAYS,
    )

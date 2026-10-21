"""Builds the cross-site rating table. Google Places finds restaurants in both markets; the other
sources depend on the market (see ReviewService._sources)."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app.dishes import extract_dishes
from app.matching import similarity
from app.models import Link, Market, Place, RecentRating, Review, ResultRow, ResultTable, SourceRating
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
MIN_RECENT_FOR_CONFIDENCE = 5
PRIOR_MEAN = 3.8   # Bayesian prior: a typical restaurant rating
PRIOR_WEIGHT = 50  # how many "virtual reviews" the prior counts as


class NotFound(Exception):
    pass


class SourceUnavailable(Exception):
    pass


def detect_market(location: str, explicit: Market | None) -> Market:
    if explicit:
        return explicit
    loc = (location or "").lower()
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
                raise NotFound("That restaurant couldn't be found. Try searching by name.")
            if not explicit and not location and detect_market(best.address, None) != market:
                market = detect_market(best.address, None)
                best = await self.google.details(place_id, market) or best  # re-fetch in the local language
            query["name"] = query["name"] or best.name
        else:
            if not name:
                raise NotFound("Enter a restaurant name.")
            candidates = await self.google.search(f"{name} {location}".strip(), market, limit=5)
            best = max(candidates, key=lambda p: similarity(name, p.name), default=None)
            if not best or similarity(name, best.name) < 0.6:
                raise NotFound(f"No restaurant matching '{name}' near '{location}'.")
        row = await self._build_row(best, market)
        table = self._table(query, market, [row])
        await self.store.set_cached(cache_key, table.model_dump(mode="json"), self.settings.cache_ttl_hours)
        return table

    async def top(
        self,
        location: str,
        market: Market | None,
        cuisine: str | None = None,
        price_levels: list[int] | None = None,
        min_rating: float | None = None,
        limit: int = 5,
    ) -> ResultTable:
        market = detect_market(location, market)
        self._require_google()
        query = {"location": location, "cuisine": cuisine, "price": price_levels, "min_rating": min_rating, "limit": limit}
        cache_key = f"top|{market.value}|{sorted((k, str(v).lower()) for k, v in query.items())}"
        if cached := await self.store.get_cached(cache_key):
            log.info("cache hit", extra={"cache_key": cache_key})
            return ResultTable(**cached)

        text = f"{cuisine} restaurants in {location}" if cuisine else f"restaurants in {location}"
        candidates = await self.google.search(text, market, price_levels=price_levels, min_rating=min_rating, limit=20)
        if not candidates:
            raise NotFound("No restaurants matched those filters.")
        # Shortlist on Google alone, then spend second-source API calls only on the shortlist.
        candidates.sort(key=lambda p: bayesian(p.rating, p.review_count) or 0, reverse=True)
        shortlist = candidates[: max(limit, self.settings.enrich_limit)]
        # Tripadvisor bills per item, so only the restaurants likely to be shown get checked there.
        rows = await asyncio.gather(*(
            self._build_row(p, market, with_tripadvisor=i < limit) for i, p in enumerate(shortlist)
        ))
        rows = sorted(rows, key=lambda r: r.score or 0, reverse=True)[:limit]
        for i, r in enumerate(rows, 1):
            r.rank = i
        table = self._table(query, market, rows)
        await self.store.set_cached(cache_key, table.model_dump(mode="json"), self.settings.cache_ttl_hours)
        return table

    async def autocomplete(self, text: str, kind: str, session_token: str | None = None) -> list[dict]:
        self._require_google()
        key = (kind, text.strip().lower())
        now = time.monotonic()
        if (hit := self._suggest_cache.get(key)) and hit[0] > now:
            return hit[1]
        results = await self.google.autocomplete(text.strip(), kind, session_token)
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

        if with_tripadvisor and self.tripadvisor and self.tripadvisor.enabled_for(market):
            try:
                ta = await self.tripadvisor.find(place.source_id, place.name, place.lat, place.lng, market)
            except Exception:
                log.exception("tripadvisor lookup failed", extra={"restaurant": place.name})
                ta = None
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
            cuisine=place.cuisine,
            ratings=ratings,
            all_time_rating=_weighted_rating(ratings),
            recent_3_months=_recent(all_reviews),
            michelin=michelin_label,
            top_dishes=extract_dishes(all_reviews),
            links=_manual_links(place, market, has_yelp_rating=any(r.source == "yelp" for r in ratings)),
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


def _manual_links(place: Place, market: Market, has_yelp_rating: bool) -> list[Link]:
    """Links the person opens themselves: free, and within each site's normal use."""
    if market != Market.us or has_yelp_rating:
        return []  # Yelp has little Taiwan coverage; with a paid key the rating is already shown.
    # Street address narrows the search to the right branch; fall back to name only.
    loc = place.address.replace(", USA", "").replace(", United States", "")
    params = urlencode({"find_desc": place.name, "find_loc": loc} if loc else {"find_desc": place.name})
    return [Link(label="See on Yelp", url=f"https://www.yelp.com/search?{params}")]


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

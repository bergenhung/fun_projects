"""Review history and response cache.

The review APIs only return a handful of recent reviews per call. Saving every review we see
builds up history over time, which makes the 3-month rating and top dishes more reliable.
"""
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from app.models import Review

log = logging.getLogger(__name__)

MAX_REVIEWS_PER_RESTAURANT = 300


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _merge(existing: dict[str, dict], new: list[Review]) -> dict[str, dict]:
    for r in new:
        existing[_key(f"{r.source}:{r.review_id}")] = r.model_dump(mode="json")
    if len(existing) > MAX_REVIEWS_PER_RESTAURANT:
        newest = sorted(existing.items(), key=lambda kv: kv[1].get("published_at") or "", reverse=True)
        existing = dict(newest[:MAX_REVIEWS_PER_RESTAURANT])
    return existing


class MemoryStore:
    def __init__(self):
        self._reviews: dict[str, dict[str, dict]] = {}
        self._cache: dict[str, tuple[float, dict]] = {}

    async def add_reviews(self, restaurant_id: str, reviews: list[Review]) -> list[Review]:
        merged = _merge(self._reviews.get(restaurant_id, {}), reviews)
        self._reviews[restaurant_id] = merged
        return [Review(**v) for v in merged.values()]

    async def get_cached(self, key: str) -> dict | None:
        hit = self._cache.get(_key(key))
        if hit and hit[0] > time.time():
            return hit[1]
        return None

    async def set_cached(self, key: str, value: dict, ttl_hours: float) -> None:
        self._cache[_key(key)] = (time.time() + ttl_hours * 3600, value)


class FirestoreStore:
    """Firestore in Native mode. Collections: restaurants/{id} and query_cache/{hash}."""

    def __init__(self, project: str | None, database: str):
        from google.cloud import firestore

        self.db = firestore.AsyncClient(project=project or None, database=database)

    async def add_reviews(self, restaurant_id: str, reviews: list[Review]) -> list[Review]:
        ref = self.db.collection("restaurants").document(_key(restaurant_id))
        snap = await ref.get()
        existing = (snap.to_dict() or {}).get("reviews", {}) if snap.exists else {}
        merged = _merge(existing, reviews)
        if reviews:
            await ref.set(
                {"restaurant_id": restaurant_id, "reviews": merged, "updated_at": datetime.now(timezone.utc)},
                merge=False,
            )
        return [Review(**v) for v in merged.values()]

    async def get_cached(self, key: str) -> dict | None:
        snap = await self.db.collection("query_cache").document(_key(key)).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        if data["expires_at"] <= datetime.now(timezone.utc):
            return None
        return json.loads(data["payload"])

    async def set_cached(self, key: str, value: dict, ttl_hours: float) -> None:
        expires = datetime.fromtimestamp(time.time() + ttl_hours * 3600, timezone.utc)
        # expires_at also drives a Firestore TTL policy that deletes old entries (see README).
        await self.db.collection("query_cache").document(_key(key)).set(
            {"key": key, "payload": json.dumps(value, default=str), "expires_at": expires}
        )


def make_store(kind: str, project: str, database: str):
    if kind == "firestore":
        log.info("using firestore store", extra={"database": database})
        return FirestoreStore(project, database)
    log.info("using in-memory store")
    return MemoryStore()

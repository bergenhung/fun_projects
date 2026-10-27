"""FastAPI entry point. Run locally with: uvicorn app.main:app --reload"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import ENV_FILE, get_settings
from app.hours import refresh as refresh_hours
from app.logging_setup import request_id_var, setup_logging, trace_var
from app.models import Market, ResultTable, Suggestion
from app.render import search_page, table_page
from app.service import NotFound, ReviewService, SourceUnavailable
from app.sources.google_places import GooglePlaces
from app.sources.michelin import Michelin
from app.sources.tripadvisor import Tripadvisor
from app.sources.yelp import Yelp
from app.store import make_store

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    store = make_store(s.store, s.gcp_project, s.firestore_database)
    ta_markets = {Market(m.strip()) for m in s.tripadvisor_markets.split(",") if m.strip() in ("us", "tw")}
    app.state.service = ReviewService(
        google=GooglePlaces(s.google_places_api_key, client),
        yelp=Yelp(s.yelp_api_key, client),
        michelin={Market.us: Michelin(s.michelin_us_csv_path), Market.tw: Michelin(s.michelin_tw_csv_path)},
        tripadvisor=Tripadvisor(s.tripadvisor_api_key, client, store, s.tripadvisor_base_url,
                                s.tripadvisor_daily_entity_limit, ta_markets),
        store=store,
        settings=s,
    )
    log.info("service started", extra={
        "store": s.store, "google": bool(s.google_places_api_key), "yelp": bool(s.yelp_api_key),
        "tripadvisor": bool(s.tripadvisor_api_key), "tripadvisor_markets": sorted(m.value for m in ta_markets),
    })
    if not s.google_places_api_key:
        log.warning(
            "GOOGLE_PLACES_API_KEY is empty: searches will fail until it's set",
            extra={"env_file": str(ENV_FILE), "env_file_exists": ENV_FILE.exists()},
        )
    yield
    await client.aclose()


app = FastAPI(
    title="Cross-site restaurant review",
    version="0.1.0",
    description=(
        "Two modes, both starting from Google Maps: check one restaurant (/v1/verify), or list the "
        "restaurants closest to an address (/v1/nearby). Each restaurant Google returns is then looked "
        "up on Tripadvisor and checked against the Michelin Guide list."
    ),
    lifespan=lifespan,
)

OPEN_PATHS = {"/", "/healthz", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def request_context(request: Request, call_next):
    # Cloud Run sends "TRACE_ID/SPAN_ID;o=1"; logging the trace ID groups a request's log lines.
    trace_header = request.headers.get("x-cloud-trace-context", "")
    trace_var.set(trace_header.split("/")[0] or None)
    request_id_var.set(request.headers.get("x-request-id") or uuid.uuid4().hex[:12])

    key = get_settings().service_api_key
    if key and request.url.path not in OPEN_PATHS and request.headers.get("x-api-key") != key:
        return JSONResponse({"detail": "Missing or invalid X-API-Key header."}, status_code=401)

    start = time.perf_counter()
    response = await call_next(request)
    log.info(
        "request",
        extra={
            "httpRequest": {
                "requestMethod": request.method,
                "requestUrl": str(request.url.path),
                "status": response.status_code,
                "latency": f"{time.perf_counter() - start:.3f}s",
                "userAgent": request.headers.get("user-agent", ""),
            },
            "query": dict(request.query_params),
        },
    )
    return response


def parse_price(price: str | None) -> list[int] | None:
    """Accepts "$$", "$-$$$" or "1,2"."""
    if not price:
        return None
    price = price.strip()
    try:
        if "-" in price:
            lo, hi = (len(p.strip()) if "$" in p else int(p) for p in price.split("-", 1))
            levels = list(range(lo, hi + 1))
        elif "$" in price:
            levels = [len(price)]
        else:
            levels = [int(p) for p in price.split(",")]
    except ValueError:
        raise HTTPException(422, "price must look like $$, $-$$$ or 1,2")
    if not levels or any(lv < 1 or lv > 4 for lv in levels):
        raise HTTPException(422, "price levels run from $ (1) to $$$$ (4)")
    return levels


def parse_min_rating(value: str | None) -> float | None:
    # Kept as text so an empty form field means "any" instead of a validation error.
    if not value:
        return None
    try:
        rating = float(value)
    except ValueError:
        raise HTTPException(422, "min_rating must be a number from 1 to 5")
    if not 1 <= rating <= 5:
        raise HTTPException(422, "min_rating must be a number from 1 to 5")
    return rating


def respond(table: ResultTable, fmt: str):
    refresh_hours(table)  # open/closed as of now, even for a cached result
    if fmt != "html":
        return table
    s = get_settings()
    return HTMLResponse(table_page(table, s.google_maps_browser_key, s.google_map_id))


async def run(coro):
    try:
        return await coro
    except NotFound as e:
        raise HTTPException(404, str(e))
    except SourceUnavailable as e:
        raise HTTPException(503, str(e))
    except httpx.HTTPError:
        log.exception("upstream review site error")
        raise HTTPException(502, "A review site didn't respond properly. Try again shortly.")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home():
    s = get_settings()
    return search_page(s.google_maps_browser_key, s.google_map_id)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


@app.get("/v1/autocomplete", response_model=list[Suggestion], summary="Suggestions while typing")
async def autocomplete(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100, description="What the person has typed so far"),
    kind: Literal["restaurant", "location", "address"] = "restaurant",
    session: str | None = Query(None, max_length=64, description="Random ID per typing session (lowers Google billing)"),
    near: str | None = Query(None, max_length=120, description="Favour suggestions near this place, e.g. 'Taipei'"),
):
    return await run(request.app.state.service.autocomplete(q, kind, session, near))


@app.get("/v1/verify", response_model=ResultTable, summary="Check one restaurant across review sites")
async def verify(
    request: Request,
    name: str = Query("", max_length=120, examples=["Din Tai Fung"]),
    location: str = Query("", max_length=120, examples=["Taipei"]),
    place_id: str | None = Query(None, max_length=200, description="From /v1/autocomplete; skips name matching"),
    session: str | None = Query(None, max_length=64, description="The autocomplete session ID, if any"),
    market: Market | None = Query(None, description="us or tw; detected from location if omitted"),
    format: Literal["json", "html"] = "json",
):
    if not place_id and (not name.strip() or not location.strip()):
        raise HTTPException(422, "Give name and location, or a place_id from autocomplete.")
    table = await run(
        request.app.state.service.verify(name.strip(), location.strip(), market, place_id or None, session or None)
    )
    return respond(table, format)


@app.get("/v1/nearby", response_model=ResultTable, summary="The restaurants closest to an address")
async def nearby(
    request: Request,
    address: str = Query("", max_length=200, examples=["2855 Stevens Creek Blvd, Santa Clara, CA"]),
    place_id: str | None = Query(None, max_length=200, description="The address picked from /v1/autocomplete"),
    session: str | None = Query(None, max_length=64, description="The autocomplete session ID, if any"),
    count: int = Query(3, ge=1, le=10, description="How many restaurants"),
    within_km: float = Query(1.0, gt=0, le=10, description="Only restaurants within this distance"),
    cuisine: str | None = Query(None, max_length=60, examples=["ramen"]),
    price: str | None = Query(None, description="$, $$, $-$$$ or 1,2", examples=["$$"]),
    min_rating: str | None = Query(None, description="1.0 to 5.0", examples=["4.0"]),
    sort: Literal["distance", "rating"] = Query("distance", description="Order of the results"),
    lat: float | None = Query(None, ge=-90, le=90, description="Start from this point (a map pin or your location)"),
    lng: float | None = Query(None, ge=-180, le=180),
    market: Market | None = Query(None, description="us or tw; detected from the address if omitted"),
    format: Literal["json", "html"] = "json",
):
    if (lat is None) != (lng is None):
        raise HTTPException(422, "Give both lat and lng.")
    if not address.strip() and not place_id and lat is None:
        raise HTTPException(422, "Give an address or cross streets, a place_id from autocomplete, or lat and lng.")
    table = await run(
        request.app.state.service.nearby(
            address.strip(), market, count, within_km, (cuisine or "").strip() or None, parse_price(price),
            parse_min_rating(min_rating), sort, place_id or None, session or None, lat, lng,
        )
    )
    return respond(table, format)


@app.get("/v1/locate", summary="Coordinates for an address or cross streets (used by the map picker)")
async def locate(
    request: Request,
    address: str = Query("", max_length=200),
    place_id: str | None = Query(None, max_length=200),
    session: str | None = Query(None, max_length=64),
):
    if not address.strip() and not place_id:
        raise HTTPException(422, "Give an address or a place_id.")
    found = await run(request.app.state.service.locate_point(address.strip(), place_id or None, session or None))
    if not found:
        raise HTTPException(404, f"Couldn't find '{address}'.")
    return {"lat": found[0], "lng": found[1], "label": found[2]}

import os
from datetime import datetime, timedelta, timezone

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def google_place(pid, name, rating, count, price="PRICE_LEVEL_MODERATE", reviews=(), address="1 Main St, Seattle, WA"):
    return {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": address,
        "rating": rating,
        "userRatingCount": count,
        "priceLevel": price,
        "googleMapsUri": f"https://maps.google.com/?cid={pid}",
        "location": {"latitude": 47.6, "longitude": -122.3},
        "primaryTypeDisplayName": {"text": "Ramen Restaurant"},
        "reviews": [
            {"name": f"places/{pid}/reviews/{i}", "rating": r, "originalText": {"text": t, "languageCode": "en"}, "publishTime": iso(d)}
            for i, (r, t, d) in enumerate(reviews)
        ],
    }


GOOGLE_US = {
    "places": [
        google_place("g1", "Noodle House", 4.6, 1800, reviews=[
            (5, "You have to try the spicy miso ramen. Service was quick.", 10),
            (4, "The spicy miso ramen was amazing, gyoza were fine.", 30),
            (5, "Ordered the pork buns and loved them.", 200),
        ]),
        google_place("g2", "Tiny Gem", 5.0, 4, reviews=[(5, "Nice.", 5)]),
        google_place("g3", "Big Bowl", 4.3, 900, price="PRICE_LEVEL_INEXPENSIVE"),
    ]
}

YELP_SEARCH = {
    "businesses": [
        {
            "id": "y1", "name": "Noodle House", "rating": 4.5, "review_count": 950, "price": "$$",
            "url": "https://www.yelp.com/biz/noodle-house?adjust=1",
            "location": {"display_address": ["1 Main St", "Seattle, WA"]},
            "coordinates": {"latitude": 47.6, "longitude": -122.3},
            "categories": [{"title": "Ramen"}],
        }
    ]
}


def yelp_reviews():
    t = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    return {"reviews": [{"id": "yr1", "rating": 5, "text": "Get the spicy miso ramen, trust me.", "time_created": t}]}


@pytest.fixture
def make_client(monkeypatch):
    def _make(yelp_key="test-yelp", michelin_us=os.path.join(FIXTURES, "michelin_us_test.csv"),
              michelin_tw=os.path.join(FIXTURES, "michelin_tw_test.csv"), service_key="", maps_key="",
              ta_key="", ta_markets="us,tw", ta_limit=100):
        monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-google")
        monkeypatch.setenv("TRIPADVISOR_API_KEY", ta_key)
        monkeypatch.setenv("TRIPADVISOR_MARKETS", ta_markets)
        monkeypatch.setenv("TRIPADVISOR_DAILY_ENTITY_LIMIT", str(ta_limit))
        monkeypatch.setenv("GOOGLE_MAPS_BROWSER_KEY", maps_key)
        monkeypatch.setenv("YELP_API_KEY", yelp_key)
        monkeypatch.setenv("MICHELIN_US_CSV_PATH", michelin_us)
        monkeypatch.setenv("MICHELIN_TW_CSV_PATH", michelin_tw)
        monkeypatch.setenv("STORE", "memory")
        monkeypatch.setenv("SERVICE_API_KEY", service_key)
        from app.config import get_settings
        get_settings.cache_clear()
        from app.main import app
        return TestClient(app)

    yield _make
    from app.config import get_settings
    get_settings.cache_clear()


@pytest.fixture
def mock_apis():
    with respx.mock(assert_all_called=False) as router:
        router.post("https://places.googleapis.com/v1/places:searchText").mock(return_value=Response(200, json=GOOGLE_US))
        router.get("https://api.yelp.com/v3/businesses/search").mock(
            side_effect=lambda req: Response(200, json=YELP_SEARCH if "Noodle" in req.url.params["term"] else {"businesses": []})
        )
        router.get(url__regex=r"https://api\.yelp\.com/v3/businesses/.+/reviews").mock(return_value=Response(200, json=yelp_reviews()))
        router.post("https://places.googleapis.com/v1/places:autocomplete").mock(return_value=Response(200, json=AUTOCOMPLETE))
        router.get(url__regex=r"https://places\.googleapis\.com/v1/places/[^:]+$").mock(
            side_effect=lambda req: Response(200, json=GOOGLE_US["places"][0]) if req.url.path.endswith("/g1")
            else Response(404, json={"error": {"code": 404}})
        )
        # Tripadvisor / Terra: 5 nearby, 6 details, 7 reviews, 8 name search
        router.get(f"{TA}/locations/nearby").mock(side_effect=_ta_nearby)
        router.get(url__regex=rf"{TA}/locations/\d+(\?|$)").mock(side_effect=_ta_details)
        router.get(url__regex=rf"{TA}/locations/\d+/reviews").mock(return_value=Response(200, json=TA_REVIEWS()))
        router.get(f"{TA}/locations/search").mock(side_effect=_ta_search)
        yield router


TA = "https://terra.tripadvisor.com/api"


def ta_location(loc_id, names, distance_km=None, rating=4.5, count=1320, lat=None, lng=None):
    loc = {
        "id": loc_id, "geo_id": 60878, "names": [{"value": n, "locale": "en"} for n in names], "addresses": [],
        "traveler_ratings": {"overall": {"rating": rating, "count": count,
                                         "icon_url": "https://static.tacdn.com/img2/ratings/traveler/ss4.5.svg"}},
    }
    if distance_km is not None:  # only nearby results carry a distance
        loc.update(distance_kilometers=distance_km, distance_miles=distance_km * 0.62)
    if lat is not None:
        loc["coordinates"] = {"latitude": lat, "longitude": lng}
    return loc


# Valley Fair mall, Santa Clara: Din Tai Fung is upstairs, and other restaurants are nearer the pin.
DTF_SC = (37.3256, -121.9455)


def _ta_search(req):
    q = req.url.params["query"]
    results = {
        "Noodle House": [ta_location(100, ["Noodle House"], lat=47.6001, lng=-122.3001)],
        "Din Tai Fung": [
            ta_location(501, ["Din Tai Fung"], lat=34.1453, lng=-118.2556, count=4100),   # Glendale branch
            ta_location(500, ["Din Tai Fung"], lat=37.3253, lng=-121.9450, count=2200),   # Santa Clara
        ],
        "Far Away Ramen": [ta_location(600, ["Far Away Ramen"], lat=40.71, lng=-74.0)],
    }.get(q, [])
    return Response(200, json={"data": results[: int(req.url.params.get("size", 20))]})


def _ta_nearby(req):
    # Terra returns everything within the radius; matching happens in our code.
    lat = req.url.params["lat"]
    if lat == "47.6":
        return Response(200, json={"data": [
            ta_location(100, ["Noodle House"], 0.02),
            ta_location(400, ["Corner Coffee"], 0.15),
        ], "pagination": {"page": 1, "size": 3, "total_elements": 2, "total_pages": 1}})
    if lat == str(DTF_SC[0]):
        # The 3 nearest places in the mall, none of them Din Tai Fung.
        return Response(200, json={"data": [ta_location(700 + i, [n], 0.02 + i / 100)
                                            for i, n in enumerate(["Pressed Juicery", "Sushi Bar", "Tea Stop"])]})
    if lat == "25.03":
        # English name only, 10 m away: should match 範例小籠包 by position.
        return Response(200, json={"data": [ta_location(300, ["Example Dumpling Hall"], 0.01)]})
    return Response(200, json={"data": []})


def _ta_details(req):
    loc = int(req.url.path.rsplit("/", 1)[-1])
    return Response(200, json=ta_location(loc, ["Noodle House"], 0))


def TA_REVIEWS():
    return {"data": [{"id": 9001, "rating": 4, "published_date": iso(5), "language": "en",
                      "title": "Solid bowl", "text": "Try the pork buns, then the spicy miso ramen."}],
            "pagination": {"page": 1, "size": 10, "total_elements": 1, "total_pages": 1}}


AUTOCOMPLETE = {
    "suggestions": [
        {"placePrediction": {"placeId": "g1", "text": {"text": "Noodle House, 1 Main St, Seattle, WA"},
                             "structuredFormat": {"mainText": {"text": "Noodle House"}, "secondaryText": {"text": "1 Main St, Seattle, WA"}},
                             "types": ["ramen_restaurant", "food", "point_of_interest"]}},
        {"placePrediction": {"placeId": "h1", "text": {"text": "Noodle Hardware Store"},
                             "structuredFormat": {"mainText": {"text": "Noodle Hardware Store"}},
                             "types": ["hardware_store", "store"]}},
        {"queryPrediction": {"text": {"text": "noodle shops near me"}}},
    ]
}

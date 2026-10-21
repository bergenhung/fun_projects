import json

from httpx import Response

from tests.conftest import google_place


def test_health(make_client):
    with make_client() as c:
        assert c.get("/healthz").json() == {"status": "ok"}


def test_top_us_ranks_and_merges_yelp(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/top", params={"location": "Seattle, WA", "cuisine": "ramen", "price": "$-$$", "limit": 3})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["market"] == "us"
    assert data["sources_used"] == ["google", "yelp", "michelin"]
    names = [row["name"] for row in data["rows"]]
    # A 5.0 from 4 reviews must not outrank 4.6 from 1,800.
    assert names[0] == "Noodle House"
    assert names.index("Tiny Gem") > names.index("Big Bowl")
    top = data["rows"][0]
    assert {s["source"] for s in top["ratings"]} == {"google", "yelp"}
    assert 4.5 <= top["all_time_rating"] <= 4.6
    # 2 Google reviews + 1 Yelp review fall within 90 days; the 200-day-old one doesn't.
    assert top["recent_3_months"]["review_count"] == 3
    assert top["recent_3_months"]["low_confidence"] is True
    assert top["top_dishes"][0] == "spicy miso ramen"
    assert top["michelin"] == "Bib Gourmand (2026)"
    # "Big Bowl" is starred in Chicago, not Seattle, so it must not get the label.
    assert next(r for r in data["rows"] if r["name"] == "Big Bowl")["michelin"] is None
    # Price filter is passed through to Google.
    body = json.loads(mock_apis.calls[0].request.content)
    assert body["priceLevels"] == ["PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE"]
    assert body["languageCode"] == "en"


def test_second_request_is_cached(make_client, mock_apis):
    with make_client() as c:
        c.get("/v1/top", params={"location": "Seattle"})
        calls = len(mock_apis.calls)
        c.get("/v1/top", params={"location": "seattle"})
    assert len(mock_apis.calls) == calls


def test_no_yelp_key_gives_yelp_links(make_client, mock_apis):
    with make_client(yelp_key="") as c:
        data = c.get("/v1/top", params={"location": "Seattle"}).json()
    # Yelp is paid, so it isn't listed as "skipped"; Tripadvisor has no key in this test.
    assert data["sources_used"] == ["google", "michelin"]
    assert data["sources_skipped"] == ["tripadvisor"]
    assert all(len(row["ratings"]) == 1 for row in data["rows"])
    link = data["rows"][0]["links"][0]
    assert link["label"] == "See on Yelp"
    assert link["url"].startswith("https://www.yelp.com/search?find_desc=Noodle+House&find_loc=1+Main+St")
    assert any("See on Yelp" in n for n in data["notes"])
    assert not any("yelp.com/v3" in str(call.request.url) for call in mock_apis.calls)


def test_verify_taiwan_uses_michelin(make_client, mock_apis):
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [
        google_place("t1", "範例小籠包", 4.4, 5200, address="台北市信義區", reviews=[(5, "必點蟹粉小籠包,真的超好吃", 7)]),
    ]}))
    with make_client() as c:
        r = c.get("/v1/verify", params={"name": "範例小籠包", "location": "台北"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["market"] == "tw"
    assert data["sources_used"] == ["google", "michelin"]
    row = data["rows"][0]
    assert row["michelin"] == "Bib Gourmand (2026)"
    assert "蟹粉小籠包" in row["top_dishes"]
    body = json.loads(mock_apis.calls[0].request.content)
    assert body["languageCode"] == "zh-TW"
    # Yelp is never called for Taiwan.
    assert not any("yelp" in str(call.request.url) for call in mock_apis.calls)


def test_verify_not_found(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/verify", params={"name": "Completely Different Place", "location": "Seattle"})
    assert r.status_code == 404


def test_html_table(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/top", params={"location": "Seattle", "format": "html", "min_rating": "", "price": ""})
    assert r.status_code == 200
    assert "<table>" in r.text and "Noodle House" in r.text and "Yelp" in r.text


def test_bad_price(make_client, mock_apis):
    with make_client() as c:
        assert c.get("/v1/top", params={"location": "Seattle", "price": "$$$$$"}).status_code == 422


def test_api_key_required_when_configured(make_client, mock_apis):
    with make_client(service_key="secret") as c:
        assert c.get("/v1/top", params={"location": "Seattle"}).status_code == 401
        assert c.get("/v1/top", params={"location": "Seattle"}, headers={"X-API-Key": "secret"}).status_code == 200
        assert c.get("/healthz").status_code == 200


def test_upstream_error_returns_502(make_client, mock_apis):
    mock_apis.routes[0].mock(return_value=Response(500, text="boom"))
    with make_client() as c:
        assert c.get("/v1/top", params={"location": "Seattle"}).status_code == 502


def test_us_michelin_skipped_when_list_empty(make_client, mock_apis):
    with make_client(michelin_us="data/michelin_us.csv") as c:
        data = c.get("/v1/top", params={"location": "Seattle"}).json()
    assert data["sources_skipped"] == ["tripadvisor", "michelin"]
    assert all(row["michelin"] is None for row in data["rows"])


def test_autocomplete_restaurant_filters_non_food(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/autocomplete", params={"q": "nood", "kind": "restaurant", "session": "abc123"})
    assert r.status_code == 200, r.text
    assert r.json() == [{"place_id": "g1", "main": "Noodle House", "secondary": "1 Main St, Seattle, WA",
                         "text": "Noodle House, 1 Main St, Seattle, WA"}]
    body = json.loads(mock_apis.routes[3].calls[0].request.content)
    assert body["sessionToken"] == "abc123" and body["languageCode"] == "en"
    assert "includedPrimaryTypes" not in body


def test_autocomplete_location_and_chinese(make_client, mock_apis):
    with make_client() as c:
        c.get("/v1/autocomplete", params={"q": "台北", "kind": "location"})
    body = json.loads(mock_apis.routes[3].calls[0].request.content)
    assert body["languageCode"] == "zh-TW"
    assert "locality" in body["includedPrimaryTypes"]


def test_autocomplete_cached_and_validated(make_client, mock_apis):
    with make_client() as c:
        c.get("/v1/autocomplete", params={"q": "nood"})
        c.get("/v1/autocomplete", params={"q": "NOOD "})
        assert c.get("/v1/autocomplete", params={"q": "n"}).status_code == 422
    assert len(mock_apis.routes[3].calls) == 1


def test_verify_by_place_id(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/verify", params={"place_id": "g1", "session": "abc123", "name": "Noodle House"})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["name"] == "Noodle House" and row["place_id"] == "g1"
    assert row["lat"] == 47.6 and row["lng"] == -122.3
    details = mock_apis.routes[4].calls[0].request
    assert details.url.params["sessionToken"] == "abc123"
    assert "places." not in details.headers["X-Goog-FieldMask"]
    # Text search is skipped entirely when a place ID is given.
    assert not mock_apis.routes[0].called


def test_verify_bad_place_id_404(make_client, mock_apis):
    with make_client() as c:
        assert c.get("/v1/verify", params={"place_id": "nope"}).status_code == 404


def test_verify_needs_name_and_location_without_place_id(make_client, mock_apis):
    with make_client() as c:
        assert c.get("/v1/verify", params={"name": "Noodle House"}).status_code == 422


def test_map_shown_only_with_browser_key(make_client, mock_apis):
    params = {"location": "Seattle", "format": "html"}
    with make_client() as c:
        html = c.get("/v1/top", params=params).text
    assert 'id="map"' not in html and "GOOGLE_MAPS_BROWSER_KEY" in html
    with make_client(maps_key="browser-key") as c:
        html = c.get("/v1/top", params={**params, "limit": 4}).text
    assert 'id="map"' in html and "key=browser-key" in html and "data-idx=" in html
    assert '"lat": 47.6' in html


def test_search_page_has_autocomplete(make_client):
    with make_client() as c:
        html = c.get("/").text
    assert "/v1/autocomplete" in html and 'name="place_id"' in html


def test_tripadvisor_us(make_client, mock_apis):
    with make_client(yelp_key="", ta_key="ta-key") as c:
        data = c.get("/v1/top", params={"location": "Seattle, WA", "limit": 3}).json()
        html = c.get("/v1/top", params={"location": "Seattle, WA", "limit": 3, "format": "html"}).text
    assert data["sources_used"] == ["google", "tripadvisor", "michelin"]
    assert data["sources_skipped"] == []
    rows = {r["name"]: r for r in data["rows"]}
    ta = next(s for s in rows["Noodle House"]["ratings"] if s["source"] == "tripadvisor")
    assert ta["rating"] == 4.5 and ta["review_count"] == 1320
    assert ta["rating_image_url"].endswith("ss4.5.svg")
    assert ta["url"] == "https://www.tripadvisor.com/Restaurant_Review-g60878-d100"
    # Big Bowl sits next to Noodle House, but a same-script name mismatch is never matched by position.
    assert [s["source"] for s in rows["Big Bowl"]["ratings"]] == ["google"]
    # 2 recent Google reviews + 1 recent Tripadvisor review.
    assert rows["Noodle House"]["recent_3_months"]["review_count"] == 3
    assert "pork buns" in rows["Noodle House"]["top_dishes"]
    assert all(r["links"][0]["label"] == "See on Yelp" for r in data["rows"])
    # Display rules: bubble image, link to the listing, credit.
    assert 'class="bubbles"' in html and "d100" in html and "© Tripadvisor" in html
    assert ">Tripadvisor</th>" in html
    req = mock_apis.routes[5].calls[0].request
    assert req.headers["X-API-Key"] == "ta-key" and "key" not in req.url.params
    p = req.url.params
    assert (p["lat"], p["lon"], p["unit"], p["category"], p["size"]) == ("47.6", "-122.3", "KM", "RESTAURANT", "3")
    assert p["version"] == "1" and p.get_list("locale") == ["en"]
    # The nearby result already had the rating, so no separate details call.
    assert not mock_apis.routes[6].called


def test_tripadvisor_ids_remembered(make_client, mock_apis):
    with make_client(yelp_key="", ta_key="ta-key") as c:
        c.get("/v1/top", params={"location": "Seattle"})
        searches = len(mock_apis.routes[5].calls)
        # A different search (not cached) that returns the same restaurants.
        c.get("/v1/top", params={"location": "Seattle", "cuisine": "ramen"})
    assert searches == 3
    assert len(mock_apis.routes[5].calls) == searches   # IDs and no-matches remembered
    assert len(mock_apis.routes[6].calls) == 1          # the remembered match needs a details call


def test_tripadvisor_only_for_shown_rows(make_client, mock_apis):
    with make_client(yelp_key="", ta_key="ta-key") as c:
        c.get("/v1/top", params={"location": "Seattle", "limit": 1})
    assert len(mock_apis.routes[5].calls) == 1


def test_tripadvisor_daily_limit(make_client, mock_apis):
    # A nearby search may bill up to 3 items, so a limit of 4 allows one search and one more item.
    with make_client(yelp_key="", ta_key="ta-key", ta_limit=4) as c:
        r = c.get("/v1/top", params={"location": "Seattle"})
    assert r.status_code == 200
    assert len(mock_apis.routes[5].calls) == 1
    assert all(len(row["ratings"]) >= 1 for row in r.json()["rows"])


def test_tripadvisor_429_pauses_for_the_day(make_client, mock_apis):
    mock_apis.routes[5].mock(return_value=Response(429, json={"title": "Too Many Requests"}))
    with make_client(yelp_key="", ta_key="ta-key") as c:
        assert c.get("/v1/top", params={"location": "Seattle"}).status_code == 200
        c.get("/v1/top", params={"location": "Seattle", "cuisine": "ramen"})
    assert len(mock_apis.routes[5].calls) == 1


def test_tripadvisor_taiwan_matches_by_position(make_client, mock_apis):
    place = google_place("t1", "範例小籠包", 4.4, 5200, address="台北市信義區")
    place["location"] = {"latitude": 25.03, "longitude": 121.56}
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [place]}))
    with make_client(ta_key="ta-key") as c:
        data = c.get("/v1/verify", params={"name": "範例小籠包", "location": "台北"}).json()
    assert data["sources_used"] == ["google", "tripadvisor", "michelin"]
    assert [s["source"] for s in data["rows"][0]["ratings"]] == ["google", "tripadvisor"]
    assert data["rows"][0]["links"] == []
    assert mock_apis.routes[5].calls[0].request.url.params.get_list("locale") == ["zh-TW", "en"]
    assert mock_apis.routes[7].calls[0].request.url.params["language"] == "primary"


def test_tripadvisor_can_be_limited_to_us(make_client, mock_apis):
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [
        google_place("t1", "範例小籠包", 4.4, 5200, address="台北市信義區"),
    ]}))
    with make_client(ta_key="ta-key", ta_markets="us") as c:
        data = c.get("/v1/verify", params={"name": "範例小籠包", "location": "台北"}).json()
    assert data["sources_used"] == ["google", "michelin"]
    assert not mock_apis.routes[5].called


def test_tripadvisor_locale_rejected_retries_without(make_client, mock_apis):
    def nearby(req):
        if req.url.params.get_list("locale"):
            return Response(400, json={"title": "Bad locale"})
        return Response(200, json={"data": [__import__("tests.conftest", fromlist=["x"]).ta_location(100, ["Noodle House"], 0.02)]})
    mock_apis.routes[5].mock(side_effect=nearby)
    with make_client(yelp_key="", ta_key="ta-key") as c:
        data = c.get("/v1/top", params={"location": "Seattle", "limit": 1}).json()
    assert "tripadvisor" in [s["source"] for s in data["rows"][0]["ratings"]]


def test_tripadvisor_error_does_not_break_results(make_client, mock_apis):
    mock_apis.routes[5].mock(return_value=Response(500, text="boom"))
    with make_client(ta_key="ta-key") as c:
        r = c.get("/v1/top", params={"location": "Seattle"})
    assert r.status_code == 200
    assert all("tripadvisor" not in [s["source"] for s in row["ratings"]] for row in r.json()["rows"])

import json

from httpx import Response

from tests.conftest import DTF_SC, google_place


def test_health(make_client):
    with make_client() as c:
        assert c.get("/healthz").json() == {"status": "ok"}


def test_nearby_rating_order_and_merges_yelp(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/nearby", params={"address": "Seattle, WA", "cuisine": "ramen", "price": "$-$$",
                                        "count": 3, "sort": "rating"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "nearby" and data["market"] == "us"
    assert data["sources_used"] == ["google", "yelp", "michelin"]
    names = [row["name"] for row in data["rows"]]
    # Highest rated first: a 5.0 from 4 reviews must not outrank 4.6 from 1,800.
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
    big = next(r for r in data["rows"] if r["name"] == "Big Bowl")
    assert big["michelin"] is None
    assert big["links"][0]["label"] == "Check Michelin Guide"
    assert big["links"][0]["url"] == "https://guide.michelin.com/us/en/search?q=Big+Bowl"
    # First call finds the address; the second searches restaurants around it, closest first.
    locate = json.loads(mock_apis.routes[0].calls[0].request.content)
    assert locate == {"textQuery": "Seattle, WA", "pageSize": 1}
    body = json.loads(mock_apis.routes[0].calls[1].request.content)
    assert body["textQuery"] == "ramen restaurant" and body["rankPreference"] == "DISTANCE"
    assert body["locationBias"]["circle"]["radius"] == 1000
    assert body["priceLevels"] == ["PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE"]
    assert body["languageCode"] == "en"


def _spread_places(req):
    """Address lookup -> a point; restaurant search -> places at known distances from it."""
    body = json.loads(req.content)
    if body.get("pageSize") == 1 and "rankPreference" not in body:
        return Response(200, json={"places": [{"location": {"latitude": 37.3256, "longitude": -121.9455},
                                               "formattedAddress": "2855 Stevens Creek Blvd, Santa Clara, CA 95050, USA"}]})
    spots = [("Far Cafe", 0.0090), ("Near Noodles", 0.0010), ("Mid Grill", 0.0040), ("Outside Bistro", 0.0200)]
    places = []
    for i, (name, dlat) in enumerate(spots):
        p = google_place(f"s{i}", name, 4.0 + i / 10, 100 + i)
        p["location"] = {"latitude": 37.3256 + dlat, "longitude": -121.9455}
        places.append(p)
    return Response(200, json={"places": places})


def test_nearby_closest_first_within_radius(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_spread_places)
    with make_client(yelp_key="") as c:
        data = c.get("/v1/nearby", params={"address": "Valley Fair", "count": 5, "within_km": 1.5}).json()
    names = [r["name"] for r in data["rows"]]
    # ~2.2 km away is outside 1.5 km, so only three come back, nearest first.
    assert names == ["Near Noodles", "Mid Grill", "Far Cafe"]
    assert [r["rank"] for r in data["rows"]] == [1, 2, 3]
    assert 0.1 <= data["rows"][0]["distance_km"] <= 0.12
    assert data["center"] == {"lat": 37.3256, "lng": -121.9455, "radius_km": 1.5,
                              "label": "2855 Stevens Creek Blvd, Santa Clara, CA 95050, USA"}


def test_nearby_count_and_html(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_spread_places)
    with make_client(yelp_key="", maps_key="browser-key") as c:
        data = c.get("/v1/nearby", params={"address": "Valley Fair", "count": 2}).json()
        html = c.get("/v1/nearby", params={"address": "Valley Fair", "count": 2, "format": "html"}).text
    assert [r["name"] for r in data["rows"]] == ["Near Noodles", "Mid Grill"]
    assert "2 restaurants near 2855 Stevens Creek Blvd" in html
    assert "<th>Distance</th>" in html and "110 m" in html and "0.1 mi" in html
    assert '"center": {"lat": 37.3256' in html and "google.maps.Circle" in html
    assert "Check Michelin Guide" in html


def test_nearby_nothing_within_radius(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_spread_places)
    with make_client() as c:
        r = c.get("/v1/nearby", params={"address": "Valley Fair", "within_km": 0.05})
    assert r.status_code == 404 and "Try a larger distance" in r.json()["detail"]


def test_nearby_address_from_autocomplete(make_client, mock_apis):
    with make_client() as c:
        data = c.get("/v1/nearby", params={"address": "Noodle House, 1 Main St", "place_id": "g1",
                                           "session": "tok1"}).json()
    details = mock_apis.routes[4].calls[0].request
    assert details.headers["X-Goog-FieldMask"] == "location,formattedAddress"
    assert details.url.params["sessionToken"] == "tok1"
    assert data["center"]["lat"] == 47.6


def test_nearby_needs_an_address(make_client, mock_apis):
    with make_client() as c:
        assert c.get("/v1/nearby", params={"count": 3}).status_code == 422
        assert c.get("/v1/nearby", params={"address": "x", "within_km": 50}).status_code == 422


def test_nearby_address_lookup_cached(make_client, mock_apis):
    with make_client() as c:
        c.get("/v1/nearby", params={"address": "Seattle"})
        c.get("/v1/nearby", params={"address": "Seattle", "cuisine": "ramen"})
    bodies = [json.loads(call.request.content) for call in mock_apis.routes[0].calls]
    assert sum(1 for b in bodies if "rankPreference" not in b) == 1


def test_second_request_is_cached(make_client, mock_apis):
    with make_client() as c:
        c.get("/v1/nearby", params={"address": "Seattle"})
        calls = len(mock_apis.calls)
        c.get("/v1/nearby", params={"address": "seattle"})
    assert len(mock_apis.calls) == calls


def test_no_yelp_key_gives_yelp_links(make_client, mock_apis):
    with make_client(yelp_key="") as c:
        data = c.get("/v1/nearby", params={"address": "Seattle"}).json()
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
    locate, body = (json.loads(c.request.content) for c in mock_apis.routes[0].calls[:2])
    assert locate == {"textQuery": "台北", "pageSize": 1, "regionCode": "TW"}  # the location, on the map
    assert body["languageCode"] == "zh-TW"
    # Yelp is never called for Taiwan.
    assert not any("yelp" in str(call.request.url) for call in mock_apis.calls)


def test_verify_not_found(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/verify", params={"name": "Completely Different Place", "location": "Seattle"})
    assert r.status_code == 404


def test_html_table(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/nearby", params={"address": "Seattle", "format": "html", "min_rating": "", "price": ""})
    assert r.status_code == 200
    assert "<table>" in r.text and "Noodle House" in r.text and "Yelp" in r.text


def test_bad_price(make_client, mock_apis):
    with make_client() as c:
        assert c.get("/v1/nearby", params={"address": "Seattle", "price": "$$$$$"}).status_code == 422


def test_api_key_required_when_configured(make_client, mock_apis):
    with make_client(service_key="secret") as c:
        assert c.get("/v1/nearby", params={"address": "Seattle"}).status_code == 401
        assert c.get("/v1/nearby", params={"address": "Seattle"}, headers={"X-API-Key": "secret"}).status_code == 200
        assert c.get("/healthz").status_code == 200


def test_upstream_error_returns_502(make_client, mock_apis):
    mock_apis.routes[0].mock(return_value=Response(500, text="boom"))
    with make_client() as c:
        assert c.get("/v1/nearby", params={"address": "Seattle"}).status_code == 502


def test_us_michelin_skipped_when_list_empty(make_client, mock_apis):
    with make_client(michelin_us="data/michelin_us.csv") as c:
        data = c.get("/v1/nearby", params={"address": "Seattle"}).json()
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
    params = {"address": "Seattle", "format": "html"}
    with make_client() as c:
        html = c.get("/v1/nearby", params=params).text
    assert 'id="map"' not in html and "GOOGLE_MAPS_BROWSER_KEY" in html
    with make_client(maps_key="browser-key") as c:
        html = c.get("/v1/nearby", params={**params, "count": 4}).text
    assert 'id="map"' in html and "key=browser-key" in html and "data-idx=" in html
    assert '"lat": 47.6' in html


def test_search_page_has_autocomplete(make_client):
    with make_client() as c:
        html = c.get("/").text
    assert "/v1/autocomplete" in html and 'name="place_id"' in html


NEARBY, DETAILS, REVIEWS, SEARCH = 5, 6, 7, 8


def test_tripadvisor_us(make_client, mock_apis):
    with make_client(yelp_key="", ta_key="ta-key") as c:
        data = c.get("/v1/nearby", params={"address": "Seattle, WA", "count": 3}).json()
        html = c.get("/v1/nearby", params={"address": "Seattle, WA", "count": 3, "format": "html"}).text
    assert data["sources_used"] == ["google", "tripadvisor", "michelin"]
    assert data["sources_skipped"] == []
    rows = {r["name"]: r for r in data["rows"]}
    ta = next(s for s in rows["Noodle House"]["ratings"] if s["source"] == "tripadvisor")
    assert ta["rating"] == 4.5 and ta["review_count"] == 1320
    assert ta["rating_image_url"].endswith("ss4.5.svg")
    assert ta["url"] == "https://www.tripadvisor.com/Restaurant_Review-g60878-d100"
    assert rows["Noodle House"]["source_status"]["tripadvisor"] == "matched"
    # Big Bowl sits next to Noodle House, but a same-script name mismatch is never matched by position.
    assert [s["source"] for s in rows["Big Bowl"]["ratings"]] == ["google"]
    assert rows["Big Bowl"]["source_status"]["tripadvisor"] == "no_match"
    # 2 recent Google reviews + 1 recent Tripadvisor review.
    assert rows["Noodle House"]["recent_3_months"]["review_count"] == 3
    assert "pork buns" in rows["Noodle House"]["top_dishes"]
    assert all(any(l["label"] == "See on Yelp" for l in r["links"]) for r in data["rows"])
    # Display rules: bubble image, link to the listing, credit.
    assert 'class="bubbles"' in html and "d100" in html and "© Tripadvisor" in html
    assert ">Tripadvisor</th>" in html
    req = mock_apis.routes[SEARCH].calls[0].request
    assert req.headers["X-API-Key"] == "ta-key" and "key" not in req.url.params
    p = req.url.params
    assert (p["query"], p["category"], p["country_code"], p["size"]) == ("Noodle House", "RESTAURANT", "US", "3")
    assert p["version"] == "1" and p.get_list("locale") == ["en"]
    # Search results already carry the rating, so no separate details call.
    assert not mock_apis.routes[DETAILS].called


def test_tripadvisor_found_by_name_inside_a_mall(make_client, mock_apis):
    """Din Tai Fung, Santa Clara: other restaurants are nearer Google's pin, and another
    Din Tai Fung branch exists in another city. The right branch must be picked."""
    place = google_place("dtf-sc", "Din Tai Fung", 4.6, 5000,
                         address="2855 Stevens Creek Blvd #2477, Santa Clara, CA 95050, USA")
    place["location"] = {"latitude": DTF_SC[0], "longitude": DTF_SC[1]}
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [place]}))
    with make_client(yelp_key="", ta_key="ta-key") as c:
        data = c.get("/v1/verify", params={"name": "Din Tai Fung", "location": "Santa Clara"}).json()
    row = data["rows"][0]
    ta = next(s for s in row["ratings"] if s["source"] == "tripadvisor")
    assert ta["source_id"] == "500" and ta["review_count"] == 2200
    assert mock_apis.routes[SEARCH].calls[0].request.url.params["postal_code"] == "95050"
    assert not mock_apis.routes[NEARBY].called


def test_tripadvisor_other_branch_only_is_not_a_match(make_client, mock_apis):
    place = google_place("far", "Far Away Ramen", 4.2, 300, address="9 Elm St, Seattle, WA 98101, USA")
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [place]}))
    with make_client(yelp_key="", ta_key="ta-key") as c:
        data = c.get("/v1/verify", params={"name": "Far Away Ramen", "location": "Seattle"}).json()
        html = c.get("/v1/verify", params={"name": "Far Away Ramen", "location": "Seattle", "format": "html"}).text
    assert data["rows"][0]["source_status"]["tripadvisor"] == "no_match"
    assert mock_apis.routes[NEARBY].called  # fell back to nearby, which found nothing either
    assert "not found" in html


def test_tripadvisor_ids_remembered(make_client, mock_apis):
    with make_client(yelp_key="", ta_key="ta-key") as c:
        c.get("/v1/nearby", params={"address": "Seattle"})
        searches = len(mock_apis.routes[SEARCH].calls) + len(mock_apis.routes[NEARBY].calls)
        # A different search (not cached) that returns the same restaurants.
        c.get("/v1/nearby", params={"address": "Seattle", "cuisine": "ramen"})
    assert len(mock_apis.routes[SEARCH].calls) == 3
    assert len(mock_apis.routes[SEARCH].calls) + len(mock_apis.routes[NEARBY].calls) == searches
    assert len(mock_apis.routes[DETAILS].calls) == 1   # the remembered match needs a details call


def test_tripadvisor_only_for_shown_rows(make_client, mock_apis):
    with make_client(yelp_key="", ta_key="ta-key") as c:
        c.get("/v1/nearby", params={"address": "Seattle", "count": 1})
    assert len(mock_apis.routes[SEARCH].calls) == 1


def test_tripadvisor_daily_limit(make_client, mock_apis):
    # A search may bill up to 3 items, so a limit of 4 allows one search and one more item.
    with make_client(yelp_key="", ta_key="ta-key", ta_limit=4) as c:
        r = c.get("/v1/nearby", params={"address": "Seattle"})
        html = c.get("/v1/nearby", params={"address": "Seattle", "format": "html", "cuisine": "x"}).text
    assert r.status_code == 200
    assert len(mock_apis.routes[SEARCH].calls) == 1
    statuses = [row["source_status"]["tripadvisor"] for row in r.json()["rows"]]
    assert statuses.count("limit") == 2
    assert "daily limit" in html


def test_tripadvisor_429_pauses_for_the_day(make_client, mock_apis):
    mock_apis.routes[SEARCH].mock(return_value=Response(429, json={"title": "Too Many Requests"}))
    with make_client(yelp_key="", ta_key="ta-key") as c:
        assert c.get("/v1/nearby", params={"address": "Seattle"}).status_code == 200
        c.get("/v1/nearby", params={"address": "Seattle", "cuisine": "ramen"})
    assert len(mock_apis.routes[SEARCH].calls) == 1


def test_tripadvisor_taiwan_matches_by_position(make_client, mock_apis):
    place = google_place("t1", "範例小籠包", 4.4, 5200, address="110台北市信義區松高路19號")
    place["location"] = {"latitude": 25.03, "longitude": 121.56}
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [place]}))
    with make_client(ta_key="ta-key") as c:
        data = c.get("/v1/verify", params={"name": "範例小籠包", "location": "台北"}).json()
    assert data["sources_used"] == ["google", "tripadvisor", "michelin"]
    assert [s["source"] for s in data["rows"][0]["ratings"]] == ["google", "tripadvisor"]
    assert data["rows"][0]["links"] == []
    search = mock_apis.routes[SEARCH].calls[0].request.url.params
    assert (search["country_code"], search["postal_code"]) == ("TW", "110")
    assert mock_apis.routes[NEARBY].calls[0].request.url.params.get_list("locale") == ["zh-TW", "en"]
    assert mock_apis.routes[REVIEWS].calls[0].request.url.params["language"] == "primary"


def test_tripadvisor_can_be_limited_to_us(make_client, mock_apis):
    mock_apis.routes[0].mock(return_value=Response(200, json={"places": [
        google_place("t1", "範例小籠包", 4.4, 5200, address="台北市信義區"),
    ]}))
    with make_client(ta_key="ta-key", ta_markets="us") as c:
        data = c.get("/v1/verify", params={"name": "範例小籠包", "location": "台北"}).json()
    assert data["sources_used"] == ["google", "michelin"]
    assert not mock_apis.routes[SEARCH].called and not mock_apis.routes[NEARBY].called


def test_tripadvisor_locale_rejected_retries_without(make_client, mock_apis):
    from tests.conftest import ta_location

    def search(req):
        if req.url.params.get_list("locale"):
            return Response(400, json={"title": "Bad locale"})
        return Response(200, json={"data": [ta_location(100, ["Noodle House"], lat=47.6, lng=-122.3)]})
    mock_apis.routes[SEARCH].mock(side_effect=search)
    with make_client(yelp_key="", ta_key="ta-key") as c:
        data = c.get("/v1/nearby", params={"address": "Seattle", "count": 1}).json()
    assert "tripadvisor" in [s["source"] for s in data["rows"][0]["ratings"]]


def test_tripadvisor_error_does_not_break_results(make_client, mock_apis):
    mock_apis.routes[SEARCH].mock(return_value=Response(500, text="boom"))
    mock_apis.routes[NEARBY].mock(return_value=Response(500, text="boom"))
    with make_client(ta_key="ta-key") as c:
        r = c.get("/v1/nearby", params={"address": "Seattle"})
        html = c.get("/v1/nearby", params={"address": "Seattle", "format": "html", "cuisine": "x"}).text
    assert r.status_code == 200
    assert all(row["source_status"]["tripadvisor"] == "error" for row in r.json()["rows"])
    assert "couldn&#x27;t check" in html or "couldn't check" in html


def test_verify_english_name_in_taiwan(make_client, mock_apis):
    """Typing 'Din Tai Fung' in Taipei: Google answers '鼎泰豐' in Chinese, so match via English."""
    zh = google_place("dtf", "鼎泰豐 信義店", 4.5, 30000, address="台北市信義區", reviews=[(5, "必點小籠包,超好吃", 3)])
    en = google_place("dtf", "Din Tai Fung Xinyi", 4.5, 30000, address="Xinyi District, Taipei")

    def search(req):
        lang = json.loads(req.content).get("languageCode", "zh-TW")
        return Response(200, json={"places": [zh] if lang == "zh-TW" else [en]})
    mock_apis.routes[0].mock(side_effect=search)
    with make_client() as c:
        r = c.get("/v1/verify", params={"name": "Din Tai Fung", "location": "Taipei"})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["name"] == "鼎泰豐 信義店" and row["place_id"] == "dtf"
    assert len(mock_apis.routes[0].calls) == 3  # location, then the search in each language


def test_verify_wrong_name_still_404_in_taiwan(make_client, mock_apis):
    zh = google_place("x", "某某麵店", 4.0, 100, address="台北市")
    en = google_place("x", "Some Noodle Shop", 4.0, 100, address="Taipei")
    mock_apis.routes[0].mock(side_effect=lambda req: Response(200, json={
        "places": [zh] if json.loads(req.content)["languageCode"] == "zh-TW" else [en]}))
    with make_client() as c:
        r = c.get("/v1/verify", params={"name": "Din Tai Fung", "location": "Taipei"})
    assert r.status_code == 404 and "suggestions" in r.json()["detail"]


def test_directions_link_on_every_row(make_client, mock_apis):
    from urllib.parse import parse_qs, urlparse
    with make_client(maps_key="browser-key") as c:
        data = c.get("/v1/nearby", params={"address": "Seattle"}).json()
        html = c.get("/v1/nearby", params={"address": "Seattle", "format": "html"}).text
    for row in data["rows"]:
        q = parse_qs(urlparse(row["directions_url"]).query)
        assert row["directions_url"].startswith("https://www.google.com/maps/dir/?api=1")
        assert q["destination_place_id"] == [row["place_id"]]
        assert q["destination"][0].startswith(row["name"])
    assert html.count(">Directions<") == len(data["rows"])
    assert '"directions": "https://www.google.com/maps/dir/' in html
    assert "zoomControl: true" in html and "Show all" in html


def test_not_found_lists_what_google_returned(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/verify", params={"name": "Din Tai Fung", "location": "Santa Clara, CA"})
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "Google returned: Noodle House (1 Main St, Seattle, WA)" in detail


def test_place_id_rejected_with_session_retries_without(make_client, mock_apis):
    def details(req):
        if "sessionToken" in req.url.params:
            return Response(400, json={"error": {"message": "Invalid session token"}})
        return Response(200, json=__import__("tests.conftest", fromlist=["x"]).GOOGLE_US["places"][0])
    mock_apis.routes[4].mock(side_effect=details)
    with make_client() as c:
        r = c.get("/v1/verify", params={"place_id": "g1", "session": "bad", "name": "Noodle House"})
    assert r.status_code == 200, r.text
    assert len(mock_apis.routes[4].calls) == 2


def test_place_id_not_found_falls_back_to_name(make_client, mock_apis):
    with make_client() as c:
        r = c.get("/v1/verify", params={"place_id": "nope", "name": "Noodle House", "location": "Seattle"})
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0]["name"] == "Noodle House"


def _taipei_or_seattle(req):
    """Address lookups: Taipei or Seattle. Restaurant searches: a Taipei branch."""
    body = json.loads(req.content)
    if body.get("pageSize") == 1 and "includedType" not in body:
        taipei = "Taipei" in body["textQuery"]
        loc = {"latitude": 25.04, "longitude": 121.56} if taipei else {"latitude": 47.6, "longitude": -122.3}
        return Response(200, json={"places": [{"location": loc, "formattedAddress": "Taipei City, Taiwan" if taipei else "Seattle, WA, USA"}]})
    branch = google_place("tp1", "Noodle House 台北店", 4.3, 800, address="110台北市信義區松高路19號")
    branch["location"] = {"latitude": 25.039, "longitude": 121.567}
    return Response(200, json={"places": [branch]})


def test_picked_suggestion_far_from_location_searches_there(make_client, mock_apis):
    """Picked a suggestion for the Seattle branch, but Location says Taipei: use the Taipei branch."""
    mock_apis.routes[0].mock(side_effect=_taipei_or_seattle)
    with make_client(yelp_key="") as c:
        data = c.get("/v1/verify", params={"name": "Noodle House", "location": "Taipei, Taiwan",
                                           "place_id": "g1", "session": "tok"}).json()
    row = data["rows"][0]
    assert row["place_id"] == "tp1" and data["market"] == "tw"
    assert row["address"].startswith("110台北市")


def test_picked_suggestion_near_location_is_kept(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_taipei_or_seattle)
    with make_client(yelp_key="") as c:
        data = c.get("/v1/verify", params={"name": "Noodle House", "location": "Seattle", "place_id": "g1"}).json()
    assert data["rows"][0]["place_id"] == "g1" and data["market"] == "us"


def test_market_follows_the_restaurant_address(make_client, mock_apis):
    """A US restaurant is a US lookup even if the typed location sounded Taiwanese."""
    us = google_place("dtf-sc", "鼎泰豐 西田谷購物中心店", 4.4, 4926, address="2855 Stevens Creek Blvd #1259, Santa Clara, CA 95050美國")
    mock_apis.routes[4].mock(return_value=Response(200, json=us))
    with make_client(yelp_key="") as c:
        data = c.get("/v1/verify", params={"name": "Din Tai Fung", "place_id": "dtf-sc"}).json()
    assert data["market"] == "us"
    # Re-fetched in English for the US market.
    langs = [call.request.url.params["languageCode"] for call in mock_apis.routes[4].calls]
    assert langs[-1] == "en"


def test_autocomplete_favours_the_location_field(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_taipei_or_seattle)
    with make_client() as c:
        c.get("/v1/autocomplete", params={"q": "din tai", "kind": "restaurant", "near": "Taipei, Taiwan"})
        c.get("/v1/autocomplete", params={"q": "din tai", "kind": "restaurant"})
    with_bias, without = (json.loads(call.request.content) for call in mock_apis.routes[3].calls)
    assert with_bias["locationBias"]["circle"]["center"] == {"latitude": 25.04, "longitude": 121.56}
    assert "locationBias" not in without  # different cache entry, no bias


def _xinyi_branches(req):
    """Location lookup: Xinyi District. Restaurant search: two branches, the farther one first."""
    body = json.loads(req.content)
    if body.get("pageSize") == 1 and "includedType" not in body:
        return Response(200, json={"places": [{"location": {"latitude": 25.0330, "longitude": 121.5654},
                                               "formattedAddress": "Xinyi District, Taipei City, Taiwan"}]})
    far = google_place("nanxi", "Din Tai Fung Nanxi", 4.5, 9000, address="104台北市中山區南京西路12號")
    far["location"] = {"latitude": 25.0522, "longitude": 121.5200}
    near = google_place("a4", "Din Tai Fung A4", 4.6, 12000, address="110台北市信義區松壽路19號")
    near["location"] = {"latitude": 25.0365, "longitude": 121.5665}
    other = google_place("x", "Bubble Tea Bar", 4.1, 300, address="110台北市信義區")
    return Response(200, json={"places": [far, other, near]})


def test_verify_picks_branch_closest_to_location(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_xinyi_branches)
    with make_client() as c:
        data = c.get("/v1/verify", params={"name": "Din Tai Fung", "location": "Xinyi District, Taipei"}).json()
        html = c.get("/v1/verify", params={"name": "Din Tai Fung", "location": "Xinyi District, Taipei",
                                           "format": "html"}).text
    assert data["rows"][0]["place_id"] == "a4"
    alts = data["alternatives"]
    assert [a["place_id"] for a in alts] == ["nanxi"] and 5 < alts[0]["distance_km"] < 6
    search = json.loads(mock_apis.routes[0].calls[1].request.content)
    assert search["rankPreference"] == "DISTANCE"
    assert search["locationBias"]["circle"]["center"] == {"latitude": 25.033, "longitude": 121.5654}
    # The other branch is one click away, keeping the same name and location.
    assert "1 other branch" in html and "place_id=nanxi" in html and "Din+Tai+Fung+Nanxi" not in html
    assert "name=Din+Tai+Fung&amp;location=Xinyi+District%2C+Taipei" in html


def test_verify_by_place_id_has_no_alternatives(make_client, mock_apis):
    with make_client() as c:
        data = c.get("/v1/verify", params={"place_id": "g1", "name": "Noodle House"}).json()
    assert data["alternatives"] == []


def test_location_field_suggests_any_place(make_client):
    with make_client() as c:
        html = c.get("/").text
    assert 'attach(vLoc, "address"' in html and "street or landmark" in html


def _places_with_hours(req):
    body = json.loads(req.content)
    if body.get("pageSize") == 1 and "includedType" not in body:
        return Response(200, json={"places": [{"location": {"latitude": 37.786, "longitude": -122.393},
                                               "formattedAddress": "330 1st St, San Francisco, CA 94105, USA"}]})
    open_all_day = google_place("fire", "Fireside", 4.2, 466, address="330 1st St, San Francisco, CA 94105, USA")
    open_all_day.update(location={"latitude": 37.7864, "longitude": -122.393},
                        regularOpeningHours={"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}],
                                             "weekdayDescriptions": [f"{d}: Open 24 hours" for d in
                                                                     ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]]},
                        utcOffsetMinutes=-420, businessStatus="OPERATIONAL",
                        priceRange={"startPrice": {"currencyCode": "USD", "units": "20"},
                                    "endPrice": {"currencyCode": "USD", "units": "30"}})
    gone = google_place("gone", "Old Diner", 4.9, 50, address="1 1st St, San Francisco, CA 94105, USA")
    gone.update(location={"latitude": 37.7861, "longitude": -122.393}, businessStatus="CLOSED_PERMANENTLY")
    return Response(200, json={"places": [gone, open_all_day]})


def test_nearby_hours_price_and_closed_places(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_places_with_hours)
    with make_client(yelp_key="", maps_key="k") as c:
        data = c.get("/v1/nearby", params={"address": "330 1st St, San Francisco"}).json()
        html = c.get("/v1/nearby", params={"address": "330 1st St, San Francisco", "format": "html"}).text
    assert [r["name"] for r in data["rows"]] == ["Fireside"]  # the permanently closed one is left out
    row = data["rows"][0]
    assert row["price_range"] == "$20–30" and row["hours"]["open_now"] is True
    assert row["hours"]["today"] == "Open 24 hours"
    assert "($20–30 per person)" in html and ">Open now<" in html and "All hours" in html
    assert '"status": "Open now · today Open 24 hours"' in html
    fields = mock_apis.routes[0].calls[1].request.headers["X-Goog-FieldMask"]
    assert all(f in fields for f in ("regularOpeningHours", "utcOffsetMinutes", "priceRange", "businessStatus"))


GEOCODE = "https://maps.googleapis.com/maps/api/geocode/json"


def _geocode_ok(req):
    p = req.url.params
    if "latlng" in p:
        return Response(200, json={"status": "OK", "results": [{"formatted_address": "No. 7, Section 5, Xinyi Rd, Taipei City, Taiwan 110"
                                                                  if p["latlng"].startswith("25.") else "330 1st St, San Francisco, CA 94105, USA"}]})
    return Response(200, json={"status": "OK", "results": [{
        "formatted_address": "1st St & Mission St, San Francisco, CA 94105, USA",
        "geometry": {"location": {"lat": 37.7897, "lng": -122.3972}}, "types": ["intersection"]}]})


def _sf_or_taipei(req):
    """Restaurant searches near San Francisco or Taipei, depending on where the search is centred."""
    body = json.loads(req.content)
    center = (body.get("locationBias") or {}).get("circle", {}).get("center", {})
    return (_xinyi_branches if center.get("latitude", 0) < 30 else _places_with_hours)(req)


def test_nearby_from_cross_streets(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_sf_or_taipei)
    geo = mock_apis.get(GEOCODE).mock(side_effect=_geocode_ok)
    with make_client(yelp_key="") as c:
        data = c.get("/v1/nearby", params={"address": "1st St & Mission St, San Francisco"}).json()
    assert data["center"]["label"] == "1st St & Mission St, San Francisco, CA 94105, USA"
    assert (data["center"]["lat"], data["center"]["lng"]) == (37.7897, -122.3972)
    assert geo.calls[0].request.url.params["address"] == "1st St & Mission St, San Francisco"
    # The intersection came from geocoding, so place search was only used for restaurants.
    assert all("rankPreference" in json.loads(c.request.content) for c in mock_apis.routes[0].calls)


def test_cross_streets_fall_back_when_geocoding_not_enabled(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_sf_or_taipei)
    mock_apis.get(GEOCODE).mock(return_value=Response(200, json={
        "status": "REQUEST_DENIED", "error_message": "This API project is not authorized to use this API."}))
    with make_client(yelp_key="") as c:
        r = c.get("/v1/nearby", params={"address": "1st St & Mission St, San Francisco"})
    assert r.status_code == 200
    first = json.loads(mock_apis.routes[0].calls[0].request.content)
    assert first["textQuery"] == "1st St & Mission St, San Francisco" and first["pageSize"] == 1


def test_nearby_from_a_pin(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_sf_or_taipei)
    mock_apis.get(GEOCODE).mock(side_effect=_geocode_ok)
    with make_client(yelp_key="") as c:
        data = c.get("/v1/nearby", params={"lat": 37.786, "lng": -122.393}).json()
        tw = c.get("/v1/nearby", params={"lat": 25.0330, "lng": 121.5654}).json()
    assert data["center"]["label"] == "330 1st St, San Francisco, CA 94105, USA" and data["market"] == "us"
    assert tw["market"] == "tw" and "Taipei" in tw["center"]["label"]
    # No address lookup: the first Google call is the restaurant search around the pin.
    body = json.loads(mock_apis.routes[0].calls[0].request.content)
    assert body["locationBias"]["circle"]["center"] == {"latitude": 37.786, "longitude": -122.393}


def test_pin_without_reverse_geocoding_still_works(make_client, mock_apis):
    mock_apis.routes[0].mock(side_effect=_sf_or_taipei)
    mock_apis.get(GEOCODE).mock(return_value=Response(200, json={"status": "REQUEST_DENIED"}))
    with make_client(yelp_key="") as c:
        data = c.get("/v1/nearby", params={"lat": 37.786, "lng": -122.393}).json()
    assert data["center"]["label"] == "the pin at 37.78600, -122.39300"


def test_nearby_pin_validation(make_client, mock_apis):
    with make_client() as c:
        assert c.get("/v1/nearby", params={"lat": 37.7}).status_code == 422
        assert c.get("/v1/nearby", params={"lat": 137.7, "lng": 1}).status_code == 422


def test_locate_endpoint(make_client, mock_apis):
    mock_apis.get(GEOCODE).mock(side_effect=_geocode_ok)
    with make_client() as c:
        r = c.get("/v1/locate", params={"address": "1st & Mission, San Francisco"})
        assert c.get("/v1/locate").status_code == 422
    assert r.json() == {"lat": 37.7897, "lng": -122.3972, "label": "1st St & Mission St, San Francisco, CA 94105, USA"}


def test_search_page_start_options(make_client):
    with make_client() as c:
        no_key = c.get("/").text
    with make_client(maps_key="browser-key") as c:
        with_key = c.get("/").text
    for html in (no_key, with_key):
        assert 'value="cross"' in html and 'value="map"' in html and 'id="mylocation"' in html
    assert 'id="pickmap"' in with_key and '"key": "browser-key"' in with_key
    assert 'id="pickmap"' not in no_key and "needs GOOGLE_MAPS_BROWSER_KEY" in no_key
    # The map script isn't in the page; it's added only when "Map or my location" is chosen.
    assert '<script async src="https://maps.googleapis.com' not in with_key

import json
import logging

from app.dishes import extract_dishes
from app.logging_setup import CloudJsonFormatter
from app.matching import similarity
from app.models import Market, Review
from app.service import bayesian, detect_market


def test_detect_market():
    assert detect_market("Taipei 101", None) == Market.tw
    assert detect_market("台中市西屯區", None) == Market.tw
    assert detect_market("Austin, TX", None) == Market.us
    assert detect_market("Austin, TX", Market.tw) == Market.tw


def test_bayesian_pulls_small_samples_down():
    assert bayesian(5.0, 4) < bayesian(4.6, 1800)


def test_similarity():
    assert similarity("Joe's Pizza", "Joe’s Pizza - Broadway") >= 0.9
    assert similarity("Noodle House", "Burger Barn") < 0.6


def test_dishes_ignores_non_dishes():
    reviews = [Review(source="g", review_id=str(i), text=t) for i, t in enumerate([
        "Try the duck confit. The service was amazing.",
        "The duck confit was excellent and the staff were great.",
    ])]
    assert extract_dishes(reviews) == ["duck confit"]


def test_log_format_is_cloud_logging_json():
    rec = logging.LogRecord("app", logging.WARNING, __file__, 1, "hello", (), None)
    rec.restaurant = "Noodle House"
    out = json.loads(CloudJsonFormatter().format(rec))
    assert out["severity"] == "WARNING" and out["message"] == "hello" and out["restaurant"] == "Noodle House"


def test_dish_phrase_stops_at_linking_word():
    reviews = [Review(source="g", review_id=str(i), text=t) for i, t in enumerate([
        "Ordered the pork buns and loved them.",
        "Try the pork buns with chili oil.",
    ])]
    assert extract_dishes(reviews) == ["pork buns"]


def test_tripadvisor_matching_rules():
    from app.sources.tripadvisor import match
    from tests.conftest import ta_location
    near_en = ta_location(1, ["Din Tai Fung"], 0.01)
    # Different scripts, same spot, nothing else close: matched by position.
    assert match("鼎泰豐", [near_en]) is near_en
    # Same script but different name: never matched by position.
    assert match("Big Bowl", [near_en]) is None
    # Two places close by: position is ambiguous, so no match.
    assert match("鼎泰豐", [near_en, ta_location(2, ["Bubble Tea Bar"], 0.04)]) is None
    # Names match: picked even if not the nearest.
    far = ta_location(3, ["Big Bowl"], 0.25)
    assert match("Big Bowl", [near_en, far]) is far


def test_postal_code():
    from app.sources.tripadvisor import postal_code
    assert postal_code("2855 Stevens Creek Blvd #2477, Santa Clara, CA 95050, USA") == "95050"
    assert postal_code("1 Main St, Seattle, WA 98101-1234, USA") == "98101"
    assert postal_code("110台北市信義區松高路19號") == "110"
    assert postal_code("No. 19, Songgao Rd, Xinyi District, Taipei City, Taiwan 110") == "110"
    assert postal_code("1 Main St, Seattle, WA") == ""


def test_detect_market_explicit_country_wins():
    assert detect_market("2855 Stevens Creek Blvd, Santa Clara, CA 95050美國", None) == Market.us
    assert detect_market("123 Taipei Ave, Austin, TX, USA", None) == Market.us
    assert detect_market("110台北市信義區松高路19號", None) == Market.tw


def test_dishes_skip_descriptions():
    reviews = [Review(source="g", review_id=str(i), text=t) for i, t in enumerate([
        "Try the variety of dishes. The savory dish of the day was great. Loved the vegan dumplings.",
        "Got the things everyone orders. Try the vegan dumplings and the green beans.",
        "The green beans were amazing.",
    ])]
    # Mentioned by two reviewers; nothing generic like "variety of dishes" or "things".
    assert extract_dishes(reviews) == ["vegan dumplings"]
    assert extract_dishes(reviews[2:]) == ["green beans"]


def test_dishes_only_food():
    """Phrases from the real results that weren't dishes: version, annoyed face, pleasure..."""
    texts = [
        "Best sushi we've ever had. Get the set omakase.",
        "Had an annoyed face from the host. Tried the new version of the menu.",
        "Got the pleasure of meeting the chef. Loved the local chopped salad.",
        "Try the pizzas, the pizza crust was perfect.",
        "Order the pizza. Order the local chopped salad.",
    ]
    reviews = [Review(source="g", review_id=str(i), text=t) for i, t in enumerate(texts)]
    dishes = extract_dishes(reviews)
    assert set(dishes) == {"local chopped salad", "pizzas"}  # each mentioned by two reviewers
    singles = extract_dishes(reviews[:3])
    assert "annoyed face" not in singles and "version" not in singles and "pleasure" not in singles
    assert "set omakase" in singles and "sushi" in singles


def _hours(periods, offset=-420):
    from app.models import Hours
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return Hours(weekday_text=[f"{d}: 11:00 AM – 9:00 PM" for d in days], periods=periods, utc_offset_minutes=offset)


def _daily(open_h, close_h, close_next_day=False):
    return [{"open": {"day": d, "hour": open_h, "minute": 0},
             "close": {"day": (d + 1) % 7 if close_next_day else d, "hour": close_h, "minute": 0}} for d in range(7)]


def test_open_now_in_restaurant_time_zone():
    from datetime import datetime, timezone
    from app.hours import is_open, today_text
    h = _hours(_daily(11, 21))  # 11 AM - 9 PM, San Francisco (UTC-7 in October)
    # 19:00 UTC Wednesday = noon in San Francisco.
    assert is_open(h, datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)) is True
    # 05:00 UTC Thursday = 10 PM Wednesday in San Francisco.
    assert is_open(h, datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)) is False
    assert today_text(h, datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)) == "11:00 AM – 9:00 PM"


def test_open_past_midnight_and_24_hours():
    from datetime import datetime, timezone
    from app.hours import is_open
    late = _hours(_daily(18, 2, close_next_day=True), offset=480)  # 6 PM - 2 AM, Taipei (UTC+8)
    # 17:00 UTC Saturday = 1 AM Sunday in Taipei: still open from Saturday night.
    assert is_open(late, datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)) is True
    assert is_open(late, datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)) is False  # 4 AM
    always = _hours([{"open": {"day": 0, "hour": 0, "minute": 0}}])
    assert is_open(always, datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc)) is True


def test_price_range_format():
    from app.sources.google_places import _price_range
    usd = lambda u: {"currencyCode": "USD", "units": u}
    assert _price_range({"startPrice": usd("20"), "endPrice": usd("30")}) == "$20–30"
    assert _price_range({"startPrice": usd("100")}) == "$100+"
    assert _price_range({"startPrice": {"currencyCode": "TWD", "units": "200"},
                         "endPrice": {"currencyCode": "TWD", "units": "1000"}}) == "NT$200–1,000"
    assert _price_range(None) is None


def test_intersections_recognised():
    from app.sources.google_places import is_intersection
    for text in ("1st St & Mission St, San Francisco", "Main St and 5th Ave", "Broadway at 42nd St",
                 "Market/Castro", "忠孝東路與敦化南路", "忠孝東路敦化南路口"):
        assert is_intersection(text), text
    for text in ("2855 Stevens Creek Blvd, Santa Clara", "Taipei 101", "台北市信義區松高路19號"):
        assert not is_intersection(text), text


def test_market_at():
    from app.service import market_at
    assert market_at(25.033, 121.565) == Market.tw     # Taipei
    assert market_at(24.43, 118.32) == Market.tw       # Kinmen
    assert market_at(37.78, -122.39) == Market.us

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

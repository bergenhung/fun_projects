"""Name matching across sources (e.g. "Joe's Pizza" vs "Joe’s Pizza - Broadway")."""
import re
import unicodedata
from difflib import SequenceMatcher

_NOISE = re.compile(r"\b(restaurant|the|cafe|bar|kitchen|grill|llc|inc)\b|[^\w]", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.split(" - ")[0]  # drop branch suffixes like "- Downtown"
    return _NOISE.sub("", text)


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.9
    return SequenceMatcher(None, na, nb).ratio()


def has_cjk(text: str) -> bool:
    """True if the text contains Chinese characters."""
    return any("一" <= ch <= "鿿" for ch in text or "")

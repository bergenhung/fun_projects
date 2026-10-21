"""Pull likely dish names out of review text.

A simple, explainable heuristic: look for phrases reviewers use when naming a dish
("try the ...", "the ... was amazing", "必點...", "推薦..."), then count mentions across all
saved reviews. It's labelled as an estimate in the response. Swapping in an LLM later only
means replacing extract_dishes().
"""
import re
from collections import Counter

from app.models import Review

_WORD = r"[A-Za-z][A-Za-z'\-]*"
_PHRASE = rf"((?:{_WORD}\s){{0,3}}{_WORD})"
EN_PATTERNS = [
    re.compile(rf"\b(?:try|order|ordered|get|got|recommend|loved|love|had)\s+(?:the|their|a|an)\s+{_PHRASE}", re.I),
    re.compile(rf"\bthe\s+{_PHRASE}\s+(?:was|were|is|are)\s+(?:amazing|excellent|incredible|delicious|great|perfect|outstanding|fantastic|the best)", re.I),
    re.compile(rf"\b(?:signature|famous|must[- ]try|best)\s+{_PHRASE}", re.I),
]
ZH_PATTERNS = [
    re.compile(r"(?:必點|推薦|招牌|必吃|最愛|好吃的)(?:的)?[「『]?([一-鿿]{2,6})"),
    re.compile(r"([一-鿿]{2,6})(?:超好吃|很好吃|必點|一絕|好好吃)"),
]
# Words that follow the cue phrases but aren't dishes.
STOP = {
    "service", "staff", "place", "food", "wait", "atmosphere", "ambiance", "ambience", "price", "prices",
    "time", "experience", "restaurant", "menu", "portion", "portions", "location", "vibe", "decor", "server",
    "waiter", "waitress", "parking", "line", "view", "music", "bill", "table", "reservation", "chance",
    "meal", "dinner", "lunch", "breakfast", "brunch", "spot", "owner", "everything", "quality",
    "服務", "環境", "價格", "餐點", "店家", "老闆", "氣氛", "東西", "這家", "餐廳",
}
TRAILING_STOP = {"and", "with", "was", "were", "is", "are", "but", "here", "there", "too", "so", "which", "that",
                 "for", "at", "it", "or", "then", "they", "we", "i", "very", "really"}


def _clean(phrase: str) -> str | None:
    words = phrase.strip().split()
    # A dish name ends at the first linking word: "pork buns and loved them" -> "pork buns".
    for i, w in enumerate(words):
        if w.lower() in TRAILING_STOP:
            words = words[:i]
            break
    if not words:
        return None
    candidate = " ".join(words).lower()
    if candidate in STOP or words[-1].lower() in STOP or len(candidate) < 3:
        return None
    return candidate


def extract_dishes(reviews: list[Review], top_n: int = 5) -> list[str]:
    counts: Counter[str] = Counter()
    for r in reviews:
        seen: set[str] = set()  # count each dish once per review
        for pat in EN_PATTERNS:
            for m in pat.finditer(r.text):
                if (d := _clean(m.group(1))) and d not in seen:
                    seen.add(d)
        for pat in ZH_PATTERNS:
            for m in pat.finditer(r.text):
                d = m.group(1)
                if d not in STOP and d not in seen:
                    seen.add(d)
        counts.update(seen)
    # Prefer dishes several reviewers mention; fall back to single mentions if that's all there is.
    ranked = [d for d, c in counts.most_common() if c >= 2] or [d for d, _ in counts.most_common()]
    return ranked[:top_n]

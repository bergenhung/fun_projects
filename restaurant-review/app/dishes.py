"""Pull likely dish names out of review text.

A simple, explainable heuristic in two steps:
1. Find phrases reviewers use when naming a dish ("try the ...", "the ... was amazing",
   "必點...", "推薦...").
2. Keep an English phrase only if it contains a recognisable food word (pizza, salad, omakase,
   duck...) and no word about the visit (place, service, menu...). This drops things like
   "version", "annoyed face" or "pleasure" that follow the same cue words.

Mentions are counted once per review; dishes several reviewers mention come first. It's labelled
as an estimate in the response. Swapping in an LLM later only means replacing extract_dishes().
"""
import re
from collections import Counter, defaultdict

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
# Chinese candidates that follow the cue words but aren't dishes.
ZH_STOP = {"服務", "環境", "價格", "餐點", "店家", "老闆", "氣氛", "東西", "這家", "餐廳", "味道", "份量", "口味"}
# A dish name ends at the first of these: "pork buns and loved them" -> "pork buns",
# "sushi we've ever had" -> "sushi".
CUT = {
    "and", "with", "was", "were", "is", "are", "but", "here", "there", "too", "so", "which", "that", "for",
    "at", "it", "or", "then", "they", "we", "i", "very", "really", "of", "the", "a", "an", "in", "on", "to",
    "from", "as", "if", "when", "this", "these", "those", "my", "our", "their", "we've", "i've", "you've",
    "we'd", "i'd", "you", "ever", "had", "have", "has", "will", "would", "could", "should", "just", "also",
    "again", "today", "tonight", "yesterday", "last", "next", "every", "always", "definitely",
}
# An English candidate must contain one of these (singular or plural).
FOOD_WORDS = set("""
pizza margherita calzone pasta spaghetti linguine fettuccine rigatoni penne lasagna lasagne ravioli tortellini
gnocchi risotto carbonara bolognese pesto parmigiana parm burrata mozzarella bruschetta focaccia arancini tiramisu
cannoli gelato panna cotta affogato
burger cheeseburger hamburger slider fries fry sandwich sub hoagie panini melt wrap hotdog dog wing nugget tender
steak ribeye sirloin filet tenderloin strip brisket rib ribs chop cutlet schnitzel roast prime meatloaf meatball
sausage bratwurst bacon ham pork belly beef lamb veal chicken duck turkey quail goose
fish salmon tuna cod halibut snapper bass trout tilapia mackerel eel unagi shrimp prawn scallop oyster clam mussel
crab lobster octopus calamari squid uni roe caviar ceviche poke crudo tartare carpaccio
sushi sashimi nigiri maki roll handroll omakase chirashi donburi don tempura katsu karaage yakitori teriyaki
ramen udon soba tonkotsu gyoza edamame miso takoyaki okonomiyaki
noodle dumpling bao bun xiaolongbao potsticker wonton shumai siumai dimsum congee chowfun lomein chowmein
mapo tofu kungpao char siu duck rice friedrice bibimbap bulgogi galbi kimchi japchae tteokbokki jjigae
pho banh mi bun bo vermicelli springroll eggroll pad thai seeew larb satay laksa curry rendang khao soi som tam
tikka masala vindaloo korma biryani dal daal naan roti paratha samosa pakora paneer chaat dosa idli tandoori
kebab kabob gyro shawarma falafel hummus baba ganoush tabbouleh fattoush pita shakshuka
taco burrito quesadilla enchilada tamale tostada nacho nachos guacamole guac salsa mole pozole elote churro
carnitas barbacoa birria al pastor fajita chimichanga empanada arepa pupusa ceviche
paella tapas croqueta croquette patatas jamon
salad caesar soup stew chowder bisque gumbo jambalaya chili broth
toast bread sourdough baguette croissant bagel biscuit scone muffin pastry danish brioche pretzel cornbread
pancake waffle omelette omelet frittata quiche benedict eggs egg hash grits oatmeal granola parfait crepe
confit cassoulet bouillabaisse ratatouille frites moules escargot terrine pate rillettes tartine croque
cake cheesecake pie tart cobbler crumble brownie cookie donut doughnut macaron eclair pudding custard flan
mousse sundae icecream sorbet mochi souffle creme brulee churros
latte cappuccino espresso coffee tea matcha boba chai smoothie milkshake shake lemonade cocktail margarita
mojito martini negroni sangria mimosa wine beer ale ipa sake soju
cheese charcuterie fondue raclette platter board flatbread mac slaw coleslaw cornbread onion rings
potato potatoes mash gratin vegetable veggies greens beans sprouts mushroom mushrooms cauliflower eggplant
asparagus spinach kale corn avocado tofu tempeh seitan
""".split())
# Multi-word foods whose last word alone isn't distinctive.
FOOD_PHRASES = {"ice cream", "panna cotta", "creme brulee", "pad thai", "pad see ew", "banh mi", "khao soi",
                "dim sum", "char siu", "kung pao", "al pastor", "onion rings", "mac and cheese", "spring rolls",
                "egg rolls", "fried rice", "hot pot", "hot dog", "short rib", "short ribs", "pork belly"}


def _singular(word: str) -> str:
    w = word.lower()
    for suffix, repl in (("ies", "y"), ("oes", "o"), ("ches", "ch"), ("shes", "sh"), ("ses", "s"), ("s", "")):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            return w[: -len(suffix)] + repl
    return w


# A candidate with any of these words describes the visit, not a dish ("chicken place", "pizza menu").
NOT_FOOD = {
    "dish", "dishes", "thing", "things", "variety", "selection", "option", "options", "item", "items", "stuff",
    "food", "menu", "meal", "place", "spot", "experience", "service", "staff", "server", "waiter", "waitress",
    "atmosphere", "ambiance", "vibe", "decor", "view", "music", "price", "prices", "portion", "portions",
    "wait", "line", "table", "reservation", "time", "visit", "location", "parking", "owner", "chef", "version",
    "deal", "special", "value", "quality", "selection", "spread", "joint", "restaurant", "bar", "lot", "bit",
}


def _is_food(candidate: str) -> bool:
    words = candidate.split()
    if any(w in NOT_FOOD or _singular(w) in NOT_FOOD for w in words):
        return False
    if any(p in candidate for p in FOOD_PHRASES):
        return True
    # Any food word counts, so dishes missing from the list still get through via their main
    # ingredient ("duck confit", "lamb shoulder").
    return any(w in FOOD_WORDS or _singular(w) in FOOD_WORDS for w in words)


def _clean(phrase: str) -> str | None:
    words = phrase.strip().split()
    for i, w in enumerate(words):
        if w.lower() in CUT:
            words = words[:i]
            break
    if not words:
        return None
    candidate = " ".join(words).lower().strip("'-")
    if len(candidate) < 3 or not _is_food(candidate):
        return None
    return candidate


def extract_dishes(reviews: list[Review], top_n: int = 5) -> list[str]:
    counts: Counter[str] = Counter()
    shown: dict[str, Counter[str]] = defaultdict(Counter)  # key -> spellings seen ("pizza", "pizzas")
    for r in reviews:
        seen: set[str] = set()  # count each dish once per review
        for pat in EN_PATTERNS:
            for m in pat.finditer(r.text):
                if d := _clean(m.group(1)):
                    key = " ".join(_singular(w) for w in d.split())
                    shown[key][d] += 1
                    seen.add(key)
        for pat in ZH_PATTERNS:
            for m in pat.finditer(r.text):
                d = m.group(1)
                if d not in ZH_STOP:
                    shown[d][d] += 1
                    seen.add(d)
        counts.update(seen)
    # Prefer dishes several reviewers mention; fall back to single mentions if that's all there is.
    ranked = [k for k, c in counts.most_common() if c >= 2] or [k for k, _ in counts.most_common()]
    return [shown[k].most_common(1)[0][0] for k in ranked[:top_n]]

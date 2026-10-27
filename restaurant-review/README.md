# Cross-site restaurant review

A small web service that puts a restaurant's ratings from several review sites side by side. It can either:

- **Verify one restaurant**: "Is this place actually good?" The Location can be a city, district, street or landmark ("Xinyi District, Taipei", "Taipei 101"). When a chain has several branches, the one closest to that location is shown, and the others are listed as one-click links.
- **Restaurants near an address**: the N restaurants closest to an address (default 3, within 1 km), with optional cuisine, price and minimum-rating filters.

  The starting point can be an **address**, **cross streets** ("1st St" & "Mission St", San Francisco, or 忠孝東路 & 敦化南路, 台北), or a **point**: click the map to drop a pin (drag it to adjust), search for a spot, or press **Use my location**. The map loads only when that option is chosen, so other page views don't count as Google map loads.

In both modes Google Maps is the starting point: the restaurants shown are the ones Google returns. Each is then looked up directly on Tripadvisor and checked against the Michelin Guide list, with links to search the Michelin Guide and Yelp sites yourself.

Each result row shows the all-time rating per site, a combined all-time rating, a last-3-months rating, the Michelin status, and the dishes reviewers mention most.

| Market | Detected when the location mentions | Sources |
| --- | --- | --- |
| `us` | anything else | Google Places + Tripadvisor + Michelin Guide, and a "See on Yelp" link per row |
| `tw` | Taiwan, Taipei, 台北, 台中, 高雄, … | Google Places + Tripadvisor + Michelin Guide |

Only the Google key is required. Each other source is used when its key or data is present and quietly left out otherwise. Yelp's API is paid, so by default Yelp appears only as a link the person opens themselves; set `YELP_API_KEY` if you ever buy a plan and its rating joins the table instead.

You can also force a market with `market=us` or `market=tw`.

## Stack (and why)

| Piece | Choice | Why |
| --- | --- | --- |
| Language / framework | Python, FastAPI | Async calls to several review APIs at once; free interactive API docs at `/docs` |
| Hosting | Cloud Run | Scales to zero, so it costs almost nothing while idle |
| Database | Firestore (Native mode) | Has a free daily quota, no server to run, pay-per-use beyond that |
| Secrets | Secret Manager | API keys never sit in code or env files |
| Logging | JSON to stdout | Cloud Logging reads severity, trace and fields automatically |
| Map | Google Maps JavaScript API | Google's terms require Places results to be shown on a Google map |
| Auth | None by default; optional API key | Public read-only service. Set `SERVICE_API_KEY` to require an `X-API-Key` header (API-only use: the web page can't send it) |

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Search page with autocomplete (HTML) |
| `GET /v1/autocomplete?q=&kind=restaurant\|location&session=` | Suggestions while typing (min 2 characters) |
| `GET /v1/verify?name=&location=` or `?place_id=` | One restaurant; `place_id` comes from autocomplete and skips name matching |
| `GET /v1/locate?address=` | Coordinates for an address or cross streets (used by the map picker) |
| `GET /v1/nearby?address=&count=&within_km=&cuisine=&price=&min_rating=&sort=` or `?lat=&lng=…` | The `count` (1–10, default 3) restaurants closest to an address, within `within_km` (default 1, max 10). `sort` is `distance` (default) or `rating`. `place_id` and `session` come from address autocomplete. |
| `GET /docs` | Interactive OpenAPI docs |
| `GET /healthz` | Health check |

Add `format=html` to `/v1/verify` or `/v1/nearby` for a rendered page: a map with numbered pins plus the table. In near-an-address mode the map also shows the address (dark pin) and the distance limit (circle), and the table gets a distance column. Clicking a row opens its pin, and clicking a pin highlights its row. `price` takes `$$`, `$-$$$` or `1,2`.

```
/v1/verify?name=Din%20Tai%20Fung&location=Taipei
/v1/nearby?address=2855%20Stevens%20Creek%20Blvd,%20Santa%20Clara&count=3&within_km=1&format=html
```

Example JSON row (trimmed):

```json
{
  "rank": 1,
  "name": "Noodle House",
  "price": "$$",
  "ratings": [
    {"source": "google", "rating": 4.6, "review_count": 1800, "url": "..."},
    {"source": "tripadvisor", "rating": 4.5, "review_count": 1320, "url": "...", "rating_image_url": "..."}
  ],
  "all_time_rating": 4.57,
  "recent_3_months": {"average": 4.67, "review_count": 3, "low_confidence": true, "window_days": 90},
  "michelin": null,
  "top_dishes": ["spicy miso ramen", "pork buns"],
  "links": [{"label": "See on Yelp", "url": "https://www.yelp.com/search?find_desc=Noodle+House&find_loc=..."}],
  "score": 4.502
}
```

## How the numbers work

- **All time**: each site's own rating. The combined figure weights each site by its review count.
- **Order**: near-an-address results are closest first by default. With `sort=rating` they're ordered by `score`, a Bayesian average, so a 5.0 from 4 reviews doesn't beat a 4.6 from 1,800.
- **Last 3 months**: the review APIs return only a few reviews per call (Google and Tripadvisor up to 5 each). The service saves every review it sees in Firestore, so this column is thin at first and fills in as restaurants get looked up again. `low_confidence` is true under 5 reviews.
- **Top dishes**: phrases like "try the …", "the … was amazing", "必點…", "…超好吃" counted across saved reviews. English phrases are kept only if they contain a food word (pizza, salad, omakase, duck…) and no word about the visit (service, menu, place…), so things like "version" or "annoyed face" are dropped. It's an estimate; `app/dishes.py` is the one place to change if you later use an LLM instead.
- **Hours and price**: from Google. "Open now" is worked out in the restaurant's own time zone each time a page is shown, so cached results stay correct. The price range is Google's typical spend per person ("$20–30"). Restaurants Google marks as permanently closed are left out of near-an-address results.
- **Caching**: identical searches are reused for 6 hours (`CACHE_TTL_HOURS`) to save API costs.

## Autocomplete and map

- **Autocomplete** goes through this service (`/v1/autocomplete`), so the Places key never reaches the browser. Typing waits 250 ms between keystrokes, suggestions are cached for an hour, and each typing session sends a session token, which Google bills more cheaply when it ends in a lookup. Picking a restaurant passes its exact Google place ID to `/v1/verify`, so there's no guessing which "Joe's" was meant. Works with the keyboard (arrows, Enter, Escape) and screen readers. Restaurant suggestions favour the area in the Location field when it's filled in (otherwise Google favours wherever you are, which may be another branch). If a picked restaurant turns out to be more than 50 km from the Location you typed, the app searches for that name in that location instead, and editing Location after picking clears the pick. The market (US or Taiwan) always follows the restaurant's own address.
- **Map** needs a second key, because a map key is visible in the page by design:
  1. APIs & Services → enable *Maps JavaScript API* → Credentials → Create API key.
  2. Restrict it: *Application restrictions* → Websites, add `http://localhost:8000/*` and your Cloud Run URL; *API restrictions* → Maps JavaScript API only.
  3. Set `GOOGLE_MAPS_BROWSER_KEY`. Optionally create a Map ID (Map management) and set `GOOGLE_MAP_ID`; `DEMO_MAP_ID` works for testing.

  The map has zoom (+/−) and full-screen buttons, and a **Show all** button that zooms back out to every result. Scroll-wheel zoom needs Ctrl (⌘ on Mac) so the page still scrolls normally; on phones, pinch with two fingers.

  Without the key the page shows the table and a one-line note instead of the map.
- **Directions**: every row and map pin has a *Directions* link that opens Google Maps directions to the restaurant from the viewer's current location, with driving, transit, walking and cycling options (on a phone it opens the Maps app). It's a plain link, so it needs no extra API and costs nothing. Each page view with a map counts as a map load on your Google bill (there's a free monthly allowance; check the current pricing page).

### Cross streets and dropped pins: enable the Geocoding API

Google's place search often can't find an intersection, so cross streets use Google's **Geocoding API**, which also turns a dropped pin into a readable address. To turn it on: APIs & Services → Library → **Geocoding API** → Enable, then edit your server key (the Places one) and tick **Geocoding API** under API restrictions as well.

If it isn't enabled, the app still works: cross streets fall back to place search (less reliable), and a dropped pin is labelled with its coordinates. The terminal logs `google geocoding unavailable` when this happens. Geocoding is billed separately per request, with its own free allowance; lookups are remembered for a day.

## Run locally

Needs **Python 3.10 or newer** (3.12 recommended). On macOS, the built-in `python3` is often 3.9; check with `python3 --version`.

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env          # add GOOGLE_PLACES_API_KEY (and YELP_API_KEY if you have one)
uvicorn app.main:app --reload
# open http://localhost:8000
pytest                        # tests mock every external API; no keys needed
```

### Common errors

| Error | Fix |
| --- | --- |
| `RuntimeError: This project needs Python 3.10 or newer` or `TypeError: unsupported operand type(s) for \|` | Your Python is too old. Install 3.12, delete `.venv`, and recreate it with the new Python. |
| `ModuleNotFoundError: No module named 'app'` | Run commands from the project folder (the one containing `app/`). |
| `ModuleNotFoundError: No module named 'fastapi'` (or similar) | The virtual environment isn't active, or dependencies aren't installed: `source .venv/bin/activate` then `pip install -r requirements-dev.txt`. |
| `503 ... GOOGLE_PLACES_API_KEY is not set` | Add the key to `.env` and restart uvicorn. |
| `404 No restaurant matching …` | The message lists what Google returned. If the restaurant is there under another name, search that name, or pick it from the suggestions while typing. |
| `502 A review site didn't respond properly` | Check the terminal log for `google places search failed`; a 403 there usually means *Places API (New)* isn't enabled for the key's project, or the key is restricted to other APIs. |
| `[Errno 48] Address already in use` | Another server is on port 8000. Stop it, or use `uvicorn app.main:app --reload --port 8001`. |

## Deploy to Google Cloud

1. **Create a project** and link billing. Set a budget alert right away (Billing → Budgets & alerts).
2. **Get a Google Places key**: APIs & Services → Credentials → Create API key. Restrict it to *Places API (New)*.
   Text Search requests that include reviews are billed at a higher Places tier, which is why results are cached. Check the current Google Maps Platform pricing page.
3. **Tripadvisor (optional)**: see [Tripadvisor](#tripadvisor) below.
4. **Yelp (optional, paid)**: skip it unless you buy a Fusion plan; US rows link to Yelp either way.
5. **Deploy** (needs the `gcloud` CLI, logged in):
   ```bash
   export PROJECT_ID=your-project-id
   export GOOGLE_PLACES_API_KEY=...
   export TRIPADVISOR_API_KEY=...      # optional
   export GOOGLE_MAPS_BROWSER_KEY=...  # optional, shows the map
   ./deploy.sh                 # REGION defaults to us-west1
   ```
   The script enables the APIs, creates Firestore with a TTL policy for the cache, a least-privilege service account, the secrets, and the Cloud Run service (0–3 instances).

Re-run `./deploy.sh` to ship code changes.

## Tripadvisor

Tripadvisor retired its old Content API on August 31, 2026; new keys come from its **Terra** platform, which this project uses (`https://terra.tripadvisor.com/api`, key sent in the `X-API-Key` header).

**Getting a key**
1. Go to https://www.tripadvisor.com/developers?screen=home and sign in (Google or email). If no sign-in box appears, click **Get Started**.
2. Fill in the organization profile (name, website, size). For a personal project, your name and a GitHub or portfolio link are fine.
3. Choose the entry plan (**Discover** at the time of writing) and confirm at checkout. Expect to add a card.
4. In the dashboard, open **Overview** → **My API key** → **Create API key**, then **Copy to clipboard**.
5. Put it in `.env` as `TRIPADVISOR_API_KEY=...` and restart the server.

**Cost.** Terra bills per *entity*: every location a search returns is one, and each details or reviews call is one. Errors aren't billed. At the time of writing the first 1,000 entities are free **once per account (not monthly)**, then about $0.015 each, getting cheaper with volume. Check the pricing shown when you sign up.

**How this project keeps that small**
- Finds each restaurant by **name**, narrowed to its postal code and country, asking for at most 3 results. A same-named result must be within 1 km of Google's pin, so another branch of a chain isn't picked. Searching by name means a restaurant inside a mall or food court is still found even when other places are nearer the pin.
- Falls back to a *nearby* search (3 results) only when the name search finds nothing, mainly for names written differently on each site (鼎泰豐 vs Din Tai Fung).
- Remembers the Tripadvisor match per Google place for 30 days (no-matches for 7), so repeat lookups cost 2 entities.
- In near-an-address mode, only the restaurants shown (`count`, default 3) are looked up.
- Caches whole searches for `CACHE_TTL_HOURS`.
- Stops for the rest of the UTC day after `TRIPADVISOR_DAILY_ENTITY_LIMIT` entities (default 30 locally, 10 per instance on Cloud Run), or as soon as Tripadvisor returns 429. Rows then show Google and Michelin only.

Rough worst case: a fresh search for 3 nearby restaurants costs about 15 entities (more if several need the nearby fallback); with the default local cap of 30 a day, that's at most about $0.45 a day once the free allowance is used. The cap is counted in memory per running instance and resets on restart.

**Taiwan.** Reviews are requested in their original language (`language=primary`), so local Chinese reviews count. Google often returns Chinese names and Tripadvisor English ones, so when names are in different scripts the closest listing within 30 m is accepted if nothing else is nearby. Two same-script names that don't match are never paired.

**Display rules.** Wherever its rating appears, Tripadvisor requires its bubble-rating image, a link to the listing and a credit. The results page shows all three; if you build your own front end on the JSON, use `rating_image_url` and `url` the same way.

**Why a cell is empty.** The Tripadvisor column says *not found* (no matching listing), *not checked (daily limit)*, *couldn't check (see log)* (an error, such as a rejected key) or *not checked* (the row wasn't looked up). The JSON has the same in each row's `source_status`.

**First run.** Terra's public reference doesn't list every response field, so the parser accepts the likely variants, and the first response of each kind is logged as `tripadvisor sample response`. If Tripadvisor ratings don't appear, that log line shows what came back.

## Michelin data (US and Taiwan)

Michelin has no public API, so there's one hand-maintained list per market: `data/michelin_us.csv` and `data/michelin_tw.csv`. Update them after each guide release. The US guide is published as several regional editions on different dates, so the US file will be updated a few times a year.

```
name,name_zh,city,distinction,year
Example Bistro,,New York|Brooklyn,1 Star,2026
Example Restaurant,範例餐廳,Taipei|台北|臺北,Bib Gourmand,2026
```

- `distinction` is one of `3 Stars`, `2 Stars`, `1 Star`, `Bib Gourmand`, `Selected`.
- `name_zh` is optional; it's there for Taiwan, where Google often returns the Chinese name.
- `city` must appear in the restaurant's Google address, so a starred "Joe's" in one city doesn't label every "Joe's" elsewhere. List aliases with `|`, and for Taiwan include the Chinese city name, since Google addresses there are usually in Chinese.

Both files ship empty, and the Michelin column shows "–" until you fill them. Redeploy after editing.

## Logs

In Cloud Logging, every line is JSON with `severity`, `request_id` and the request trace. Useful queries:

```
resource.type="cloud_run_revision" AND jsonPayload.message="request"
resource.type="cloud_run_revision" AND severity>=WARNING
jsonPayload.message="tripadvisor no match"
jsonPayload.message="tripadvisor sample response"
jsonPayload.message:"tripadvisor skipped"
```

## Project layout

```
app/
  main.py            routes, middleware (logging, optional API key)
  service.py         builds the table: matching, ratings, ranking
  sources/           google_places.py, tripadvisor.py, michelin.py, yelp.py (paid, off by default)
  store.py           Firestore / in-memory review history and cache
  dishes.py          dish extraction
  render.py          HTML search page (autocomplete) and results (map + table)
  logging_setup.py   Cloud Logging JSON format
data/michelin_us.csv, data/michelin_tw.csv
tests/
Dockerfile, deploy.sh
```

## Next steps

- More sources go in `app/sources/` and `ReviewService._sources`.
- A nightly Cloud Scheduler job that re-checks popular restaurants, so 3-month history builds faster.
- The multi-region VM version (global VPC, `us-west1`, `us-east1`, `asia-east1`) defined in Terraform, reusing this Docker image.

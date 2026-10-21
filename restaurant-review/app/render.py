"""HTML views: the search page (with autocomplete) and the results page (with map)."""
import json
from html import escape

from app.models import ResultTable

STYLE = """
<style>
:root{--bg:#faf9f6;--fg:#1f1e1c;--muted:#6b6a65;--line:#e4e1d8;--accent:#9a3412;--accent-dark:#7c2d12;--chip:#f3efe6;--panel:#fff;--hl:#fdf1e7}
@media (prefers-color-scheme:dark){:root{--bg:#191917;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--accent:#fb923c;--accent-dark:#c2410c;--chip:#2a2926;--panel:#23221f;--hl:#3a2a1e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 20px}
form{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));align-items:end}
label{font-size:13px;color:var(--muted);display:grid;gap:4px}
input,select,button{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--fg);width:100%}
button{background:var(--accent);color:#fff;border:0;cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
fieldset{border:1px solid var(--line);border-radius:12px;padding:16px;margin:0 0 20px}legend{padding:0 6px;font-weight:600}
.ac{position:relative}.ac ul{position:absolute;z-index:10;left:0;right:0;top:calc(100% + 4px);margin:0;padding:4px;list-style:none;background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.12);max-height:280px;overflow:auto}
.ac li{padding:7px 9px;border-radius:6px;cursor:pointer;color:var(--fg);font-size:14px}.ac li small{display:block;color:var(--muted);font-size:12px}
.ac li[aria-selected=true],.ac li:hover{background:var(--chip)}.ac .err{color:var(--muted);cursor:default}
.formerr{color:#b91c1c;font-size:13px;grid-column:1/-1;margin:0}
#map{height:380px;border-radius:12px;border:1px solid var(--line);margin:0 0 18px;background:var(--chip)}@media (max-width:640px){#map{height:280px}}
.mapnote{color:var(--muted);font-size:13px;margin:0 0 16px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:760px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:13px;color:var(--muted);font-weight:600}
tr[data-idx]{cursor:pointer}tr.active td{background:var(--hl)}
.rank{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;font-size:12px;font-weight:600}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 8px;margin:0 4px 4px 0;font-size:13px}
.muted{color:var(--muted);font-size:13px}a{color:var(--accent)}
a.ext{display:inline-block;margin-top:4px;font-size:13px}img.bubbles{vertical-align:-3px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}ul.notes{color:var(--muted);font-size:13px;padding-left:18px}
.iw{font:14px/1.4 system-ui,sans-serif;color:#1f1e1c;max-width:240px}.iw b{display:block;margin-bottom:2px}.iw span{color:#6b6a65;font-size:12px}
</style>"""

# Autocomplete: suggestions come from this service (/v1/autocomplete), so the Places key stays on the server.
AUTOCOMPLETE_JS = r"""
<script>
(function () {
  const newToken = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, "");
  let uid = 0;

  function attach(input, kind, onPick) {
    const wrap = document.createElement("div");
    wrap.className = "ac";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const list = document.createElement("ul");
    list.id = "ac-list-" + (++uid);
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.appendChild(list);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", list.id);
    input.setAttribute("autocomplete", "off");

    let items = [], active = -1, timer = null, ctrl = null, token = newToken();

    function close() {
      list.hidden = true; active = -1;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }
    function highlight(i) {
      active = i;
      [...list.children].forEach((li, j) => li.setAttribute("aria-selected", String(j === i)));
      if (i >= 0 && list.children[i]) {
        input.setAttribute("aria-activedescendant", list.children[i].id);
        list.children[i].scrollIntoView({ block: "nearest" });
      }
    }
    function render(msg) {
      list.innerHTML = "";
      if (msg) {
        const li = document.createElement("li"); li.className = "err"; li.textContent = msg; list.appendChild(li);
      }
      items.forEach((s, i) => {
        const li = document.createElement("li");
        li.id = list.id + "-" + i;
        li.setAttribute("role", "option");
        li.textContent = s.main;
        if (s.secondary) { const sm = document.createElement("small"); sm.textContent = s.secondary; li.appendChild(sm); }
        li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(i); });
        list.appendChild(li);
      });
      const open = items.length > 0 || !!msg;
      list.hidden = !open;
      input.setAttribute("aria-expanded", String(open));
      highlight(-1);
    }
    function pick(i) {
      const s = items[i];
      if (!s) return;
      onPick(s, token);
      token = newToken();   // next typing session gets a fresh token
      close();
    }
    async function fetchSuggestions(q) {
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      try {
        const url = "/v1/autocomplete?" + new URLSearchParams({ q, kind, session: token });
        const res = await fetch(url, { signal: ctrl.signal });
        if (!res.ok) { items = []; render(res.status === 503 ? "Suggestions unavailable (no Google key set)" : ""); return; }
        items = await res.json();
        render(items.length ? "" : "");
      } catch (e) { if (e.name !== "AbortError") { items = []; render(""); } }
    }
    input.addEventListener("input", () => {
      input.dispatchEvent(new CustomEvent("ac:typed"));
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { items = []; close(); return; }
      timer = setTimeout(() => fetchSuggestions(q), 250);
    });
    input.addEventListener("keydown", (e) => {
      if (list.hidden || !items.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); highlight((active + 1) % items.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active <= 0 ? items.length - 1 : active - 1); }
      else if (e.key === "Enter" && active >= 0) { e.preventDefault(); pick(active); }
      else if (e.key === "Escape") { close(); }
    });
    input.addEventListener("blur", () => setTimeout(close, 100));
  }

  // Check one restaurant: picking a suggestion pins the exact place.
  const vf = document.getElementById("verify-form");
  const vName = vf.querySelector("[name=name]"), vLoc = vf.querySelector("[name=location]");
  const vPid = vf.querySelector("[name=place_id]"), vSess = vf.querySelector("[name=session]");
  attach(vName, "restaurant", (s, token) => {
    vName.value = s.main; vPid.value = s.place_id; vSess.value = token;
    if (!vLoc.value.trim()) vLoc.value = s.secondary;
  });
  vName.addEventListener("ac:typed", () => { vPid.value = ""; vSess.value = ""; });
  attach(vLoc, "location", (s) => { vLoc.value = s.text || s.main; });
  vf.addEventListener("submit", (e) => {
    const err = vf.querySelector(".formerr");
    if (!vName.value.trim()) {
      e.preventDefault(); err.textContent = "Enter a restaurant name."; err.hidden = false; vName.focus(); return;
    }
    if (!vPid.value && !vLoc.value.trim()) {
      e.preventDefault(); err.textContent = "Pick a restaurant from the suggestions, or enter a location.";
      err.hidden = false; vLoc.focus(); return;
    }
    err.hidden = true;
    if (!vPid.value) { vPid.disabled = true; vSess.disabled = true; }   // keep the URL tidy
  });
  vLoc.addEventListener("input", () => { vf.querySelector(".formerr").hidden = true; });

  // Top options: location autocomplete only.
  const tLoc = document.querySelector("#top-form [name=location]");
  attach(tLoc, "location", (s) => { tLoc.value = s.text || s.main; });
})();
</script>"""


def search_page() -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cross-site restaurant review</title>{STYLE}</head><body><main>
<h1>Cross-site restaurant review</h1><p class="sub">Ratings from several review sites side by side: all time, last 3 months, and dishes people mention.</p>
<fieldset><legend>Check one restaurant</legend><form id="verify-form" action="/v1/verify" method="get" novalidate>
<input type="hidden" name="format" value="html"><input type="hidden" name="place_id"><input type="hidden" name="session">
<label>Restaurant<input name="name" required placeholder="Start typing, e.g. Din Tai Fung"></label>
<label>Location<input name="location" placeholder="e.g. Taipei or Seattle, WA"></label>
<button type="submit">Check</button>
<p class="formerr" role="alert" hidden>Pick a restaurant from the suggestions, or enter a location.</p></form></fieldset>
<fieldset><legend>Find top options</legend><form id="top-form" action="/v1/top" method="get">
<input type="hidden" name="format" value="html">
<label>Location<input name="location" required placeholder="e.g. Mission District, San Francisco"></label>
<label>Cuisine<input name="cuisine" placeholder="e.g. ramen"></label>
<label>Price<select name="price"><option value="">Any</option><option>$</option><option>$$</option><option>$$$</option><option>$$$$</option><option value="$-$$">$ to $$</option></select></label>
<label>Minimum rating<select name="min_rating"><option value="">Any</option><option>4.0</option><option>4.5</option></select></label>
<label>How many<select name="limit"><option>5</option><option>3</option><option>10</option></select></label>
<button type="submit">Search</button></form></fieldset>
<p class="muted">JSON API and docs: <a href="/docs">/docs</a></p></main>{AUTOCOMPLETE_JS}</body></html>"""


SOURCE_LABELS = {"google": "Google", "tripadvisor": "Tripadvisor", "yelp": "Yelp"}


def _fmt(v, digits=1):
    return "–" if v is None else f"{v:.{digits}f}"


def _map_block(t: ResultTable, maps_key: str, map_id: str) -> str:
    points = [
        {"idx": i, "rank": r.rank or i + 1, "name": r.name, "address": r.address, "lat": r.lat, "lng": r.lng,
         "rating": r.all_time_rating, "michelin": r.michelin}
        for i, r in enumerate(t.rows) if r.lat is not None and r.lng is not None
    ]
    if not points:
        return ""
    if not maps_key:
        return '<p class="mapnote">Map hidden: set GOOGLE_MAPS_BROWSER_KEY to show results on a map.</p>'
    data = json.dumps({"points": points, "mapId": map_id}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<div id="map" role="region" aria-label="Map of results"></div>
<script>
const MAPDATA = {data};
function gm_authFailure() {{
  document.getElementById("map").outerHTML = '<p class="mapnote">The map couldn\\'t load. Check that the browser key allows the Maps JavaScript API and this site\\'s address.</p>';
}}
function initMap() {{
  const el = document.getElementById("map");
  const map = new google.maps.Map(el, {{ mapId: MAPDATA.mapId, center: MAPDATA.points[0], zoom: 14,
    mapTypeControl: false, streetViewControl: false, clickableIcons: false }});
  const info = new google.maps.InfoWindow();
  const bounds = new google.maps.LatLngBounds();
  const markers = {{}};
  const rows = document.querySelectorAll("tr[data-idx]");
  function select(idx, fromMap) {{
    const p = MAPDATA.points.find(x => x.idx === idx); if (!p) return;
    rows.forEach(r => r.classList.toggle("active", Number(r.dataset.idx) === idx));
    const box = document.createElement("div"); box.className = "iw";
    const b = document.createElement("b"); b.textContent = p.rank + ". " + p.name; box.appendChild(b);
    const s = document.createElement("span");
    s.textContent = [p.rating != null ? "All time " + p.rating.toFixed(2) : "", p.michelin ? "Michelin: " + p.michelin : "", p.address]
      .filter(Boolean).join(" · ");
    box.appendChild(s);
    info.setContent(box); info.open({{ map, anchor: markers[idx] }});
    if (fromMap) {{ const row = document.querySelector('tr[data-idx="' + idx + '"]'); row && row.scrollIntoView({{ block: "nearest", behavior: "smooth" }}); }}
    else {{ map.panTo({{ lat: p.lat, lng: p.lng }}); el.scrollIntoView({{ block: "nearest", behavior: "smooth" }}); }}
  }}
  MAPDATA.points.forEach(p => {{
    const pin = new google.maps.marker.PinElement({{ glyph: String(p.rank), background: "#9a3412", borderColor: "#7c2d12", glyphColor: "#ffffff" }});
    const m = new google.maps.marker.AdvancedMarkerElement({{ map, position: {{ lat: p.lat, lng: p.lng }}, title: p.name, content: pin.element, gmpClickable: true }});
    m.addListener("click", () => select(p.idx, true));
    markers[p.idx] = m; bounds.extend({{ lat: p.lat, lng: p.lng }});
  }});
  if (MAPDATA.points.length > 1) map.fitBounds(bounds, 48); else map.setZoom(15);
  rows.forEach(r => {{
    r.tabIndex = 0;
    r.addEventListener("click", e => {{ if (e.target.closest("a")) return; select(Number(r.dataset.idx), false); }});
    r.addEventListener("keydown", e => {{ if (e.key === "Enter") select(Number(r.dataset.idx), false); }});
  }});
}}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key={escape(maps_key)}&loading=async&libraries=marker&callback=initMap"></script>"""


def table_page(t: ResultTable, maps_key: str = "", map_id: str = "DEMO_MAP_ID") -> str:
    sources = t.sources_used
    head = "".join(f"<th>{escape(SOURCE_LABELS.get(s, s.title()))}</th>" for s in sources if s != "michelin")
    if "michelin" in sources:
        head += "<th>Michelin</th>"
    body = []
    for i, r in enumerate(t.rows):
        by_src = {s.source: s for s in r.ratings}
        cells = []
        for s in sources:
            if s == "michelin":
                continue
            sr = by_src.get(s)
            if sr and sr.rating is not None:
                label = _fmt(sr.rating)
                if sr.rating_image_url:
                    # Tripadvisor's display rules: show its bubble image and link to the listing.
                    label = (f'<img class="bubbles" src="{escape(sr.rating_image_url)}" '
                             f'alt="{_fmt(sr.rating)} of 5 bubbles" width="98" height="18"> {label}')
                link = f'<a href="{escape(sr.url)}" target="_blank" rel="noopener">{label}</a>' if sr.url else label
                cells.append(f'<td>{link}<div class="muted">{sr.review_count or 0:,} reviews</div></td>')
            else:
                cells.append('<td class="muted">not found</td>')
        if "michelin" in sources:
            cells.append(f"<td>{escape(r.michelin) if r.michelin else '<span class=muted>–</span>'}</td>")
        rec = r.recent_3_months
        recent = f"{_fmt(rec.average)}<div class='muted'>{rec.review_count} saved review{'s' if rec.review_count != 1 else ''}{' · low confidence' if rec.low_confidence else ''}</div>"
        dishes = "".join(f'<span class="chip">{escape(d)}</span>' for d in r.top_dishes) or '<span class="muted">not enough reviews yet</span>'
        meta = " · ".join(x for x in (r.price, r.cuisine) if x)
        extra = "".join(
            f'<a class="ext" href="{escape(l.url)}" target="_blank" rel="noopener">{escape(l.label)}'
            f'<span class="sr-only"> (opens in a new tab)</span> ↗</a>'
            for l in r.links
        )
        idx_attr = f' data-idx="{i}"' if r.lat is not None else ""
        body.append(
            f"<tr{idx_attr}><td><span class='rank'>{r.rank or i + 1}</span></td><td><strong>{escape(r.name)}</strong><div class='muted'>{escape(r.address)}</div>"
            f"<div class='muted'>{escape(meta)}</div>{extra}</td><td><strong>{_fmt(r.all_time_rating, 2)}</strong></td>"
            f"{''.join(cells)}<td>{recent}</td><td>{dishes}</td></tr>"
        )
    notes = "".join(f"<li>{escape(n)}</li>" for n in t.notes)
    q = ", ".join(f"{k}: {v}" for k, v in t.query.items() if v not in (None, "", []))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Restaurant ratings</title>{STYLE}</head><body><main>
<h1>Restaurant ratings</h1><p class="sub">{escape(q)} · market: {t.market.value.upper()} · <a href="/">new search</a></p>
{_map_block(t, maps_key, map_id)}
<div class="wrap"><table><thead><tr><th>#</th><th>Restaurant</th><th>All time</th>{head}<th>Last 3 months</th><th>Top dishes</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div><ul class="notes">{notes}</ul></main></body></html>"""

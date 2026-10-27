"""HTML views: the search page (with autocomplete) and the results page (with map)."""
import json
from urllib.parse import urlencode
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
.hours{font-size:13px;margin-top:2px;color:var(--muted)}.hours .open{color:#15803d;font-weight:600}
.hours .shut{color:#b91c1c;font-weight:600}
@media (prefers-color-scheme:dark){.hours .open{color:#4ade80}.hours .shut{color:#f87171}}
.week{display:inline}.week summary{display:inline;cursor:pointer;margin-left:6px;text-decoration:underline}
.week ul{margin:4px 0 0;padding-left:16px}
.alts{margin:-8px 0 16px;font-size:14px}.alts summary{cursor:pointer;color:var(--muted)}
.alts ul{margin:6px 0 0;padding-left:18px}.alts li{margin:2px 0}
.start{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:5px 12px;color:var(--fg);font-size:14px;cursor:pointer}
.pill input{width:auto;margin:0}
.pill:has(input:checked){border-color:var(--accent);background:var(--hl)}
.grid3{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.maptools{display:grid;gap:10px;grid-template-columns:1fr auto;align-items:end;margin-bottom:10px}
@media (max-width:560px){.maptools{grid-template-columns:1fr}}
button.secondary{background:transparent;color:var(--accent);border:1px solid var(--accent)}
#pickmap{height:340px;border-radius:12px;border:1px solid var(--line);background:var(--chip)}
.modes{display:inline-flex;border:1px solid var(--line);border-radius:10px;padding:3px;margin:0 0 16px;gap:2px;flex-wrap:wrap}
.modes button{width:auto;background:transparent;color:var(--fg);border-radius:7px;padding:7px 14px}
.modes button[aria-selected=true]{background:var(--accent);color:#fff}
.wide{grid-column:1/-1}
[hidden]{display:none !important}
.formerr{color:#b91c1c;font-size:13px;grid-column:1/-1;margin:0}
#map{height:380px;border-radius:12px;border:1px solid var(--line);margin:0 0 18px;background:var(--chip)}@media (max-width:640px){#map{height:280px}}
.mapnote{color:var(--muted);font-size:13px;margin:0 0 16px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:760px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:13px;color:var(--muted);font-weight:600}
tr[data-idx]{cursor:pointer}tr.active td{background:var(--hl)}
.rank{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;font-size:12px;font-weight:600}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 8px;margin:0 4px 4px 0;font-size:13px}
.muted{color:var(--muted);font-size:13px}a{color:var(--accent)}
.rowlinks{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:4px}a.ext{font-size:13px}
.mapbtn{margin:10px;padding:6px 12px;width:auto;background:#fff;color:#1f1e1c;border:0;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font:500 13px system-ui,sans-serif;cursor:pointer}
.iw a.iwdir{display:inline-block;margin-top:6px;color:#9a3412;font-size:13px}img.bubbles{vertical-align:-3px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}ul.notes{color:var(--muted);font-size:13px;padding-left:18px}
.iw{font:14px/1.4 system-ui,sans-serif;color:#1f1e1c;max-width:240px}.iw b{display:block;margin-bottom:2px}.iw span{display:block;color:#6b6a65;font-size:12px}
</style>"""

# Autocomplete: suggestions come from this service (/v1/autocomplete), so the Places key stays on the server.
AUTOCOMPLETE_JS = r"""
<script>
(function () {
  const newToken = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, "");
  let uid = 0;

  function attach(input, kind, onPick, extra) {
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
        const params = { q, kind, session: token, ...(extra ? extra() : {}) };
        Object.keys(params).forEach(k => { if (!params[k]) delete params[k]; });
        const url = "/v1/autocomplete?" + new URLSearchParams(params);
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
  // Suggestions favour the Location field when it's filled in (otherwise Google favours
  // wherever the person is, which may be another branch entirely).
  attach(vName, "restaurant", (s, token) => {
    vName.value = s.main; vPid.value = s.place_id; vSess.value = token;
    if (!vLoc.value.trim()) vLoc.value = s.secondary;
  }, () => ({ near: vLoc.value.trim() }));
  // Changing the location after picking a restaurant means "that name, but there".
  vLoc.addEventListener("input", () => { vPid.value = ""; vSess.value = ""; });
  vName.addEventListener("ac:typed", () => { vPid.value = ""; vSess.value = ""; });
  // Any place works as the location: a city, a district, a street or a landmark ("Taipei 101").
  attach(vLoc, "address", (s) => { vLoc.value = s.text || s.main; });
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

  // Near an address: picking a suggestion pins the exact spot.
  const nf = document.getElementById("nearby-form");
  const nAddr = nf.querySelector("[name=address]");
  const nPid = nf.querySelector("[name=place_id]"), nSess = nf.querySelector("[name=session]");
  attach(nAddr, "address", (s, token) => { nAddr.value = s.text || s.main; nPid.value = s.place_id; nSess.value = token; });
  const nErr = nf.querySelector(".formerr");
  nAddr.addEventListener("ac:typed", () => { nPid.value = ""; nSess.value = ""; nErr.hidden = true; });

  // Start from: address, cross streets, or a point (map pin / my location).
  const nLat = nf.querySelector("[name=lat]"), nLng = nf.querySelector("[name=lng]");
  const x1 = document.getElementById("x1"), x2 = document.getElementById("x2"), x3 = document.getElementById("x3");
  const radios = [...nf.querySelectorAll("input[name=start]")];
  const panes = [...nf.querySelectorAll(".startpane")];
  const pinStatus = document.getElementById("pinstatus");
  let startMode = "address";
  function setStart(mode) {
    startMode = mode; nErr.hidden = true;
    panes.forEach(p => { p.hidden = p.dataset.start !== mode; });
    if (mode === "map") openPickMap();
  }
  radios.forEach(r => r.addEventListener("change", () => setStart(r.value)));
  attach(x3, "location", (s) => { x3.value = s.text || s.main; });

  let pickMap = null, pickPin = null, pendingPin = null, mapLoading = false;
  function setPin(lat, lng, label) {
    nLat.value = lat.toFixed(6); nLng.value = lng.toFixed(6); nErr.hidden = true;
    pinStatus.textContent = "Starting point: " + (label || lat.toFixed(5) + ", " + lng.toFixed(5));
    if (pickMap) {
      pickPin.position = { lat, lng }; pickPin.map = pickMap;
      pickMap.panTo({ lat, lng }); if (pickMap.getZoom() < 15) pickMap.setZoom(15);
    } else { pendingPin = { lat, lng }; }
  }
  function openPickMap() {
    if (!MAPCFG.key || mapLoading) return;
    mapLoading = true;  // loaded only when this option is used, so other page views don't count as map loads
    const sc = document.createElement("script");
    sc.async = true;
    sc.src = "https://maps.googleapis.com/maps/api/js?key=" + encodeURIComponent(MAPCFG.key) + "&loading=async&libraries=marker&callback=initPickMap";
    document.head.appendChild(sc);
  }
  window.gm_authFailure = () => {
    const el = document.getElementById("pickmap");
    if (el) el.outerHTML = '<p class="mapnote">The map couldn\'t load. Check the browser key allows the Maps JavaScript API and this site\'s address.</p>';
  };
  window.initPickMap = () => {
    const el = document.getElementById("pickmap");
    const zh = (navigator.language || "").toLowerCase().startsWith("zh");
    const start = pendingPin || (zh ? { lat: 25.0418, lng: 121.5654 } : { lat: 39.5, lng: -98.35 });
    pickMap = new google.maps.Map(el, { center: start, zoom: pendingPin ? 15 : (zh ? 12 : 4), mapId: MAPCFG.mapId,
      clickableIcons: false, streetViewControl: false, mapTypeControl: false, gestureHandling: "cooperative" });
    pickPin = new google.maps.marker.AdvancedMarkerElement({ gmpDraggable: true, title: "Starting point" });
    pickMap.addListener("click", (e) => setPin(e.latLng.lat(), e.latLng.lng(), "pin on the map"));
    pickPin.addListener("dragend", () => {
      const p = pickPin.position; setPin(typeof p.lat === "function" ? p.lat() : p.lat, typeof p.lng === "function" ? p.lng() : p.lng, "pin on the map");
    });
    if (pendingPin) { pickPin.position = pendingPin; pickPin.map = pickMap; }
  };

  document.getElementById("mylocation").addEventListener("click", () => {
    if (!navigator.geolocation) { pinStatus.textContent = "This browser can't share your location."; return; }
    pinStatus.textContent = "Getting your location…";
    navigator.geolocation.getCurrentPosition(
      (pos) => setPin(pos.coords.latitude, pos.coords.longitude, "your location (within about " + Math.round(pos.coords.accuracy) + " m)"),
      (err) => { pinStatus.textContent = "Couldn't get your location" + (err.code === 1 ? " (permission denied)." : "."); },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  });

  const mapFind = document.getElementById("mapfind");
  async function findSpot(params) {
    pinStatus.textContent = "Finding…";
    try {
      const res = await fetch("/v1/locate?" + new URLSearchParams(params));
      if (!res.ok) { pinStatus.textContent = "Couldn't find that. Try adding the city, or click the map."; return; }
      const j = await res.json(); setPin(j.lat, j.lng, j.label);
    } catch (e) { pinStatus.textContent = "Couldn't reach the server."; }
  }
  attach(mapFind, "address", (s, token) => {
    mapFind.value = s.text || s.main;
    findSpot({ address: mapFind.value, place_id: s.place_id, session: token });
  });
  mapFind.addEventListener("keydown", (e) => {
    // Enter with no suggestion highlighted: look up the text as typed (handy for "1st & Mission, SF").
    if (e.key === "Enter" && !e.defaultPrevented) { e.preventDefault(); if (mapFind.value.trim()) findSpot({ address: mapFind.value.trim() }); }
  });

  nf.addEventListener("submit", (e) => {
    const fail = (msg, el) => { e.preventDefault(); nErr.textContent = msg; nErr.hidden = false; if (el) el.focus(); };
    if (startMode === "address") {
      if (!nAddr.value.trim()) return fail("Enter an address.", nAddr);
      nLat.disabled = nLng.disabled = true;
      if (!nPid.value) { nPid.disabled = true; nSess.disabled = true; }
    } else if (startMode === "cross") {
      if (!x1.value.trim()) return fail("Enter a street.", x1);
      if (!x2.value.trim()) return fail("Enter the cross street.", x2);
      nAddr.value = x1.value.trim() + " & " + x2.value.trim() + (x3.value.trim() ? ", " + x3.value.trim() : "");
      nPid.disabled = nSess.disabled = nLat.disabled = nLng.disabled = true;
    } else {
      if (!nLat.value) return fail("Drop a pin on the map, find a spot, or use your location first.", mapFind);
      nAddr.disabled = nPid.disabled = nSess.disabled = true;
    }
    radios.forEach(r => { r.disabled = true; });
    nf.querySelectorAll("select, input[name=cuisine]").forEach(el => { if (!el.value) el.disabled = true; });
  });
  // Coming back with the browser's Back button: fields disabled for a tidy URL must work again.
  window.addEventListener("pageshow", () => document.querySelectorAll("form input, form select").forEach(el => { el.disabled = false; }));

  // Mode switch. Without JavaScript both forms simply show.
  const tabs = [...document.querySelectorAll("[role=tab]")];
  function show(id, focus) {
    tabs.forEach(t => {
      const on = t.id === id;
      t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (focus) document.getElementById(id).focus();
    try { history.replaceState(null, "", id === "tab-nearby" ? "#nearby" : "#"); } catch (e) {}
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t.id));
    t.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); show(tabs[(i + 1) % tabs.length].id, true); }
    });
  });
  show(location.hash === "#nearby" ? "tab-nearby" : "tab-single");
})();
</script>"""


def search_page(maps_key: str = "", map_id: str = "DEMO_MAP_ID") -> str:
    mapcfg = json.dumps({"key": maps_key, "mapId": map_id}).replace("</", "<\\/")
    map_area = ('<div id="pickmap" role="region" aria-label="Map for choosing the starting point"></div>' if maps_key else
                '<p class="mapnote">The map needs GOOGLE_MAPS_BROWSER_KEY. Finding a spot above and '
                '"Use my location" still work.</p>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cross-site restaurant review</title>{STYLE}</head><body><main>
<h1>Cross-site restaurant review</h1><p class="sub">Find restaurants on Google Maps, then see what Tripadvisor and the Michelin Guide say about each one: ratings all time and for the last 3 months, and the dishes people mention.</p>
<div class="modes" role="tablist" aria-label="Search mode">
<button type="button" role="tab" id="tab-single" aria-controls="panel-single" aria-selected="true">One restaurant</button>
<button type="button" role="tab" id="tab-nearby" aria-controls="panel-nearby" aria-selected="false">Restaurants near an address</button>
</div>
<fieldset id="panel-single" role="tabpanel" aria-labelledby="tab-single"><legend>Check one restaurant</legend><form id="verify-form" action="/v1/verify" method="get" novalidate>
<input type="hidden" name="format" value="html"><input type="hidden" name="place_id"><input type="hidden" name="session">
<label>Restaurant<input name="name" required placeholder="Start typing, e.g. Din Tai Fung"></label>
<label>Location<input name="location" placeholder="City, district, street or landmark, e.g. Xinyi District, Taipei"></label>
<button type="submit">Check</button>
<p class="formerr" role="alert" hidden>Pick a restaurant from the suggestions, or enter a location.</p></form></fieldset>
<fieldset id="panel-nearby" role="tabpanel" aria-labelledby="tab-nearby"><legend>Restaurants near an address</legend><form id="nearby-form" action="/v1/nearby" method="get" novalidate>
<input type="hidden" name="format" value="html"><input type="hidden" name="place_id"><input type="hidden" name="session">
<input type="hidden" name="lat"><input type="hidden" name="lng">
<div class="start wide" role="radiogroup" aria-label="Start from"><span class="muted">Start from</span>
<label class="pill"><input type="radio" name="start" value="address" checked> Address</label>
<label class="pill"><input type="radio" name="start" value="cross"> Cross streets</label>
<label class="pill"><input type="radio" name="start" value="map"> Map or my location</label></div>
<div class="startpane wide" data-start="address"><label>Address<input name="address" required placeholder="Start typing, e.g. 2855 Stevens Creek Blvd, Santa Clara"></label></div>
<div class="startpane wide grid3" data-start="cross" hidden>
<label>Street<input id="x1" placeholder="e.g. 1st St / 忠孝東路"></label>
<label>Cross street<input id="x2" placeholder="e.g. Mission St / 敦化南路"></label>
<label>City<input id="x3" placeholder="e.g. San Francisco, CA / 台北"></label></div>
<div class="startpane wide" data-start="map" hidden>
<div class="maptools"><label>Find a spot<input id="mapfind" placeholder="Address, landmark or cross streets, then pick or press Enter"></label>
<button type="button" id="mylocation" class="secondary">Use my location</button></div>
{map_area}
<p class="muted" id="pinstatus" aria-live="polite">Click the map to drop a pin (drag it to adjust), find a spot, or use your location.</p></div>
<label>How many<select name="count"><option>1</option><option>2</option><option selected>3</option><option>5</option><option>10</option></select></label>
<label>Within<select name="within_km"><option value="0.3">300 m (0.2 mi)</option><option value="0.5">500 m (0.3 mi)</option><option value="1" selected>1 km (0.6 mi)</option><option value="2">2 km (1.2 mi)</option><option value="5">5 km (3 mi)</option></select></label>
<label>Cuisine<input name="cuisine" placeholder="Any, or e.g. ramen"></label>
<label>Price<select name="price"><option value="">Any</option><option>$</option><option>$$</option><option>$$$</option><option>$$$$</option><option value="$-$$">$ to $$</option></select></label>
<label>Minimum rating<select name="min_rating"><option value="">Any</option><option>4.0</option><option>4.5</option></select></label>
<label>Order<select name="sort"><option value="distance">Closest first</option><option value="rating">Highest rated first</option></select></label>
<button type="submit">Find</button>
<p class="formerr" role="alert" hidden>Enter an address.</p></form></fieldset>
<script>const MAPCFG = {mapcfg};</script>
<p class="muted">JSON API and docs: <a href="/docs">/docs</a></p></main>{AUTOCOMPLETE_JS}</body></html>"""


MISSING = {
    "no_match": "not found",
    "matched": "no rating yet",
    "not_checked": "not checked",
    "limit": "not checked<div>(daily limit)</div>",
    "error": "couldn't check<div>(see log)</div>",
}
SOURCE_LABELS = {"google": "Google", "tripadvisor": "Tripadvisor", "yelp": "Yelp"}


def _fmt(v, digits=1):
    return "–" if v is None else f"{v:.{digits}f}"


def _map_block(t: ResultTable, maps_key: str, map_id: str) -> str:
    points = [
        {"idx": i, "rank": r.rank or i + 1, "name": r.name, "address": r.address, "lat": r.lat, "lng": r.lng,
         "rating": r.all_time_rating, "michelin": r.michelin, "directions": r.directions_url,
         "status": _status_text(r)}
        for i, r in enumerate(t.rows) if r.lat is not None and r.lng is not None
    ]
    if not points:
        return ""
    if not maps_key:
        return '<p class="mapnote">Map hidden: set GOOGLE_MAPS_BROWSER_KEY to show results on a map.</p>'
    center = t.center.model_dump() if t.center else None
    data = json.dumps({"points": points, "mapId": map_id, "center": center}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<div id="map" role="region" aria-label="Map of results"></div>
<script>
const MAPDATA = {data};
function gm_authFailure() {{
  document.getElementById("map").outerHTML = '<p class="mapnote">The map couldn\\'t load. Check that the browser key allows the Maps JavaScript API and this site\\'s address.</p>';
}}
function initMap() {{
  const el = document.getElementById("map");
  const map = new google.maps.Map(el, {{ mapId: MAPDATA.mapId, center: MAPDATA.points[0], zoom: 14,
    zoomControl: true, fullscreenControl: true, mapTypeControl: false, streetViewControl: false,
    clickableIcons: false, gestureHandling: "cooperative" }});
  const fitAll = () => {{ if (MAPDATA.points.length > 1 || MAPDATA.center) map.fitBounds(bounds, 48); else {{ map.setCenter(MAPDATA.points[0]); map.setZoom(15); }} }};
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "mapbtn"; btn.textContent = "Show all";
  btn.addEventListener("click", () => {{ info.close(); fitAll(); }});
  map.controls[google.maps.ControlPosition.TOP_LEFT].push(btn);
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
    s.textContent = [p.status, p.rating != null ? "All time " + p.rating.toFixed(2) : "", p.michelin ? "Michelin: " + p.michelin : "", p.address]
      .filter(Boolean).join(" · ");
    box.appendChild(s);
    if (p.directions) {{
      const a = document.createElement("a"); a.href = p.directions; a.target = "_blank"; a.rel = "noopener";
      a.className = "iwdir"; a.textContent = "Directions ↗"; box.appendChild(a);
    }}
    info.setContent(box); info.open({{ map, anchor: markers[idx] }});
    if (fromMap) {{ const row = document.querySelector('tr[data-idx="' + idx + '"]'); row && row.scrollIntoView({{ block: "nearest", behavior: "smooth" }}); }}
    else {{ map.panTo({{ lat: p.lat, lng: p.lng }}); if (map.getZoom() < 15) map.setZoom(15); el.scrollIntoView({{ block: "nearest", behavior: "smooth" }}); }}
  }}
  MAPDATA.points.forEach(p => {{
    const pin = new google.maps.marker.PinElement({{ glyph: String(p.rank), background: "#9a3412", borderColor: "#7c2d12", glyphColor: "#ffffff" }});
    const m = new google.maps.marker.AdvancedMarkerElement({{ map, position: {{ lat: p.lat, lng: p.lng }}, title: p.name, content: pin.element, gmpClickable: true }});
    m.addListener("click", () => select(p.idx, true));
    markers[p.idx] = m; bounds.extend({{ lat: p.lat, lng: p.lng }});
  }});
  if (MAPDATA.center) {{
    // The searched address: a dark pin, plus the distance limit as a faint circle.
    const c = MAPDATA.center, pos = {{ lat: c.lat, lng: c.lng }};
    const pin = new google.maps.marker.PinElement({{ background: "#1f2937", borderColor: "#111827", glyphColor: "#ffffff", scale: 0.9 }});
    new google.maps.marker.AdvancedMarkerElement({{ map, position: pos, title: "Searched address: " + c.label, content: pin.element, zIndex: 1 }});
    new google.maps.Circle({{ map, center: pos, radius: c.radius_km * 1000, clickable: false,
      strokeColor: "#9a3412", strokeOpacity: 0.45, strokeWeight: 1, fillColor: "#9a3412", fillOpacity: 0.04 }});
    bounds.extend(pos);
  }}
  fitAll();
  rows.forEach(r => {{
    r.tabIndex = 0;
    r.addEventListener("click", e => {{ if (e.target.closest("a")) return; select(Number(r.dataset.idx), false); }});
    r.addEventListener("keydown", e => {{ if (e.key === "Enter") select(Number(r.dataset.idx), false); }});
  }});
}}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key={escape(maps_key)}&loading=async&libraries=marker&callback=initMap"></script>"""


def _query_summary(query: dict, nearby: bool) -> str:
    if not nearby:
        return ", ".join(f"{k}: {v}" for k, v in query.items() if v not in (None, "", []))
    parts = [f"within {query.get('within_km', 1):g} km"]
    if query.get("cuisine"):
        parts.append(str(query["cuisine"]))
    if query.get("price"):
        parts.append("price " + "/".join("$" * p for p in query["price"]))
    if query.get("min_rating"):
        parts.append(f"rated {query['min_rating']}+")
    parts.append("highest rated first" if query.get("sort") == "rating" else "closest first")
    return " · ".join(parts)


def _alternatives_block(t: ResultTable) -> str:
    """Other branches of the same name, so a different one is one click away."""
    if not t.alternatives:
        return ""
    location = str(t.query.get("location") or "")
    name = str(t.query.get("name") or "")
    items = []
    for a in t.alternatives:
        href = "/v1/verify?" + urlencode({"format": "html", "place_id": a.place_id, "name": name, "location": location})
        dist = f" · {_short_distance(a.distance_km)}" if a.distance_km is not None else ""
        items.append(f'<li><a href="{escape(href)}">{escape(a.name)}</a>'
                     f'<span class="muted"> {escape(a.address)}{escape(dist)}</span></li>')
    where = f" near {escape(location)}" if location else ""
    return (f'<details class="alts"><summary>Showing the closest match{where}. '
            f'{len(t.alternatives)} other branch{"es" if len(t.alternatives) != 1 else ""}</summary>'
            f'<ul>{"".join(items)}</ul></details>')


def _short_distance(km: float) -> str:
    return f"{round(km * 1000, -1):.0f} m" if km < 1 else f"{km:.1f} km"


def _status_text(r) -> str:
    """'Open now · 11:00 AM – 9:00 PM', 'Closed now', 'Permanently closed'... ('' if unknown)."""
    if r.business_status == "CLOSED_PERMANENTLY":
        return "Permanently closed"
    if r.business_status == "CLOSED_TEMPORARILY":
        return "Temporarily closed"
    h = r.hours
    if not h or h.open_now is None:
        return ""
    state = "Open now" if h.open_now else "Closed now"
    return f"{state} · today {h.today}" if h.today else state


def _hours_html(r) -> str:
    text = _status_text(r)
    if not text:
        return ""
    is_open = bool(r.hours and r.hours.open_now) and r.business_status in (None, "OPERATIONAL")
    state, _, rest = text.partition(" · ")
    week = ""
    if r.hours and len(r.hours.weekday_text) == 7:
        items = "".join(f"<li>{escape(line)}</li>" for line in r.hours.weekday_text)
        week = f'<details class="week"><summary>All hours</summary><ul>{items}</ul></details>'
    return (f'<div class="hours"><span class="{"open" if is_open else "shut"}">{escape(state)}</span>'
            f'{" · " + escape(rest) if rest else ""}{week}</div>')


def _distance_cell(km: float | None) -> str:
    if km is None:
        return "<td class='muted'>–</td>"
    metric = f"{round(km * 1000, -1):.0f} m" if km < 1 else f"{km:.1f} km"
    miles = km * 0.621371
    mi = "&lt; 0.1 mi" if miles < 0.05 else f"{miles:.1f} mi"
    return f"<td>{metric}<div class='muted'>{mi}</div></td>"


def table_page(t: ResultTable, maps_key: str = "", map_id: str = "DEMO_MAP_ID") -> str:
    nearby = t.mode == "nearby" and t.center is not None
    if nearby:
        n = len(t.rows)
        title = f"{n} restaurant{'s' if n != 1 else ''} near {t.center.label}"
    else:
        title = "Restaurant ratings"
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
                cells.append(f'<td class="muted">{MISSING.get(r.source_status.get(s, "no_match"), "not found")}</td>')
        if "michelin" in sources:
            cells.append(f"<td>{escape(r.michelin) if r.michelin else '<span class=muted>–</span>'}</td>")
        rec = r.recent_3_months
        recent = f"{_fmt(rec.average)}<div class='muted'>{rec.review_count} saved review{'s' if rec.review_count != 1 else ''}{' · low confidence' if rec.low_confidence else ''}</div>"
        dishes = "".join(f'<span class="chip">{escape(d)}</span>' for d in r.top_dishes) or '<span class="muted">not enough reviews yet</span>'
        price = " ".join(x for x in (r.price, f"({r.price_range} per person)" if r.price_range else None) if x)
        meta = " · ".join(x for x in (price, r.cuisine) if x)
        row_links = ([("Directions", r.directions_url)] if r.directions_url else []) + [(l.label, l.url) for l in r.links]
        extra = '<div class="rowlinks">' + "".join(
            f'<a class="ext" href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}'
            f'<span class="sr-only"> (opens in a new tab)</span> ↗</a>'
            for label, url in row_links
        ) + "</div>" if row_links else ""
        idx_attr = f' data-idx="{i}"' if r.lat is not None else ""
        body.append(
            f"<tr{idx_attr}><td><span class='rank'>{r.rank or i + 1}</span></td><td><strong>{escape(r.name)}</strong><div class='muted'>{escape(r.address)}</div>"
            f"<div class='muted'>{escape(meta)}</div>{_hours_html(r)}{extra}</td>{_distance_cell(r.distance_km) if nearby else ''}"
            f"<td><strong>{_fmt(r.all_time_rating, 2)}</strong></td>"
            f"{''.join(cells)}<td>{recent}</td><td>{dishes}</td></tr>"
        )
    notes = "".join(f"<li>{escape(n)}</li>" for n in t.notes)
    q = _query_summary(t.query, nearby)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Restaurant ratings</title>{STYLE}</head><body><main>
<h1>{escape(title)}</h1><p class="sub">{escape(q)} · market: {t.market.value.upper()} · <a href="/{'#nearby' if nearby else ''}">new search</a></p>
{_alternatives_block(t)}
{_map_block(t, maps_key, map_id)}
<div class="wrap"><table><thead><tr><th>#</th><th>Restaurant</th>{'<th>Distance</th>' if nearby else ''}<th>All time</th>{head}<th>Last 3 months</th><th>Top dishes</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div><ul class="notes">{notes}</ul></main></body></html>"""

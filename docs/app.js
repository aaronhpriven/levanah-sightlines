// App controller: location search, settings, data loading, sightline solving, calendar table.
// The 3D viewer (viewer.js) is a port of the YIWS viewer and reads the globals below.

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

let MODEL = null;      // geodata model (buildings, streets, candidates, tz…)
let NIGHTS = [];       // solved nights
let SHUL = null;       // origin spot (outside the location) {x, y, g, …}
let BUILDINGS = [];
let CANDIDATES = [];
let PLACE = null;      // {lat, lon, label, name, short, pinLabel, atLabel}
let SETTINGS = null;
let loadToken = 0;

const EXAMPLES = [
  { key: "exYiws", lat: 40.790886, lon: -73.973311, name: "Young Israel of the West Side", label: "210 West 91st Street, New York, NY", short: "Shul" },
  { key: "exLakewood", lat: 40.08215, lon: -74.20955, name: "Beth Medrash Govoha", label: "Beth Medrash Govoha, Lakewood, NJ", short: "Yeshiva" },
  { key: "exLondon", lat: 51.57227, lon: -0.19529, name: "Golders Green", label: "Golders Green Road, London, UK", short: "Location" },
  { key: "exJerusalem", lat: 31.77612, lon: 35.21713, name: "Great Synagogue", label: "King George St 56, Jerusalem", short: "Shul" },
];

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep0 = () => new Promise(r => setTimeout(r, 0));

// ---------------------------------------------------------------- settings
function readSettingsFromUI() {
  return {
    year: parseInt($("setYear").value, 10),
    tzeis: parseInt($("setTzeis").value, 10),
    minDays: parseInt($("setMinDays").value, 10),
    sofZman: $("setSof").value,
    clearMin: parseInt($("setClear").value, 10),
    israel: $("setIsrael").value,
    walkMaxFt: parseInt($("setWalk").value, 10),
    defaultHeightFt: Math.max(8, Math.min(200, parseFloat($("setDefH").value) || 30)),
    short: ($("setShort").value || "Location").trim().slice(0, 24) || "Location",
  };
}

function ensureOption(sel, value, label) {
  if (![...sel.options].some(o => o.value === String(value))) {
    const o = document.createElement("option");
    o.value = String(value); o.textContent = label;
    sel.appendChild(o);
  }
  sel.value = String(value);
}

function initSettingsUI(params) {
  const cur = Astro.currentHebrewYear(new Date());
  const ys = $("setYear");
  for (let y = cur - 1; y <= cur + 2; y++) {
    const o = document.createElement("option");
    o.value = y; o.textContent = `${y}${y === cur ? " (current)" : ""}`;
    ys.appendChild(o);
  }
  ys.value = String(cur);
  if (params.get("year")) ensureOption(ys, parseInt(params.get("year"), 10), params.get("year"));
  if (params.get("tzeis")) ensureOption($("setTzeis"), parseInt(params.get("tzeis"), 10), `${params.get("tzeis")} min`);
  if (params.get("min")) ensureOption($("setMinDays"), parseInt(params.get("min"), 10), `${params.get("min")} days`);
  if (params.get("yt")) $("setIsrael").value = params.get("yt");
  if (params.get("sof")) $("setSof").value = params.get("sof");
  if (params.get("clr")) ensureOption($("setClear"), parseInt(params.get("clr"), 10), `${params.get("clr")} min after tzeis`);
  if (params.get("walk")) ensureOption($("setWalk"), parseInt(params.get("walk"), 10), `${params.get("walk")} ft`);
  if (params.get("defh")) $("setDefH").value = params.get("defh");
  if (params.get("short")) $("setShort").value = params.get("short");
  for (const id of ["setYear", "setTzeis", "setMinDays", "setSof", "setClear", "setIsrael", "setWalk", "setDefH", "setShort"]) {
    $(id).addEventListener("change", () => { $("btnApply").disabled = !PLACE; });
  }
}

// ---------------------------------------------------------------- status
let activeLog = null;
function setStatus(html, kind = "busy") {
  if (activeLog) { activeLog.stop(); activeLog = null; }
  const el = $("status");
  if (!html) { el.className = "status"; el.innerHTML = ""; return; }
  el.className = "status show" + (kind === "error" ? " error" : "");
  el.innerHTML = (kind === "busy" ? '<span class="spinner"></span>' : "") + html;
}

// Live, step-by-step load log with per-step timers (so users can see real lookups happening)
function makeLoadLog(title) {
  if (activeLog) activeLog.stop();
  const el = $("status");
  const t0 = performance.now();
  const steps = new Map();
  let alive = true;
  let errorHtml = "";
  const secs = s => (s < 10 ? s.toFixed(1) : s.toFixed(0)) + " s";
  const ICON = {
    active: '<span class="spinner"></span>',
    ok: '<span class="st-ic ok">✓</span>',
    warn: '<span class="st-ic warn">!</span>',
    fail: '<span class="st-ic fail">✕</span>',
  };
  function rowsHtml() {
    return [...steps.values()].map(s => {
      const dt = ((s.t1 ?? performance.now()) - s.t0) / 1000;
      const det = Array.isArray(s.detail) ? s.detail : (s.detail ? [s.detail] : []);
      return `<div class="st-row st-${s.state}">${ICON[s.state]}<div class="st-body">
        <div class="st-title">${esc(s.title)}${s.sub ? ` <span class="st-sub">${esc(s.sub)}</span>` : ""}<span class="st-time">${secs(dt)}</span></div>
        ${det.map(d => `<div class="st-detail">${esc(d)}</div>`).join("")}</div></div>`;
    }).join("");
  }
  function render() {
    if (!alive) return;
    const total = (performance.now() - t0) / 1000;
    el.className = "status show loadlog" + (errorHtml ? " error" : "");
    el.innerHTML = `<div class="st-head">${errorHtml ? "" : '<span class="spinner"></span>'}${esc(title)}<span class="st-time">${secs(total)} elapsed</span></div>${rowsHtml()}${errorHtml}`;
    // Re-rendering recreates spinners; offset their animation by a shared clock so rotation stays continuous
    const phase = `-${(performance.now() % 800) / 1000}s`;
    el.querySelectorAll(".spinner").forEach(sp => { sp.style.animationDelay = phase; });
  }
  const timer = setInterval(render, 250);
  const end = (k, state, d) => {
    const s = steps.get(k);
    if (!s) return;
    s.state = state;
    if (d !== undefined) s.detail = d;
    s.t1 = performance.now();
    render();
  };
  const api = {
    start(k, title, sub) { steps.set(k, { title, sub, state: "active", detail: null, t0: performance.now() }); render(); },
    detail(k, d) { const s = steps.get(k); if (s && s.state === "active") { s.detail = d; render(); } },
    ok: (k, d) => end(k, "ok", d),
    warn: (k, d) => end(k, "warn", d),
    fail: (k, d) => end(k, "fail", d),
    error(msgHtml) {
      for (const s of steps.values()) if (s.state === "active") { s.state = "fail"; s.t1 = performance.now(); }
      errorHtml = `<div class="st-error">${msgHtml}</div>`;
      render();
      clearInterval(timer);
      alive = false;
    },
    finish() {
      const total = (performance.now() - t0) / 1000;
      const html = rowsHtml();
      api.stop();
      el.className = "status";
      el.innerHTML = "";
      return { total, html };
    },
    stop() { alive = false; clearInterval(timer); if (activeLog === api) activeLog = null; },
  };
  activeLog = api;
  render();
  return api;
}
let lastLoadSummary = null;
const SOF_LABEL = {
  "15d": "15 full days after molad",
  half: "half the lunar month (14d 18h 22m after molad)",
  lel15: "the end of the night of the 15th (dawn)",
};

// ---------------------------------------------------------------- search (as-you-type + explicit)
let searchSeq = 0, searchAbort = null, searchTimer = null, searchResults = [], searchActive = -1, justPicked = 0;

function renderResults(list, msg) {
  const box = $("results");
  searchResults = list;
  searchActive = -1;
  box.innerHTML = msg ? `<div class="results-msg">${msg}</div>` : "";
  list.forEach((r, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "result";
    b.dataset.idx = i;
    b.innerHTML = `${esc(r.label)}<span class="src">${esc(r.source)} &bull; ${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}</span>`;
    b.onmousedown = e => e.preventDefault(); // keep focus in the input
    b.onclick = () => pickResult(i);
    box.appendChild(b);
  });
}

function highlightResult(i) {
  const items = $("results").querySelectorAll(".result");
  if (!items.length) return;
  searchActive = (i + items.length) % items.length;
  items.forEach((el, k) => el.classList.toggle("active", k === searchActive));
  items[searchActive].scrollIntoView({ block: "nearest" });
}

function pickResult(i) {
  const r = searchResults[i];
  if (!r) return;
  justPicked = Date.now();
  clearTimeout(searchTimer);
  if (searchAbort) searchAbort.abort();
  searchSeq++;
  renderResults([]);
  choosePlace(r);
}

async function runSearch(q, explicit) {
  q = q.trim();
  clearTimeout(searchTimer);
  if (searchAbort) searchAbort.abort();
  const seq = ++searchSeq;
  if (q.length < (explicit ? 1 : 3)) { renderResults([]); return; }
  searchAbort = new AbortController();
  const sig = searchAbort.signal;
  renderResults(searchResults, `<span class="spinner"></span>${/new york|nyc|manhattan|brooklyn|queens|bronx|staten/i.test(q) ? I18N.t("searchingNycText") : I18N.t("searchingText")}`);
  $("btnSearch").disabled = explicit;
  try {
    const res = await Geo.geocode(q, { autocomplete: !explicit, signal: sig });
    if (seq !== searchSeq) return;
    if (explicit && res.length === 1 && res[0].source === "Coordinates") { renderResults([]); choosePlace(res[0]); return; }
    if (!res.length) {
      renderResults([], explicit ? I18N.t("noMatchesFound") : I18N.t("noMatchesYet"));
      return;
    }
    renderResults(res);
    if (explicit) highlightResult(0);
  } catch (e) {
    if (seq !== searchSeq) return;
    renderResults([], `Search failed: ${esc(e.message)}`);
  } finally {
    if (seq === searchSeq) $("btnSearch").disabled = false;
  }
}

function doSearch(q) { return runSearch(q, true); }

function initSearchBox() {
  const input = $("q");
  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = input.value;
    if (q.trim().length < 3) { if (searchAbort) searchAbort.abort(); searchSeq++; renderResults([]); return; }
    searchTimer = setTimeout(() => runSearch(q, false), 300);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); highlightResult(searchActive + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); highlightResult(searchActive - 1); }
    else if (e.key === "Escape") { if (searchAbort) searchAbort.abort(); searchSeq++; renderResults([]); }
    else if (e.key === "Enter" && searchActive >= 0) { e.preventDefault(); pickResult(searchActive); }
  });
}

function choosePlace(r, shortOverride) {
  const s = readSettingsFromUI();
  const short = shortOverride || s.short;
  if (shortOverride) $("setShort").value = shortOverride;
  const name = (r.name || r.label || "Selected location").trim();
  PLACE = {
    lat: +r.lat, lon: +r.lon,
    label: r.label || name,
    name,
    short,
    pinLabel: name.length > 32 ? name.slice(0, 30) + "…" : name,
    atLabel: `Outside ${short}`,
  };
  $("q").value = PLACE.label;
  loadPlace();
}

// ---------------------------------------------------------------- analytics (GoatCounter)
function trackEvent(path, title = "") {
  try {
    if (window.goatcounter && typeof window.goatcounter.count === "function") {
      window.goatcounter.count({ path, title, event: true });
    }
  } catch { /* ignore */ }
}

// ---------------------------------------------------------------- loading pipeline
async function loadPlace() {
  if (!PLACE) return;
  const token = ++loadToken;
  SETTINGS = readSettingsFromUI();
  PLACE.short = SETTINGS.short;
  PLACE.atLabel = `Outside ${SETTINGS.short}`;
  $("btnApply").disabled = true;
  $("calSection").classList.remove("show");
  $("btnShare").style.display = "none";
  $("btnPdf").style.display = "none";
  const log = makeLoadLog(`Loading ${PLACE.name}`);
  try {
    const model = await Geo.loadLocation(PLACE, SETTINGS, log);
    if (token !== loadToken) return;
    MODEL = model;
    SHUL = model.shul;
    BUILDINGS = model.buildings;
    CANDIDATES = model.candidates;
    trackEvent(model.nycMode ? "event/load/nyc" : "event/load/osm", model.nycMode ? "Location loaded (NYC)" : "Location loaded (OSM)");
    if (model.tz) trackEvent(`event/tz/${model.tz}`, `Region: ${model.tz}`);
    await solveNights(token, log);
  } catch (e) {
    if (token !== loadToken) return;
    console.error(e);
    trackEvent("event/load-error", "Location load failed");
    log.error(`<strong>Could not load building data for this location.</strong> ${esc(e.message)}<br/>
      These are free public map servers and are sometimes overloaded &mdash; please try again in a minute or two.
      <button class="btn secondary" type="button" style="margin-left:6px;padding:5px 10px" onclick="loadPlace()">Try again</button>`);
  }
}

async function solveNights(token, log) {
  const { lat, lon } = PLACE;
  const elevM = SHUL.g / Geo.FT;
  const tz = MODEL.tz;
  const isIsrael = SETTINGS.israel === "auto" ? null : SETTINGS.israel === "israel";
  log.start("cal", `Hebrew calendar ${SETTINGS.year}: molad, Kiddush Levanah windows & tzeis`, `local time: ${tz}`);
  await sleep0();
  const nights = Astro.computeYear({
    year: SETTINGS.year, lat, lon, elevM, tzName: tz,
    tzeisMinutes: SETTINGS.tzeis, minDaysAfterMolad: SETTINGS.minDays, sofZman: SETTINGS.sofZman, isIsrael,
  });
  log.ok("cal", `${nights.length} valid nights (${nights.filter(n => n.is_motzaei).length} Motzaei Shabbos / YK / 9 Av)`);
  log.start("rays", "Ray-casting sightlines for every night", `${BUILDINGS.length.toLocaleString()} buildings × ${CANDIDATES.length.toLocaleString()} spots × ${SETTINGS.clearMin + 1} minutes`);

  const fmt = ms => Astro.formatTime(ms, tz);
  const samples = (startMs, mins) => {
    const out = [];
    for (let k = 0; k <= mins; k++) {
      const m = Astro.moonAltAz(startMs + k * 60000, lat, lon, elevM);
      out.push([m.az, m.alt]);
    }
    return out;
  };

  let t0 = performance.now();
  for (let i = 0; i < nights.length; i++) {
    if (token !== loadToken) return;
    const n = nights[i];
    let spot = null, wait = 0, waitMs = n.eval_ms;
    if (n.moon_alt_deg > 0.5) {
      spot = Geo.findSpotWindow(MODEL, samples(n.eval_ms, SETTINGS.clearMin));
      if (!spot) {
        for (const add of [30, 60, 90]) {
          const ms = n.eval_ms + add * 60000;
          if (ms >= n.latest_ms) break;
          const m = Astro.moonAltAz(ms, lat, lon, elevM);
          if (m.alt > 0.5) {
            const s2 = Geo.findSpotWindow(MODEL, samples(ms, SETTINGS.clearMin));
            if (s2) {
              spot = s2; wait = add; waitMs = ms;
              n.moon_note = `Blocked at tzeis; clear at ${fmt(ms)} (${Math.round(m.alt)}°)`;
              break;
            }
          }
        }
      }
    }
    n.wait_min = wait;
    n.wait_time_str = wait ? fmt(waitMs) : null;
    n.spot = spot ? {
      name: spot.name, short_name: spot.short_name, x: spot.x, y: spot.y, g: spot.g,
      walk_ft: spot.walk_ft, min_clr: spot.min_clearance_deg,
    } : null;
    const startMs = n.eval_ms + wait * 60000;
    n.frames = [];
    for (let k = 0; k <= 30; k++) {
      const ms = startMs + k * 60000;
      const m = Astro.moonAltAz(ms, lat, lon, elevM);
      n.frames.push([Math.round(m.az * 10) / 10, Math.round(m.alt * 10) / 10, fmt(ms), Astro.compassDirection(m.az)]);
    }
    if (performance.now() - t0 > 60) {
      log.detail("rays", `${i + 1} / ${nights.length} nights • ${nights.slice(0, i + 1).filter(x => x.spot).length} with a clear spot so far`);
      await sleep0();
      t0 = performance.now();
    }
  }
  if (token !== loadToken) return;
  NIGHTS = nights;
  log.ok("rays", `${nights.filter(x => x.spot).length} of ${nights.length} nights have a spot clear for ${SETTINGS.clearMin} min within ${MODEL.walkMax.toLocaleString()} ft`);
  lastLoadSummary = log.finish();
  showResults();
}

// ---------------------------------------------------------------- results UI
function showResults() {
  const hs = MODEL.heightStats;
  const tzNote = MODEL.tz;
  const israel = SETTINGS.israel === "auto" ? Astro.isLikelyIsrael(PLACE.lat, PLACE.lon) : SETTINGS.israel === "israel";
  $("placeBadge").style.display = "block";
  $("placeBadge").innerHTML = `<strong>${esc(PLACE.name)}</strong><br/><span dir="ltr">${esc(PLACE.label !== PLACE.name ? PLACE.label : `${PLACE.lat.toFixed(5)}, ${PLACE.lon.toFixed(5)}`)}</span>
    <div class="src-line">${esc(MODEL.nycMode ? "NYC 3D Building Model" : "OpenStreetMap 3D Model")} &bull; <span dir="ltr">${esc(tzNote)}</span></div>`;
  $("btnShare").style.display = "inline-block";

  const notes = [];
  notes.push({ cls: "info", text: `Buildings: ${MODEL.source}. Streets: ${MODEL.streetSrc}. ${CANDIDATES.length.toLocaleString()} candidate sidewalk spots within ${MODEL.walkMax.toLocaleString()} ft walk.` });
  if (!MODEL.nycMode || hs.default > 0) {
    if (hs.pctEst >= 5) notes.push({ cls: "", text: `${hs.pctEst}% of buildings here have no height data in OpenStreetMap and were assumed to be ${SETTINGS.defaultHeightFt} ft tall (houses ≤ 26 ft, sheds/garages ≤ 12 ft)${hs.pctLv ? `; ${hs.pctLv}% were estimated from floor counts` : ""}. Treat clearances as approximate and adjust the default height in Settings if needed.` });
    else if (hs.pctLv >= 5) notes.push({ cls: "info", text: `${hs.pctLv}% of building heights were estimated from floor counts (≈10 ft per floor).` });
  }
  for (const w of MODEL.warnings) notes.push({ cls: "", text: w });
  const estHint = (!MODEL.nycMode && hs.pctEst >= 5) ? ` &bull; <span style="color:#fde68a">&#9888; ${esc(I18N.t("approxHeightsNote"))}</span>` : "";
  const summaryLabel = lastLoadSummary
    ? `${esc(I18N.t("loadedSummary", { s: lastLoadSummary.total.toFixed(0) }))}${estHint}`
    : `${esc(MODEL.source)}${estHint}`;
  const notesHtml = notes.map(n => `<div class="note ${n.cls}" style="margin-top:6px">${esc(n.text)}</div>`).join("");
  const logHtml = lastLoadSummary ? `<div class="status loadlog show" style="margin:8px 0 0">${lastLoadSummary.html}</div>` : "";
  $("notes").innerHTML = `<details class="note info loadlog-summary"><summary>${summaryLabel}</summary>${notesHtml}${logHtml}</details>`;

  const motz = NIGHTS.filter(n => n.is_motzaei).length;
  $("tabMotzaei").textContent = I18N.t("tabMotzaei", { n: motz });
  $("tabAll").textContent = I18N.t("tabAll", { n: NIGHTS.length });
  $("footRule").textContent = `Year ${SETTINGS.year} • Window: ${SETTINGS.minDays} days after molad (after Yom Kippur in Tishrei, after Tisha B'Av in Av) until ${SOF_LABEL[SETTINGS.sofZman]} • Tzeis = Shkiah + ${SETTINGS.tzeis} min • ${israel ? "Israel (1-day Yom Tov)" : "Diaspora (2-day Yom Tov)"}`;
  $("footData").textContent = `+4 ft parapet buffer, ≥1.5° clearance, 5.5 ft eye level, clear for ${SETTINGS.clearMin} min after tzeis`;
  $("thSpot").textContent = I18N.t("thSpot", { n: SETTINGS.clearMin });
  $("btnModeStable").textContent = I18N.t("modeStable", { n: SETTINGS.clearMin });
  $("btnPdf").style.display = "inline-block";
  $("calSection").classList.add("show");
  const deepLink = location.hash && location.hash.length > 1;
  renderCalendar(!deepLink);
  updateUrl();

  if (deepLink) {
    const found = NIGHTS.find(n => n.civil_date === location.hash.slice(1));
    if (found) openViewer(found.id);
  }
}

function updateUrl() {
  const p = new URLSearchParams();
  p.set("lat", PLACE.lat.toFixed(6));
  p.set("lon", PLACE.lon.toFixed(6));
  p.set("name", PLACE.name);
  if (PLACE.label && PLACE.label !== PLACE.name) p.set("label", PLACE.label);
  p.set("short", SETTINGS.short);
  const cur = Astro.currentHebrewYear(new Date());
  if (SETTINGS.year !== cur) p.set("year", SETTINGS.year);
  if (SETTINGS.tzeis !== 50) p.set("tzeis", SETTINGS.tzeis);
  if (SETTINGS.minDays !== 3) p.set("min", SETTINGS.minDays);
  if (SETTINGS.sofZman !== "15d") p.set("sof", SETTINGS.sofZman);
  if (SETTINGS.clearMin !== 20) p.set("clr", SETTINGS.clearMin);
  if (SETTINGS.israel !== "auto") p.set("yt", SETTINGS.israel);
  if (SETTINGS.walkMaxFt !== 1650) p.set("walk", SETTINGS.walkMaxFt);
  if (SETTINGS.defaultHeightFt !== 30) p.set("defh", SETTINGS.defaultHeightFt);
  if (I18N.code !== "en") p.set("lang", I18N.code);
  history.replaceState(null, "", `${location.pathname}?${p.toString()}${location.hash}`);
}

// ---------------------------------------------------------------- ray tracing for the viewer (exact match to Geo.clearance)
function findClosestSpotAt(azDeg, altDeg) {
  if (altDeg <= 0.5) return null;
  for (const c of CANDIDATES) {
    const tr = traceRay(c.x, c.y, c.g, azDeg, altDeg);
    if (tr.isClear) return { spot: c, trace: tr };
  }
  return null;
}

function raySegIntersect(ox, oy, dx, dy, x1, y1, x2, y2) {
  const sx = x2 - x1, sy = y2 - y1;
  const denom = dx * sy - dy * sx;
  if (Math.abs(denom) < 1e-9) return null;
  const qpx = x1 - ox, qpy = y1 - oy;
  const t = (qpx * sy - qpy * sx) / denom;
  if (t <= 0.5) return null;
  const u = (qpx * dy - qpy * dx) / denom;
  if (u >= -1e-9 && u <= 1.0 + 1e-9) return t;
  return null;
}

function traceRay(ox, oy, groundFt, azDeg, altDeg, maxDist = 1800) {
  const azRad = azDeg * DEG;
  const dx = Math.sin(azRad), dy = Math.cos(azRad);
  const oz = groundFt + 5.5;
  const tanAlt = Math.tan(altDeg * DEG);
  const rx1 = ox + dx * maxDist, ry1 = oy + dy * maxDist;
  const rMinX = Math.min(ox, rx1), rMaxX = Math.max(ox, rx1);
  const rMinY = Math.min(oy, ry1), rMaxY = Math.max(oy, ry1);

  const slices = [];
  let maxObs = 0;
  let limitingId = null;

  for (const b of BUILDINGS) {
    if (b.x1 < rMinX || b.x0 > rMaxX || b.y1 < rMinY || b.y0 > rMaxY) continue;
    let tMin = Infinity, tMax = -Infinity;
    const pts = b.pts;
    for (let i = 0; i < pts.length - 1; i++) {
      const t = raySegIntersect(ox, oy, dx, dy, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]);
      if (t !== null && t <= maxDist) {
        if (t < tMin) tMin = t;
        if (t > tMax) tMax = t;
      }
    }
    if (tMin === Infinity) continue;
    if (tMax <= tMin + 1) tMax = Math.min(maxDist, tMin + 40);
    const dh = b.top - oz;
    const obsAngle = dh > 0 ? Math.atan2(dh, tMin) * RAD : 0;
    const rayZ = oz + tMin * tanAlt;
    const blocks = b.top > rayZ - 1e-6;
    if (obsAngle > maxObs) { maxObs = obsAngle; limitingId = b.id; }
    slices.push({
      id: b.id, tEnter: tMin, tExit: tMax, g: b.g, h: Math.round(b.h),
      roof: b.g + b.h, top: b.top, rayZ, obsAngle, blocks, est: b.est,
    });
  }
  slices.sort((a, b) => a.tEnter - b.tEnter);
  const firstBlock = slices.find(s => s.blocks) || null;
  const clearance = Math.round((altDeg - maxObs) * 10) / 10;
  return {
    ox, oy, g: groundFt, oz, azDeg, altDeg,
    maxObs: Math.round(maxObs * 10) / 10,
    clearance,
    isClear: altDeg > 0.5 && clearance >= 1.5,
    blockingId: firstBlock ? firstBlock.id : null,
    limitingId,
    firstBlock,
    slices,
  };
}

// ---------------------------------------------------------------- calendar table
let currentFilter = "all";
const calBody = $("calBody");

function getFilteredNights() {
  return NIGHTS.filter(n => currentFilter === "all" || n.is_motzaei);
}

function walkStr(ft) {
  if (ft <= 20) return I18N.t("walkZero");
  const mins = Math.max(1, Math.round(ft / 260));
  return I18N.t("walkFmt", { ft: ft.toLocaleString(), m: mins });
}

function renderCalendar(scrollToNext = false) {
  calBody.innerHTML = "";
  const list = getFilteredNights();
  if (!list.length) {
    calBody.innerHTML = `<tr><td colspan="6" style="color:var(--muted);padding:18px;">${esc(I18N.t("noNights"))}</td></tr>`;
    return;
  }
  const viewArrow = I18N.dir === "rtl" ? "&larr;" : "&rarr;";
  const nowMs = Date.now();
  const isUpcoming = n => nowMs < (n.end_ms || (n.eval_ms + 12 * 3600000));
  const nextNight = list.find(isUpcoming) || null;
  let nextRowEl = null;

  for (const n of list) {
    const f0 = n.frames[0];
    let tagHtml = "";
    if (n.special_tag) {
      const tagCls = n.special_tag === "Motzaei YK" ? "tag-yk" : (n.special_tag === "Motzaei 9 Av" ? "tag-9a" : "tag-ms");
      tagHtml = `<span class="tag ${tagCls}">${esc(I18N.tag(n.special_tag))}</span>`;
    }
    if (nextNight && n.id === nextNight.id) {
      tagHtml = `<span class="tag tag-next">${esc(I18N.t("nextUpTag"))}</span>` + tagHtml;
    }
    const tr = document.createElement("tr");
    if (nextNight && n.id === nextNight.id) {
      tr.className = "next-night";
      nextRowEl = tr;
    } else if (!isUpcoming(n)) {
      tr.className = "past-night";
    }
    tr.onclick = () => openViewer(n.id);

    let spotHtml;
    if (n.spot) {
      const waitNote = n.wait_min ? ` <span style="color:#fcd34d">${esc(I18N.t("atWaitTime", { t: n.wait_time_str }))}</span>` : "";
      spotHtml = `<div class="spot-name">${esc(n.spot.short_name)}${waitNote}</div>
        <div class="spot-meta">${esc(I18N.t("clearWindowMeta", { walk: walkStr(n.spot.walk_ft), clr: n.spot.min_clr.toFixed(1), m: SETTINGS.clearMin }))}</div>`;
    } else if (n.moon_alt_deg <= 0.5) {
      spotHtml = `<div class="spot-none">${esc(I18N.t("moonNotUp"))}</div>
        <div class="spot-meta">${esc(n.moon_note || I18N.t("altShort", { n: f0[1].toFixed(1) }))} &mdash; ${esc(I18N.t("useAnotherNight"))}</div>`;
    } else {
      spotHtml = `<div class="spot-none">${esc(I18N.t("blockedWithin", { n: MODEL.walkMax.toLocaleString() }))}</div>
        <div class="spot-meta">${esc(I18N.t("moonTooLow", { alt: f0[1].toFixed(1) }))}</div>`;
    }

    const compLoc = I18N.compass(f0[3]);
    tr.innerHTML = `
      <td class="td-month"><div class="m-name">${esc(I18N.month(n.month_name))}</div><div class="m-win">${esc(n.win_earliest)} &ndash; ${esc(n.win_latest)}</div></td>
      <td class="td-night"><strong>${esc(n.date_disp)}</strong>${tagHtml}<div class="m-win">${esc(I18N.hebDate(n.heb_date))}</div></td>
      <td class="td-tzeis"><strong>${esc(n.tzeis_str)}</strong></td>
      <td class="td-moon"><strong>${esc(compLoc)} (${f0[0].toFixed(1)}&deg;)</strong><div class="m-win">${esc(I18N.t("altShort", { n: f0[1].toFixed(1) }))} &bull; ${esc(I18N.t("litPct", { n: n.illum_pct }))}</div></td>
      <td class="td-spot">${spotHtml}</td>
      <td class="td-action" style="text-align:right;"><button class="view-btn">${esc(I18N.t("view3d"))} ${viewArrow}</button></td>
    `;
    calBody.appendChild(tr);
  }
  if (scrollToNext && nextRowEl) {
    requestAnimationFrame(() => nextRowEl.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    renderCalendar(true);
  };
});

// ---------------------------------------------------------------- init
function localizeDynamicOptions() {
  const cur = Astro.currentHebrewYear(new Date());
  for (const o of $("setYear").options) {
    const y = parseInt(o.value, 10);
    o.textContent = y === cur ? `${y} (${I18N.t("currentTag")})` : String(y);
  }
  for (const o of $("setTzeis").options) {
    o.textContent = `${o.value} ${I18N.t("minUnit")}`;
  }
  for (const o of $("setClear").options) {
    o.textContent = I18N.t("minAfterTzeis", { n: o.value });
  }
  for (const o of $("setWalk").options) {
    const ft = parseInt(o.value, 10);
    o.textContent = walkStr(ft);
  }
  document.querySelectorAll("#examples .chip").forEach((c, i) => {
    if (EXAMPLES[i]) c.textContent = I18N.t(EXAMPLES[i].key);
  });
}

function init() {
  const params = new URLSearchParams(location.search);
  I18N.init(params);
  initSettingsUI(params);

  const ex = $("examples");
  for (const e of EXAMPLES) {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = I18N.t(e.key);
    c.onclick = () => { renderResults([]); choosePlace(e, e.short); };
    ex.appendChild(c);
  }
  localizeDynamicOptions();

  const langSel = $("langSelect");
  if (langSel) {
    langSel.value = I18N.code;
    langSel.onchange = () => {
      I18N.setLang(langSel.value);
      if (PLACE) updateUrl();
    };
  }
  I18N.onChange(() => {
    localizeDynamicOptions();
    if (NIGHTS.length && MODEL && SETTINGS) {
      const motz = NIGHTS.filter(n => n.is_motzaei).length;
      $("tabMotzaei").textContent = I18N.t("tabMotzaei", { n: motz });
      $("tabAll").textContent = I18N.t("tabAll", { n: NIGHTS.length });
      $("thSpot").textContent = I18N.t("thSpot", { n: SETTINGS.clearMin });
      $("btnModeStable").textContent = I18N.t("modeStable", { n: SETTINGS.clearMin });
      renderCalendar();
      if (typeof recomputeAndRender === "function" && $("viewerOverlay").classList.contains("open")) {
        recomputeAndRender();
      }
    }
  });

  initSearchBox();
  $("searchForm").addEventListener("submit", ev => {
    ev.preventDefault();
    if (Date.now() - justPicked < 1000) return; // Enter already picked a highlighted result
    if (searchActive >= 0) { pickResult(searchActive); return; }
    doSearch($("q").value);
  });
  $("btnApply").onclick = () => {
    if (!PLACE) return;
    const s = readSettingsFromUI();
    // Calendar-only changes (year, tzeis, window, sof zman, clear time, Yom Tov, label) don't need new map data
    if (MODEL && SETTINGS && s.walkMaxFt === SETTINGS.walkMaxFt && s.defaultHeightFt === SETTINGS.defaultHeightFt) {
      SETTINGS = s;
      PLACE.short = s.short;
      PLACE.atLabel = `Outside ${s.short}`;
      SHUL.name = SHUL.short_name = PLACE.atLabel;
      $("btnApply").disabled = true;
      $("calSection").classList.remove("show");
      const token = ++loadToken;
      const log = makeLoadLog(`Recomputing ${PLACE.name} with new settings`);
      log.start("model", "Using already-downloaded 3D model", `${BUILDINGS.length.toLocaleString()} buildings`);
      log.ok("model", "no new lookups needed");
      solveNights(token, log);
    } else {
      loadPlace();
    }
  };
  $("btnShare").onclick = async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      $("btnShare").textContent = "✓ " + I18N.t("linkCopied");
    } catch {
      prompt(I18N.t("copyLink") + ":", location.href);
    }
    setTimeout(() => { $("btnShare").innerHTML = `&#128279; <span data-i18n="copyLink">${esc(I18N.t("copyLink"))}</span>`; }, 1800);
  };
  $("btnGeo").onclick = () => {
    if (!navigator.geolocation) { setStatus("Geolocation isn't available in this browser.", "error"); return; }
    setStatus("Getting your location…");
    navigator.geolocation.getCurrentPosition(async pos => {
      const { latitude: lat, longitude: lon } = pos.coords;
      const rv = await Geo.reverseGeocode(lat, lon);
      choosePlace({ lat, lon, label: rv.label, name: rv.name || "My location" });
    }, err => setStatus(`Couldn't get your location: ${esc(err.message)}`, "error"), { enableHighAccuracy: true, timeout: 15000 });
  };

  const lat = parseFloat(params.get("lat")), lon = parseFloat(params.get("lon"));
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    choosePlace({ lat, lon, name: params.get("name") || "Selected location", label: params.get("label") || params.get("name") || `${lat}, ${lon}` });
  } else if (params.get("q")) {
    $("q").value = params.get("q");
    doSearch(params.get("q"));
  }
}
window.addEventListener("DOMContentLoaded", init);

// Hybrid geodata loader + line-of-sight engine for any location.
//  - Inside NYC: NYC Open Data 3D Building Footprints (5zhs-2jue) + Street Centerlines (inkn-q76z),
//    with OpenStreetMap buildings merged in for any area just outside the city line.
//  - Elsewhere: OpenStreetMap (Overpass API) buildings + streets, Open-Meteo terrain elevation.
// Generalizes src/visibility.py (which was hard-coded to W 91st St and the 29° Manhattan grid).

const Geo = (() => {
  const FT = 3.280839895; // feet per meter
  const DEG = Math.PI / 180, RAD = 180 / Math.PI;
  const PARAPET_FT = 4.0;
  const EYE_FT = 5.5;
  const MIN_CLEARANCE = 1.5;
  const RAY_MAX_FT = 1800;
  const NYC_BOX = { s: 40.49, n: 40.92, w: -74.26, e: -73.69 };

  const OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
  ];

  const COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const compass8 = azDeg => COMPASS8[Math.floor((((azDeg % 360) + 360) % 360 + 22.5) / 45) % 8];

  function inNycBox(lat, lon) {
    return lat >= NYC_BOX.s && lat <= NYC_BOX.n && lon >= NYC_BOX.w && lon <= NYC_BOX.e;
  }

  // ------------------------------------------------------------------ network
  const HTTP_HINTS = { 429: "too many requests", 502: "bad gateway", 503: "server unavailable", 504: "gateway timeout — server overloaded" };
  const fmtBytes = n => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`;

  // fetch + JSON with timeout, optional byte-progress callback and optional external abort signal
  async function fetchJson(url, opts = {}, timeoutMs = 45000, onBytes = null, extSignal = null) {
    const ctl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, timeoutMs);
    const onExt = () => ctl.abort();
    if (extSignal) { if (extSignal.aborted) ctl.abort(); else extSignal.addEventListener("abort", onExt); }
    const host = (() => { try { return new URL(url).host; } catch { return url; } })();
    try {
      const r = await fetch(url, { ...opts, signal: ctl.signal });
      if (!r.ok) throw new Error(`${host}: HTTP ${r.status}${HTTP_HINTS[r.status] ? ` (${HTTP_HINTS[r.status]})` : ""}`);
      let text;
      if (onBytes && r.body && r.body.getReader) {
        const reader = r.body.getReader();
        const chunks = [];
        let n = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          n += value.length;
          onBytes(n);
        }
        const all = new Uint8Array(n);
        let o = 0;
        for (const c of chunks) { all.set(c, o); o += c.length; }
        text = new TextDecoder().decode(all);
      } else {
        text = await r.text();
      }
      try {
        return JSON.parse(text);
      } catch {
        throw new Error(`${host}: unexpected response (not JSON)`);
      }
    } catch (e) {
      if (e.name === "AbortError") throw new Error(timedOut ? `${host}: no answer after ${Math.round(timeoutMs / 1000)} s` : `${host}: cancelled`);
      if (e instanceof TypeError) throw new Error(`${host}: network error (${e.message})`);
      throw e;
    } finally {
      clearTimeout(timer);
      if (extSignal) extSignal.removeEventListener("abort", onExt);
    }
  }

  // ------------------------------------------------------------------ projection
  function makeProjection(lat0, lon0) {
    const mLat = 111132.954;
    const mLon = 111319.491 * Math.cos(lat0 * DEG);
    return {
      lat0, lon0,
      toXY: (lat, lon) => [(lon - lon0) * mLon * FT, (lat - lat0) * mLat * FT],
      toLatLon: (x, y) => [lat0 + y / FT / mLat, lon0 + x / FT / mLon],
      box: radiusM => ({
        s: lat0 - radiusM / mLat, n: lat0 + radiusM / mLat,
        w: lon0 - radiusM / mLon, e: lon0 + radiusM / mLon,
      }),
    };
  }

  // ------------------------------------------------------------------ geocoding
  function photonLabel(p) {
    const street = [p.housenumber, p.street].filter(Boolean).join(" ");
    const parts = [
      p.name && p.name !== street ? p.name : null,
      street || null,
      p.city || p.town || p.village || p.district || p.county,
      p.state,
      p.country,
    ].filter(Boolean);
    return [...new Set(parts)].join(", ");
  }

  // autocomplete=true: search-as-you-type (Photon + NYC GeoSearch autocomplete only; Nominatim forbids autocomplete)
  async function geocode(q, { autocomplete = false, signal = null } = {}) {
    q = (q || "").trim();
    if (!q) return [];
    const m = q.match(/^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/);
    if (m) {
      const lat = +m[1], lon = +m[2];
      if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        return [{ label: `${lat.toFixed(6)}, ${lon.toFixed(6)}`, name: "Selected location", lat, lon, source: "Coordinates" }];
      }
    }
    const enc = encodeURIComponent(q);
    const photonP = fetchJson(`https://photon.komoot.io/api/?q=${enc}&limit=6&lang=en`, {}, 15000, null, signal)
      .then(gj => (gj.features || []).map(f => ({
        label: photonLabel(f.properties),
        name: f.properties.name || [f.properties.housenumber, f.properties.street].filter(Boolean).join(" "),
        lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0], source: "OpenStreetMap",
      })))
      .catch(() => null);
    const nycUrl = autocomplete
      ? `https://geosearch.planninglabs.nyc/v2/autocomplete?text=${enc}&size=3`
      : `https://geosearch.planninglabs.nyc/v2/search?text=${enc}&size=3`;
    const nycP = fetchJson(nycUrl, {}, 12000, null, signal)
      .then(gj => (gj.features || [])
        .filter(f => autocomplete || (f.properties.confidence ?? 0) >= 0.8)
        .map(f => {
          // NYC GeoSearch returns ALL-CAPS addresses ("210 WEST 91 STREET"); tidy to "210 W 91st St"
          let name = f.properties.name || "";
          let label = f.properties.label || name;
          if (name && name === name.toUpperCase()) {
            const m = name.match(/^(\d+[A-Z]?(?:-\d+)?)\s+(.*)$/);
            const nice = m ? `${m[1]} ${cleanStreetName(m[2])}` : cleanStreetName(name);
            label = label.startsWith(name) ? nice + label.slice(name.length) : label;
            name = nice;
          }
          return { label, name, lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0], source: "NYC GeoSearch" };
        }))
      .catch(() => []);
    let [photon, nyc] = await Promise.all([photonP, nycP]);
    if (signal && signal.aborted) return [];
    if ((!photon || photon.length === 0) && !autocomplete) {
      photon = await fetchJson(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&accept-language=en&q=${enc}`, {}, 15000)
        .then(arr => arr.map(r => ({
          label: r.display_name, name: r.name || r.display_name.split(",")[0],
          lat: +r.lat, lon: +r.lon, source: "OpenStreetMap",
        })))
        .catch(() => []);
    }
    photon = photon || [];
    const nycLikely = (photon.length && inNycBox(photon[0].lat, photon[0].lon)) ||
      /\b(new york|nyc|ny\s*\d{5}|manhattan|brooklyn|queens|bronx|staten island)\b/i.test(q);
    const merged = nycLikely ? [...nyc, ...photon] : photon;
    const out = [];
    for (const r of merged) {
      if (!out.some(o => Math.abs(o.lat - r.lat) < 0.0003 && Math.abs(o.lon - r.lon) < 0.0004)) out.push(r);
    }
    return out.slice(0, 8);
  }

  async function reverseGeocode(lat, lon) {
    try {
      const gj = await fetchJson(`https://photon.komoot.io/reverse?lat=${lat}&lon=${lon}&lang=en`, {}, 10000);
      const f = (gj.features || [])[0];
      if (f) return { label: photonLabel(f.properties), name: f.properties.name || [f.properties.housenumber, f.properties.street].filter(Boolean).join(" ") };
    } catch { /* ignore */ }
    return { label: `${lat.toFixed(6)}, ${lon.toFixed(6)}`, name: "My location" };
  }

  // ------------------------------------------------------------------ timezone + terrain
  async function fetchTimezone(lat, lon) {
    try {
      const j = await fetchJson(`https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(5)}&longitude=${lon.toFixed(5)}&timezone=auto&forecast_days=1&daily=sunset`, {}, 15000);
      if (j.timezone) return { tz: j.timezone, elevM: Number.isFinite(j.elevation) ? j.elevation : null, fallback: false };
    } catch { /* fall through */ }
    return { tz: Intl.DateTimeFormat().resolvedOptions().timeZone, elevM: null, fallback: true };
  }

  async function fetchElevationGrid(box, n = 10) {
    const lats = [], lons = [];
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        lats.push((box.s + (box.n - box.s) * i / (n - 1)).toFixed(5));
        lons.push((box.w + (box.e - box.w) * j / (n - 1)).toFixed(5));
      }
    }
    const j = await fetchJson(`https://api.open-meteo.com/v1/elevation?latitude=${lats.join(",")}&longitude=${lons.join(",")}`, {}, 20000);
    const el = j.elevation;
    if (!Array.isArray(el) || el.length !== n * n) throw new Error("Bad elevation response");
    // Returns ground elevation (ft) at lat/lon via bilinear interpolation
    return (lat, lon) => {
      const fi = Math.max(0, Math.min(n - 1, (lat - box.s) / (box.n - box.s) * (n - 1)));
      const fj = Math.max(0, Math.min(n - 1, (lon - box.w) / (box.e - box.w) * (n - 1)));
      const i0 = Math.min(n - 2, Math.floor(fi)), j0 = Math.min(n - 2, Math.floor(fj));
      const di = fi - i0, dj = fj - j0;
      const v = (i, k) => el[i * n + k];
      const z = v(i0, j0) * (1 - di) * (1 - dj) + v(i0 + 1, j0) * di * (1 - dj) +
        v(i0, j0 + 1) * (1 - di) * dj + v(i0 + 1, j0 + 1) * di * dj;
      return z * FT;
    };
  }

  // ------------------------------------------------------------------ NYC Open Data
  async function socrataGeo(dataset, fields, box, limit, onBytes = null) {
    let lastErr = null;
    for (const col of ["the_geom", "shape", "geom"]) {
      const params = new URLSearchParams({
        "$where": `within_box(${col}, ${box.n}, ${box.w}, ${box.s}, ${box.e})`,
        "$select": [col, ...fields].join(","),
        "$limit": String(limit),
      });
      try {
        return await fetchJson(`https://data.cityofnewyork.us/resource/${dataset}.geojson?${params}`, {}, 60000, onBytes);
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr;
  }

  // ------------------------------------------------------------------ OpenStreetMap
  // Asks the public Overpass servers in a staggered race: the first server starts immediately,
  // the next one joins after `staggerMs` (or right away if a server fails). First good answer wins;
  // the rest are cancelled. onState(host, text) reports what each server is doing.
  function fetchOverpass(box, { timeoutMs = 60000, staggerMs = 6000, onState = () => {}, signal = null } = {}) {
    const bb = `${box.s.toFixed(6)},${box.w.toFixed(6)},${box.n.toFixed(6)},${box.e.toFixed(6)}`;
    const srvTimeout = Math.max(25, Math.round(timeoutMs / 1000) - 5);
    const hw = `way["highway"]["highway"!~"^(motorway|motorway_link|construction|proposed|abandoned|raceway|platform|elevator|corridor|bus_stop|services|rest_area|razed|disused)$"]["area"!="yes"]`;
    const q = `[out:json][timeout:${srvTimeout}];(way["building"](${bb});relation["building"](${bb});${hw}(${bb}););out tags geom qt;`;
    const body = "data=" + encodeURIComponent(q);
    const ctl = new AbortController();
    const errors = [];
    return new Promise((resolve, reject) => {
      let next = 0, pending = 0, settled = false;
      const timers = [];
      const finish = () => { settled = true; timers.forEach(clearTimeout); };
      const launch = () => {
        if (settled || next >= OVERPASS_ENDPOINTS.length) return;
        const ep = OVERPASS_ENDPOINTS[next++];
        const host = new URL(ep).host;
        const t0 = Date.now();
        pending++;
        onState(host, "asking…");
        fetchJson(ep, {
          method: "POST",
          body,
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        }, timeoutMs, n => { if (!settled) onState(host, `receiving ${fmtBytes(n)}…`); }, ctl.signal)
          .then(j => {
            if (j.remark && /error|timed out|out of memory|runtime/i.test(j.remark)) throw new Error(`${host}: ${j.remark.trim().slice(0, 120)}`);
            if (settled) return;
            finish();
            ctl.abort();
            onState(host, `answered in ${((Date.now() - t0) / 1000).toFixed(0)} s ✓`);
            resolve({ data: j, host, secs: (Date.now() - t0) / 1000 });
          })
          .catch(e => {
            pending--;
            if (settled) return;
            errors.push(e.message);
            onState(host, `failed — ${e.message.replace(`${host}: `, "")}`);
            launch(); // a failure brings in the next server immediately
            if (pending === 0 && next >= OVERPASS_ENDPOINTS.length) {
              finish();
              reject(new Error(errors.join("; ")));
            }
          });
      };
      launch();
      if (signal) signal.addEventListener("abort", () => {
        if (settled) return;
        finish();
        ctl.abort();
        reject(new Error("skipped"));
      });
      for (let k = 1; k < OVERPASS_ENDPOINTS.length; k++) {
        timers.push(setTimeout(() => { if (next <= k) launch(); }, staggerMs * k));
      }
    });
  }

  function parseLenM(v) {
    if (v === undefined || v === null || v === "") return null;
    const s = String(v).trim().replace(",", ".");
    let m = s.match(/^(\d+(?:\.\d+)?)\s*(m|meters?|metres?)?$/i);
    if (m) return parseFloat(m[1]);
    m = s.match(/^(\d+(?:\.\d+)?)\s*(ft|feet|')$/i);
    if (m) return parseFloat(m[1]) / FT;
    m = s.match(/^(\d+)'\s*(\d+(?:\.\d+)?)"?$/);
    if (m) return (parseInt(m[1], 10) + parseFloat(m[2]) / 12) / FT;
    m = s.match(/(\d+(?:\.\d+)?)/);
    return m ? parseFloat(m[1]) : null;
  }

  const SMALL_BUILDINGS = new Set(["garage", "garages", "shed", "carport", "hut", "kiosk", "cabin", "roof", "toilets", "greenhouse", "service", "transformer_tower"]);
  const HOUSE_BUILDINGS = new Set(["house", "detached", "semidetached_house", "bungalow", "terrace", "farm", "static_caravan"]);

  // Returns { h: height_ft, est: "measured" | "levels" | "default" }
  function osmHeightFt(tags, defaultFt) {
    const hM = parseLenM(tags.height) ?? parseLenM(tags["building:height"]);
    if (hM !== null && hM > 0.5) return { h: hM * FT, est: "measured" };
    const lv = parseFloat(tags["building:levels"]);
    if (Number.isFinite(lv) && lv > 0) {
      const roofH = parseLenM(tags["roof:height"]);
      const roofLv = parseFloat(tags["roof:levels"]) || 0;
      const roof = roofH !== null ? roofH : roofLv * 2.0;
      return { h: (lv * 3.1 + roof + 0.6) * FT, est: "levels" };
    }
    const kind = tags.building;
    if (SMALL_BUILDINGS.has(kind)) return { h: Math.min(defaultFt, 12), est: "default" };
    if (HOUSE_BUILDINGS.has(kind)) return { h: Math.min(defaultFt, 26), est: "default" };
    return { h: defaultFt, est: "default" };
  }

  const samePt = (a, b) => Math.abs(a.lat - b.lat) < 1e-9 && Math.abs(a.lon - b.lon) < 1e-9;

  function joinWays(ways) {
    const rings = [];
    const pool = ways.filter(w => w && w.length >= 2).map(w => w.slice());
    while (pool.length) {
      let cur = pool.shift();
      let guard = 0;
      while (!samePt(cur[0], cur[cur.length - 1]) && guard++ < 1000) {
        const end = cur[cur.length - 1];
        const idx = pool.findIndex(w => samePt(w[0], end) || samePt(w[w.length - 1], end));
        if (idx < 0) break;
        let w = pool.splice(idx, 1)[0];
        if (!samePt(w[0], end)) w = w.reverse();
        cur = cur.concat(w.slice(1));
      }
      if (cur.length >= 4) rings.push(cur);
    }
    return rings;
  }

  // ------------------------------------------------------------------ geometry helpers
  function pointInRing(px, py, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > py) !== (yj > py) && px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi) inside = !inside;
    }
    return inside;
  }

  function makeBuilding(ringXY, g, h, est) {
    const pts = [];
    for (const [x, y] of ringXY) {
      const rx = Math.round(x * 10) / 10, ry = Math.round(y * 10) / 10;
      const last = pts[pts.length - 1];
      if (!last || last[0] !== rx || last[1] !== ry) pts.push([rx, ry]);
    }
    if (pts.length >= 3 && (pts[0][0] !== pts[pts.length - 1][0] || pts[0][1] !== pts[pts.length - 1][1])) pts.push([pts[0][0], pts[0][1]]);
    if (pts.length < 4) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of pts) {
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    return { pts, g, h, top: g + h + PARAPET_FT, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, x0, y0, x1, y1, est };
  }

  // Simple uniform grid for fast spatial lookups of buildings (by bbox)
  function buildGrid(items, cell = 150) {
    const map = new Map();
    for (let idx = 0; idx < items.length; idx++) {
      const b = items[idx];
      for (let gx = Math.floor(b.x0 / cell); gx <= Math.floor(b.x1 / cell); gx++) {
        for (let gy = Math.floor(b.y0 / cell); gy <= Math.floor(b.y1 / cell); gy++) {
          const k = gx + "," + gy;
          let arr = map.get(k);
          if (!arr) map.set(k, arr = []);
          arr.push(idx);
        }
      }
    }
    return {
      near(x, y) { return map.get(Math.floor(x / cell) + "," + Math.floor(y / cell)) || []; },
    };
  }

  // ------------------------------------------------------------------ street names
  function ordinal(n) {
    const suf = (n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
    return `${n}${suf}`;
  }
  const UPPER_ABBR = { W: "W", E: "E", N: "N", S: "S", ST: "St", AVE: "Ave", AV: "Ave", DR: "Dr", PKWY: "Pkwy", PLZ: "Plz", PL: "Pl", RD: "Rd", BLVD: "Blvd", LN: "Ln", CT: "Ct", TER: "Ter", HWY: "Hwy", EXPY: "Expy", SQ: "Sq" };

  function cleanStreetName(raw) {
    let name = (raw || "").trim();
    if (!name) return "";
    if (name === name.toUpperCase() && /[A-Z]/.test(name)) {
      // NYC CSCL labels like "W 91 ST", "AMSTERDAM AVE"
      name = name.split(/\s+/).map(w => {
        if (UPPER_ABBR[w]) return UPPER_ABBR[w];
        if (/^\d+$/.test(w)) return ordinal(parseInt(w, 10));
        return w.charAt(0) + w.slice(1).toLowerCase();
      }).join(" ");
    }
    return name
      .replace(/^West /, "W ").replace(/^East /, "E ").replace(/^North /, "N ").replace(/^South /, "S ")
      .replace(/ Street$/, " St").replace(/ Avenue$/, " Ave").replace(/ Drive$/, " Dr").replace(/ Road$/, " Rd")
      .replace(/ Boulevard$/, " Blvd").replace(/ Place$/, " Pl").replace(/ Parkway$/, " Pkwy").replace(/ Lane$/, " Ln")
      .replace(/ Court$/, " Ct").replace(/ Terrace$/, " Ter");
  }
  const shortStreet = s => s.replace(/ (St|Ave|Rd|Dr|Blvd|Pl|Ln|Ct|Ter|Way)$/, "").replace(/^Riverside$/, "Riverside");

  const OSM_ROAD_WIDTH_FT = {
    trunk: 80, primary: 64, primary_link: 34, secondary: 56, secondary_link: 30, tertiary: 44, tertiary_link: 28,
    residential: 34, unclassified: 30, living_street: 22, pedestrian: 22, service: 18, road: 30,
  };
  const OSM_EXCLUDE = new Set(["motorway", "motorway_link", "trunk_link", "construction", "proposed", "abandoned", "raceway",
    "bus_guideway", "escape", "platform", "elevator", "corridor", "via_ferrata", "services", "rest_area", "razed", "disused"]);
  const NYC_EXCLUDE_RW = new Set(["2", "3", "4", "9", "12", "13", "14"]);

  // ------------------------------------------------------------------ main loader
  // `log` receives step updates: start(key, title, sub), detail(key, textOrLines), ok/warn/fail(key, text)
  const NOOP_LOG = { start() {}, detail() {}, ok() {}, warn() {}, fail() {} };
  const countOsm = j => {
    let b = 0, s = 0;
    for (const el of (j && j.elements) || []) {
      if (el.tags && el.tags.building) b++;
      else if (el.tags && el.tags.highway) s++;
    }
    return { b, s };
  };

  async function loadLocation(place, settings, log = NOOP_LOG) {
    const L = { ...NOOP_LOG, ...log };
    const { lat, lon } = place;
    const proj = makeProjection(lat, lon);
    let walkMax = settings.walkMaxFt || 1650;
    let fetchRadiusM = Math.max(650, (walkMax + 1150) / FT);
    let box = proj.box(fetchRadiusM);
    const defaultHFt = settings.defaultHeightFt || 30;
    const warnings = [];
    const nycMode = inNycBox(lat, lon);

    L.start("tz", "Timezone & ground elevation", "api.open-meteo.com");
    const tzP = fetchTimezone(lat, lon);
    const elevP = fetchElevationGrid(box).catch(() => null);
    Promise.all([tzP, elevP]).then(([tz, el]) => {
      if (tz.fallback) L.warn("tz", `Timezone lookup failed — using your browser's (${tz.tz})`);
      else L.ok("tz", `${tz.tz}${tz.elevM !== null ? ` • ground ≈ ${Math.round(tz.elevM)} m above sea level` : ""}${el ? " • 100-point terrain grid" : " • terrain grid unavailable"}`);
    });

    const serverStates = key => {
      const st = {};
      return (host, text) => { st[host] = text; L.detail(key, Object.entries(st).map(([h, t]) => `${h}: ${t}`)); };
    };

    let nycBuildingsGj = null, nycStreetsGj = null, osm = null;
    if (nycMode) {
      const socrataStep = (key, title, dataset, fields, limit, noun) => {
        L.start(key, title, "data.cityofnewyork.us");
        let bytes = 0;
        return socrataGeo(dataset, fields, box, limit, n => { bytes = n; L.detail(key, `receiving ${fmtBytes(n)}…`); })
          .then(gj => { L.ok(key, `${(gj.features || []).length.toLocaleString()} ${noun}${bytes ? ` (${fmtBytes(bytes)})` : ""}`); return gj; })
          .catch(e => { L.fail(key, e.message); warnings.push(`${title} failed: ${e.message}`); return null; });
      };
      L.start("osm", "OpenStreetMap buildings outside the NYC dataset", "Overpass API • optional, only matters near the city line");
      const osmAbort = new AbortController();
      const osmP = fetchOverpass(box, { timeoutMs: 40000, staggerMs: 4000, onState: serverStates("osm"), signal: osmAbort.signal })
        .then(r => { const c = countOsm(r.data); L.ok("osm", `${c.b.toLocaleString()} buildings from ${r.host} in ${r.secs.toFixed(0)} s`); return r.data; })
        .catch(e => {
          if (e.message === "skipped") L.warn("osm", "Servers slow — skipped; using NYC data only");
          else { L.warn("osm", "Unavailable — using NYC data only"); console.warn("Overpass:", e.message); }
          return null;
        });
      [nycBuildingsGj, nycStreetsGj] = await Promise.all([
        socrataStep("nycb", "NYC 3D building footprints", "5zhs-2jue", ["height_roof", "ground_elevation"], 50000, "footprints"),
        socrataStep("nycs", "NYC street centerlines", "inkn-q76z", ["stname_label", "full_street_name", "streetwidth", "rw_type"], 20000, "street segments"),
      ]);
      // With NYC data in hand, give OpenStreetMap at most 8 more seconds
      const grace = nycBuildingsGj ? 8000 : 40000;
      const graceTimer = setTimeout(() => osmAbort.abort(), grace);
      osm = await osmP;
      clearTimeout(graceTimer);
      if (!osm && nycBuildingsGj) warnings.push("OpenStreetMap was slow or unavailable, so only NYC Open Data was used (this only matters within ~200 ft of the city line).");
    } else {
      L.start("osm", "OpenStreetMap buildings & streets", `Overpass API • ${Math.round(fetchRadiusM)} m radius • asking public servers in turn`);
      let res, retried = false;
      try {
        res = await fetchOverpass(box, { timeoutMs: 60000, staggerMs: 6000, onState: serverStates("osm") });
      } catch (e1) {
        retried = true;
        L.warn("osm", `Every server failed for a ${Math.round(fetchRadiusM)} m radius`);
        const r2 = Math.max(420, Math.round(fetchRadiusM * 0.6));
        L.start("osm2", "Retrying with a smaller area", `Overpass API • ${r2} m radius`);
        try {
          res = await fetchOverpass(proj.box(r2), { timeoutMs: 45000, staggerMs: 4000, onState: serverStates("osm2") });
        } catch (e2) {
          L.fail("osm2", "Every server failed again");
          throw new Error(`All OpenStreetMap servers are busy or unreachable right now. ${e2.message}`);
        }
        fetchRadiusM = r2;
        box = proj.box(r2);
        walkMax = Math.min(walkMax, Math.max(500, Math.round((r2 * FT - 900) / 50) * 50));
        warnings.push(`The map servers were busy, so a smaller area was loaded (${r2} m radius). Spots are limited to ${walkMax.toLocaleString()} ft walk and distant tall buildings may be missing.`);
        const c = countOsm(res.data);
        L.ok("osm2", `${c.b.toLocaleString()} buildings, ${c.s.toLocaleString()} street segments from ${res.host} in ${res.secs.toFixed(0)} s`);
      }
      if (!retried) {
        const c = countOsm(res.data);
        L.ok("osm", `${c.b.toLocaleString()} buildings, ${c.s.toLocaleString()} street segments from ${res.host} in ${res.secs.toFixed(0)} s`);
      }
      osm = res.data;
    }
    const [tzInfo, elevAt] = await Promise.all([tzP, elevP]);
    if (tzInfo.fallback) warnings.push(`Could not determine the location's timezone; using your browser's (${tzInfo.tz}).`);

    L.start("model", "Building 3D model & walking network", "");
    // ---------------- buildings
    const buildings = [];
    const nycAllRings = []; // includes low structures (for de-duplicating OSM)
    const nycGrounds = [];
    let nNyc = 0, nOsm = 0;
    const est = { measured: 0, levels: 0, default: 0 };

    if (nycBuildingsGj && nycBuildingsGj.features) {
      const raw = [];
      for (const f of nycBuildingsGj.features) {
        const p = f.properties || {}, geom = f.geometry;
        if (!geom) continue;
        const h = parseFloat(p.height_roof) || 0;
        const g = p.ground_elevation !== undefined && p.ground_elevation !== null ? parseFloat(p.ground_elevation) : null;
        if (Number.isFinite(g)) nycGrounds.push(g);
        const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
        for (const poly of polys) {
          if (!poly[0]) continue;
          const ring = poly[0].map(pt => proj.toXY(pt[1], pt[0]));
          nycAllRings.push(ring);
          if (h > 5) raw.push([ring, Number.isFinite(g) ? g : null, h]);
        }
      }
      nycGrounds.sort((a, b) => a - b);
      const med = nycGrounds.length ? nycGrounds[Math.floor(nycGrounds.length / 2)] : (tzInfo.elevM ?? 20) * FT;
      for (const [ring, g, h] of raw) {
        const b = makeBuilding(ring, g !== null ? g : med, h, "measured");
        if (b) { b.src = "nyc"; buildings.push(b); nNyc++; }
      }
    }

    // OSM ground elevation fallback
    const originGroundFallback = (tzInfo.elevM ?? 20) * FT;
    const groundAtLL = (la, lo) => (elevAt ? elevAt(la, lo) : originGroundFallback);

    const osmStreetsRaw = [];
    if (osm && osm.elements) {
      // Index NYC rings for de-dup
      const nycIdxItems = nycAllRings.map(r => {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const [x, y] of r) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
        return { r, x0, y0, x1, y1 };
      });
      const nycGrid = buildGrid(nycIdxItems, 150);
      // An OSM building is only used where the NYC dataset has no footprint within 200 ft,
      // i.e. genuinely outside NYC coverage (across the city line). Inside the city NYC data wins.
      const COVER_FT = 200;
      const coveredByNyc = (x, y) => {
        for (let dx = -COVER_FT; dx <= COVER_FT; dx += 100) {
          for (let dy = -COVER_FT; dy <= COVER_FT; dy += 100) {
            for (const i of nycGrid.near(x + dx, y + dy)) {
              const it = nycIdxItems[i];
              const cx = Math.max(it.x0, Math.min(x, it.x1)), cy = Math.max(it.y0, Math.min(y, it.y1));
              if (Math.hypot(cx - x, cy - y) <= COVER_FT) return true;
            }
          }
        }
        return false;
      };

      for (const el of osm.elements) {
        const tags = el.tags || {};
        if (tags.building && tags.building !== "no") {
          if (tags.location === "underground" || parseFloat(tags.layer) < 0 || tags["building:part"]) continue;
          let rings = [];
          if (el.type === "way" && el.geometry) rings = [el.geometry];
          else if (el.type === "relation" && el.members) {
            rings = joinWays(el.members.filter(m => m.type === "way" && (m.role === "outer" || m.role === "") && m.geometry).map(m => m.geometry));
          }
          if (!rings.length) continue;
          const { h, est: e } = osmHeightFt(tags, defaultHFt);
          for (const ringLL of rings) {
            if (ringLL.length < 4) continue;
            const ring = ringLL.map(p => proj.toXY(p.lat, p.lon));
            let cx = 0, cy = 0;
            for (const [x, y] of ring) { cx += x; cy += y; }
            cx /= ring.length; cy /= ring.length;
            if (nycAllRings.length && coveredByNyc(cx, cy)) continue;
            const c = proj.toLatLon(cx, cy);
            const b = makeBuilding(ring, groundAtLL(c[0], c[1]), h, e);
            if (b) { b.src = "osm"; buildings.push(b); nOsm++; est[e]++; }
          }
        } else if (tags.highway && el.type === "way" && el.geometry) {
          osmStreetsRaw.push(el);
        }
      }
    }
    est.measured += nNyc;
    buildings.forEach((b, i) => { b.id = i; });

    if (!buildings.length) warnings.push("No building footprints found near this location — results assume an open sky.");

    // ---------------- streets
    // street: { name, kind: "road"|"ped", width, pts:[[x,y],...] }
    const nycStreets = [];
    if (nycStreetsGj && nycStreetsGj.features) {
      for (const f of nycStreetsGj.features) {
        const p = f.properties || {}, geom = f.geometry;
        if (!geom) continue;
        const rw = p.rw_type ? String(p.rw_type) : "1";
        if (NYC_EXCLUDE_RW.has(rw)) continue;
        let name = cleanStreetName(p.stname_label || p.full_street_name || "");
        if (/Ramp|Exit|Driveway/i.test(name)) continue;
        const ped = rw === "5" || rw === "6" || rw === "7" || /Pedestrian Path/i.test(name);
        if (ped && /Path/i.test(name)) name = "";
        const width = parseFloat(p.streetwidth) || 34;
        const lines = geom.type === "LineString" ? [geom.coordinates] : geom.type === "MultiLineString" ? geom.coordinates : [];
        for (const line of lines) {
          const pts = line.map(pt => proj.toXY(pt[1], pt[0]));
          if (pts.length >= 2) nycStreets.push({ name, kind: ped ? "ped" : "road", width, pts });
        }
      }
    }
    const osmStreets = [];
    for (const el of osmStreetsRaw) {
      const t = el.tags;
      if (OSM_EXCLUDE.has(t.highway) || t.tunnel === "yes" || t.area === "yes") continue;
      const roadW = OSM_ROAD_WIDTH_FT[t.highway];
      const isRoad = roadW !== undefined && !(t.highway === "service" && !t.name) && !(t.highway === "pedestrian" && !t.name);
      const wTag = parseLenM(t.width);
      const width = wTag ? wTag * FT : (roadW || 8);
      const name = cleanStreetName(t["name:en"] || t.name || "");
      const pts = el.geometry.map(p => proj.toXY(p.lat, p.lon));
      if (pts.length >= 2) osmStreets.push({ name: isRoad ? name : (t.highway === "pedestrian" ? name : ""), kind: isRoad ? "road" : "ped", width, pts });
    }

    let streets, streetSrc;
    const nearOrigin = s => s.pts.some(([x, y]) => x * x + y * y < 600 * 600);
    if (nycStreets.filter(s => s.kind === "road" && nearOrigin(s)).length >= 4) {
      streets = nycStreets; streetSrc = "NYC Street Centerlines";
    } else {
      streets = osmStreets; streetSrc = "OpenStreetMap";
    }

    // ---------------- source summary
    let source;
    if (nNyc && nOsm) source = `NYC Open Data 3D footprints (${nNyc.toLocaleString()}) + OpenStreetMap (${nOsm.toLocaleString()} outside NYC dataset)`;
    else if (nNyc) source = `NYC Open Data 3D Building Footprints (${nNyc.toLocaleString()} buildings, surveyed roof heights)`;
    else source = `OpenStreetMap (${nOsm.toLocaleString()} buildings)`;
    const total = buildings.length || 1;
    const pctEst = Math.round(100 * est.default / total);
    const pctLv = Math.round(100 * est.levels / total);

    const model = {
      proj, place, tz: tzInfo.tz, nycMode: !!nNyc, buildings, streets, streetSrc, warnings, source,
      heightStats: { measured: est.measured, levels: est.levels, default: est.default, pctEst, pctLv },
      fetchRadiusFt: fetchRadiusM * FT, walkMax,
    };
    model.bGrid = buildGrid(buildings, 150);
    model.groundAt = (x, y) => {
      if (nNyc) {
        // Same approach as visibility.py: nearest NYC building's ground elevation
        let best = Infinity, g = null;
        for (const b of buildings) {
          if (b.src !== "nyc") continue;
          const d2 = (b.cx - x) ** 2 + (b.cy - y) ** 2;
          if (d2 < best) { best = d2; g = b.g; }
        }
        if (g !== null && best < 400 * 400) return g;
      }
      const ll = proj.toLatLon(x, y);
      return groundAtLL(ll[0], ll[1]);
    };
    buildCandidates(model);
    buildDrawData(model);
    L.ok("model", `${buildings.length.toLocaleString()} buildings • ${streets.length.toLocaleString()} street segments • ${model.candidates.length.toLocaleString()} candidate spots within ${walkMax.toLocaleString()} ft walk`);
    return model;
  }

  // ------------------------------------------------------------------ candidates
  function isInsideBuilding(model, x, y, pad = 1.0) {
    for (const i of model.bGrid.near(x, y)) {
      const b = model.buildings[i];
      if (x < b.x0 - pad || x > b.x1 + pad || y < b.y0 - pad || y > b.y1 + pad) continue;
      if (pointInRing(x, y, b.pts)) return true;
    }
    return false;
  }

  function projectOnSeg(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay;
    const L2 = dx * dx + dy * dy;
    const t = L2 < 1e-9 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2));
    const qx = ax + t * dx, qy = ay + t * dy;
    return { t, qx, qy, d: Math.hypot(px - qx, py - qy), len: Math.sqrt(L2) };
  }

  function buildCandidates(model) {
    const { streets, walkMax } = model;
    const SNAP = 3;
    const keyOf = (x, y) => Math.round(x / SNAP) + "," + Math.round(y / SNAP);

    // ---- walking graph from all walkable street geometry
    const nodes = new Map(); // key -> {x,y,adj:[[key,len]]}
    const segs = [];
    const segGridCell = 120;
    const segGrid = new Map();
    const addNode = (x, y) => {
      const k = keyOf(x, y);
      if (!nodes.has(k)) nodes.set(k, { x, y, adj: [] });
      return k;
    };
    streets.forEach((s, si) => {
      for (let i = 0; i < s.pts.length - 1; i++) {
        const [ax, ay] = s.pts[i], [bx, by] = s.pts[i + 1];
        const len = Math.hypot(bx - ax, by - ay);
        if (len < 0.01) continue;
        const ka = addNode(ax, ay), kb = addNode(bx, by);
        nodes.get(ka).adj.push([kb, len]);
        nodes.get(kb).adj.push([ka, len]);
        const seg = { ax, ay, bx, by, len, ka, kb, si };
        const idx = segs.push(seg) - 1;
        const gx0 = Math.floor(Math.min(ax, bx) / segGridCell), gx1 = Math.floor(Math.max(ax, bx) / segGridCell);
        const gy0 = Math.floor(Math.min(ay, by) / segGridCell), gy1 = Math.floor(Math.max(ay, by) / segGridCell);
        for (let gx = gx0; gx <= gx1; gx++) for (let gy = gy0; gy <= gy1; gy++) {
          const k = gx + "," + gy;
          let arr = segGrid.get(k);
          if (!arr) segGrid.set(k, arr = []);
          arr.push(idx);
        }
      }
    });
    function nearestSeg(x, y, maxR, filter) {
      let best = null;
      const r = Math.ceil(maxR / segGridCell);
      const cx = Math.floor(x / segGridCell), cy = Math.floor(y / segGridCell);
      const seen = new Set();
      for (let gx = cx - r; gx <= cx + r; gx++) for (let gy = cy - r; gy <= cy + r; gy++) {
        for (const idx of segGrid.get(gx + "," + gy) || []) {
          if (seen.has(idx)) continue;
          seen.add(idx);
          const s = segs[idx];
          if (filter && !filter(s)) continue;
          const p = projectOnSeg(x, y, s.ax, s.ay, s.bx, s.by);
          if (p.d <= maxR && (!best || p.d < best.d)) best = { ...p, seg: s, idx };
        }
      }
      return best;
    }

    const isNamedRoad = s => streets[s.si].kind === "road" && streets[s.si].name;
    const halfW = st => Math.max(10, Math.min(45, st.width / 2)) + 4;

    // ---- dominant street-grid rotation (e.g. Manhattan ≈ 29°), so "NE corner" follows local convention
    let gridDeg = 0;
    {
      let C = 0, S = 0, W = 0;
      for (const s of segs) {
        const st = streets[s.si];
        if (st.kind !== "road") continue;
        if (Math.hypot((s.ax + s.bx) / 2, (s.ay + s.by) / 2) > 1500) continue;
        const a = Math.atan2(s.bx - s.ax, s.by - s.ay) * 4;
        C += s.len * Math.cos(a); S += s.len * Math.sin(a); W += s.len;
      }
      if (W > 0 && Math.hypot(C, S) / W > 0.45) gridDeg = Math.atan2(S, C) * RAD / 4;
      if (Math.abs(gridDeg) < 4) gridDeg = 0;
    }
    model.gridDeg = Math.round(gridDeg);
    const gcompass8 = az => compass8(az - gridDeg);
    const gcompass4 = az => ["N", "E", "S", "W"][Math.floor((((az - gridDeg) % 360 + 360) % 360 + 45) / 90) % 4];
    const gdiag = az => ["NE", "SE", "SW", "NW"][Math.floor((((az - gridDeg) % 360 + 360) % 360) / 90) % 4];

    // ---- location front sidewalk
    let front = { x: 0, y: 0 }, frontStreet = null, across = null;
    const ns = nearestSeg(0, 0, 450, isNamedRoad) || nearestSeg(0, 0, 450, s => streets[s.si].kind === "road");
    if (ns) {
      frontStreet = streets[ns.seg.si];
      const off = halfW(frontStreet);
      let ux = -ns.qx, uy = -ns.qy;
      let ul = Math.hypot(ux, uy);
      if (ul < 1) { // geocoded point sits on the centerline: use segment normal
        const dx = ns.seg.bx - ns.seg.ax, dy = ns.seg.by - ns.seg.ay, l = Math.hypot(dx, dy) || 1;
        ux = -dy / l; uy = dx / l; ul = 1;
      } else { ux /= ul; uy /= ul; }
      front = null;
      for (const o of [off, off * 0.75, Math.min(off, ul), off * 0.5]) {
        const fx = ns.qx + ux * o, fy = ns.qy + uy * o;
        if (!isInsideBuilding(model, fx, fy)) { front = { x: fx, y: fy }; break; }
      }
      if (!front) front = { x: ns.qx, y: ns.qy };
      across = { x: ns.qx - ux * off, y: ns.qy - uy * off };
    } else if (isInsideBuilding(model, 0, 0)) {
      // No street nearby: step outward until outside the building
      outer: for (let r = 10; r <= 200; r += 10) {
        for (let a = 0; a < 360; a += 30) {
          const fx = Math.sin(a * DEG) * r, fy = Math.cos(a * DEG) * r;
          if (!isInsideBuilding(model, fx, fy)) { front = { x: fx, y: fy }; break outer; }
        }
      }
    }

    // ---- Dijkstra from the front sidewalk
    const dist = new Map();
    let startSeg = null;
    {
      const heap = [];
      const push = (d, k) => {
        heap.push([d, k]);
        let i = heap.length - 1;
        while (i > 0) { const p = (i - 1) >> 1; if (heap[p][0] <= heap[i][0]) break; [heap[p], heap[i]] = [heap[i], heap[p]]; i = p; }
      };
      const pop = () => {
        const top = heap[0], last = heap.pop();
        if (heap.length) {
          heap[0] = last;
          let i = 0;
          for (;;) {
            const l = 2 * i + 1, r = l + 1;
            let m = i;
            if (l < heap.length && heap[l][0] < heap[m][0]) m = l;
            if (r < heap.length && heap[r][0] < heap[m][0]) m = r;
            if (m === i) break;
            [heap[m], heap[i]] = [heap[i], heap[m]];
            i = m;
          }
        }
        return top;
      };
      startSeg = nearestSeg(front.x, front.y, 300);
      if (startSeg) {
        const s = startSeg.seg;
        push(startSeg.d + startSeg.t * s.len, s.ka);
        push(startSeg.d + (1 - startSeg.t) * s.len, s.kb);
        const LIMIT = walkMax * 1.6 + 400;
        while (heap.length) {
          const [d, k] = pop();
          if (dist.has(k)) continue;
          dist.set(k, d);
          if (d > LIMIT) continue;
          for (const [k2, len] of nodes.get(k).adj) if (!dist.has(k2)) push(d + len, k2);
        }
      }
    }
    function walkDist(x, y) {
      const euclid = Math.hypot(x - front.x, y - front.y);
      if (!startSeg) return euclid * 1.25;
      const p = nearestSeg(x, y, 160);
      if (!p) return euclid * 1.25 + 40;
      const s = p.seg;
      let best = Infinity;
      const da = dist.get(s.ka), db = dist.get(s.kb);
      if (da !== undefined) best = Math.min(best, da + p.t * s.len);
      if (db !== undefined) best = Math.min(best, db + (1 - p.t) * s.len);
      if (p.idx === startSeg.idx) best = Math.min(best, startSeg.d + Math.abs(p.t - startSeg.t) * s.len);
      if (!Number.isFinite(best)) return euclid * 1.25 + 40;
      return Math.max(euclid, best + p.d);
    }

    // ---- intersections between differently-named roads
    const vtx = new Map(); // cell key -> {names:Set, pts:[]}
    const CELL = 12;
    streets.forEach(s => {
      if (s.kind !== "road" || !s.name) return;
      for (const [x, y] of s.pts) {
        if (Math.hypot(x, y) > walkMax + 200) continue;
        const k = Math.round(x / CELL) + "," + Math.round(y / CELL);
        let v = vtx.get(k);
        if (!v) vtx.set(k, v = { names: new Set(), pts: [], gx: Math.round(x / CELL), gy: Math.round(y / CELL) });
        v.names.add(s.name);
        v.pts.push([x, y]);
      }
    });
    const pairPts = new Map(); // "A|B" -> [[x,y],...]
    for (const v of vtx.values()) {
      const names = new Set(v.names);
      const pts = v.pts.slice();
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        if (!dx && !dy) continue;
        const n = vtx.get((v.gx + dx) + "," + (v.gy + dy));
        if (n) { n.names.forEach(nm => names.add(nm)); }
      }
      if (names.size < 2) continue;
      const arr = [...names].sort();
      const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
      for (let i = 0; i < arr.length; i++) for (let j = i + 1; j < arr.length; j++) {
        if (!v.names.has(arr[i]) && !v.names.has(arr[j])) continue;
        const key = arr[i] + "|" + arr[j];
        let l = pairPts.get(key);
        if (!l) pairPts.set(key, l = []);
        l.push([cx, cy]);
      }
    }
    const widthOf = new Map();
    const linesOf = new Map();
    streets.forEach(s => {
      if (!s.name) return;
      widthOf.set(s.name, Math.max(widthOf.get(s.name) || 0, s.width));
      let l = linesOf.get(s.name);
      if (!l) linesOf.set(s.name, l = []);
      l.push(s.pts);
    });
    const intersections = [];
    for (const [key, pts] of pairPts) {
      const [s1, s2] = key.split("|");
      // cluster points within 130 ft (dual carriageways collapse to one intersection)
      const clusters = [];
      for (const p of pts) {
        const c = clusters.find(c => Math.hypot(c.x - p[0], c.y - p[1]) < 130);
        if (c) { c.list.push(p); c.x = c.list.reduce((a, q) => a + q[0], 0) / c.list.length; c.y = c.list.reduce((a, q) => a + q[1], 0) / c.list.length; }
        else clusters.push({ x: p[0], y: p[1], list: [p] });
      }
      for (const c of clusters) {
        let spread = 0;
        for (const p of c.list) spread = Math.max(spread, Math.hypot(p[0] - c.x, p[1] - c.y));
        const [a, b] = (widthOf.get(s2) || 0) > (widthOf.get(s1) || 0) ? [s2, s1] : [s1, s2];
        intersections.push({ x: c.x, y: c.y, a, b, spread });
      }
    }

    const raw = [];
    const addCand = (name, short, x, y, kind) => {
      if (Math.hypot(x, y) > walkMax + 150) return;
      if (isInsideBuilding(model, x, y, 1.0)) return;
      const w = walkDist(x, y);
      if (w > walkMax) return;
      raw.push({ name, short_name: short, x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, walk_ft: Math.round(w), kind });
    };

    const placeShort = model.place.short || "Location";
    raw.push({ name: `Outside ${placeShort}`, short_name: `Outside ${placeShort}`, x: Math.round(front.x * 10) / 10, y: Math.round(front.y * 10) / 10, walk_ft: 0, kind: "shul" });
    if (across && frontStreet) addCand(`Across ${frontStreet.name || "the street"} from ${placeShort}`, `Across ${shortStreet(frontStreet.name || "street")}`, across.x, across.y, "midblock");

    // ---- corners (and medians) at each intersection
    function outgoingAngles(c, names, R) {
      const angs = [];
      for (const nm of names) for (const pl of linesOf.get(nm) || []) {
        let near = Infinity;
        for (let i = 0; i < pl.length - 1; i++) near = Math.min(near, projectOnSeg(c.x, c.y, pl[i][0], pl[i][1], pl[i + 1][0], pl[i + 1][1]).d);
        if (near > 40 + c.spread) continue;
        let foundAny = false, far = null, farD = 0;
        for (let i = 0; i < pl.length - 1; i++) {
          const d1 = Math.hypot(pl[i][0] - c.x, pl[i][1] - c.y), d2 = Math.hypot(pl[i + 1][0] - c.x, pl[i + 1][1] - c.y);
          if ((d1 - R) * (d2 - R) < 0) {
            const t = (R - d1) / (d2 - d1);
            const px = pl[i][0] + t * (pl[i + 1][0] - pl[i][0]), py = pl[i][1] + t * (pl[i + 1][1] - pl[i][1]);
            angs.push(Math.atan2(px - c.x, py - c.y));
            foundAny = true;
          }
          for (const [q, d] of [[pl[i], d1], [pl[i + 1], d2]]) if (d > farD) { farD = d; far = q; }
        }
        if (!foundAny && far && farD > 10) angs.push(Math.atan2(far[0] - c.x, far[1] - c.y));
      }
      angs.sort((p, q) => p - q);
      const out = [];
      for (const a of angs) {
        if (!out.some(o => { let d = Math.abs(o - a) % (2 * Math.PI); if (d > Math.PI) d = 2 * Math.PI - d; return d < 25 * DEG; })) out.push(a);
      }
      return out.sort((p, q) => p - q);
    }

    for (const it of intersections) {
      const d0 = Math.hypot(it.x, it.y);
      if (d0 > walkMax + 100) continue;
      const full = `${it.a} & ${it.b}`;
      const short = `${shortStreet(it.a)} & ${shortStreet(it.b)}`;
      const wa = widthOf.get(it.a) || 34, wb = widthOf.get(it.b) || 34;
      if (it.spread > 18 || (model.nycMode && Math.max(wa, wb) >= 90)) {
        const wide = wa >= wb ? it.a : it.b, other = wide === it.a ? it.b : it.a;
        addCand(`Median of ${wide} at ${other}`, `${shortStreet(wide)} median/${shortStreet(other)}`, it.x, it.y, "median");
      }
      const off = Math.max(wa, wb) / 2 + 4 + it.spread;
      let angs = outgoingAngles(it, [it.a, it.b], 45 + it.spread);
      if (angs.length < 2) {
        const base = angs.length ? angs[0] : 0;
        angs = [base, base + Math.PI / 2, base + Math.PI, base + 1.5 * Math.PI];
      }
      for (let i = 0; i < angs.length; i++) {
        const a1 = angs[i], a2 = i + 1 < angs.length ? angs[i + 1] : angs[0] + 2 * Math.PI;
        const gap = a2 - a1;
        if (gap < 20 * DEG) continue;
        const bis = a1 + gap / 2;
        const dd = Math.min(off * 2.2, off / Math.max(0.3, Math.sin(gap / 2)));
        const label = angs.length === 4 ? gdiag(bis * RAD) : gcompass8(bis * RAD);
        for (const sc of [1.0, 0.75, 0.5, 1.3]) {
          const tx = it.x + Math.sin(bis) * dd * sc, ty = it.y + Math.cos(bis) * dd * sc;
          if (!isInsideBuilding(model, tx, ty, 1.0)) {
            addCand(`${label} corner of ${full}`, `${short} (${label})`, tx, ty, "corner");
            break;
          }
        }
      }
    }

    // ---- midblock sidewalk points along every named road
    const nearestInterOn = (name, x, y) => {
      let best = null, bd = Infinity;
      for (const it of intersections) {
        if (it.a !== name && it.b !== name) continue;
        const d = Math.hypot(it.x - x, it.y - y);
        if (d < bd) { bd = d; best = it; }
      }
      return best ? { it: best, d: bd } : null;
    };
    const tooCloseToInter = (x, y) => intersections.some(it => Math.hypot(it.x - x, it.y - y) < 60 + it.spread);
    const STEP = 100;
    for (const s of streets) {
      if (s.kind !== "road" || !s.name) continue;
      if (!s.pts.some(([x, y]) => Math.hypot(x, y) < walkMax + 100)) continue;
      const off = halfW(s);
      let carry = STEP / 2;
      for (let i = 0; i < s.pts.length - 1; i++) {
        const [ax, ay] = s.pts[i], [bx, by] = s.pts[i + 1];
        const L = Math.hypot(bx - ax, by - ay);
        if (L < 1e-6) continue;
        const tx = (bx - ax) / L, ty = (by - ay) / L;
        let d = carry;
        while (d < L) {
          const mx = ax + tx * d, my = ay + ty * d;
          d += STEP;
          if (Math.hypot(mx, my) > walkMax + 100 || tooCloseToInter(mx, my)) continue;
          const ni = nearestInterOn(s.name, mx, my);
          for (const sign of [1, -1]) {
            const nx = -ty * sign, ny = tx * sign; // normal
            const side = gcompass4(Math.atan2(nx, ny) * RAD);
            const px = mx + nx * off, py = my + ny * off;
            let name, short;
            if (ni && ni.d < 900) {
              const other = ni.it.a === s.name ? ni.it.b : ni.it.a;
              const dir = gcompass4(Math.atan2(mx - ni.it.x, my - ni.it.y) * RAD);
              name = `${s.name}, ${side} side (${Math.round(ni.d / 10) * 10} ft ${dir} of ${other})`;
              short = `${shortStreet(s.name)}, ${side} side (${dir} of ${shortStreet(other)})`;
            } else {
              name = `${s.name}, ${side} side`;
              short = name;
            }
            addCand(name, short, px, py, "midblock");
          }
        }
        carry = d - L;
      }
    }

    // ---- open-area probes (rural / sparse street data)
    if (raw.length < 12) {
      for (const r of [40, 100, 180, 300, 500, 800, 1200]) {
        if (r > walkMax) break;
        for (let a = 0; a < 360; a += 45) {
          const x = front.x + Math.sin(a * DEG) * r, y = front.y + Math.cos(a * DEG) * r;
          addCand(`${r} ft ${gcompass8(a)} of ${placeShort}`, `${r} ft ${gcompass8(a)}`, x, y, "probe");
        }
      }
    }

    // ---- sort, de-dup, assign ground
    raw.sort((p, q) => p.walk_ft - q.walk_ft);
    const out = [];
    for (const c of raw) {
      if (out.some(o => Math.hypot(o.x - c.x, o.y - c.y) < 10)) continue;
      out.push(c);
    }
    for (const c of out) c.g = Math.round(model.groundAt(c.x, c.y) * 10) / 10;
    model.candidates = out;
    model.shul = out[0];
    model.intersections = intersections;
    model.frontStreet = frontStreet ? frontStreet.name : null;
  }

  // ------------------------------------------------------------------ drawing data
  function buildDrawData(model) {
    const R = Math.min(model.fetchRadiusFt, 2600);
    model.streetsDraw = model.streets
      .filter(s => s.kind === "road" || s.name)
      .filter(s => s.pts.some(([x, y]) => Math.hypot(x, y) < R))
      .map(s => s.pts);
    const buckets = new Map();
    for (const s of model.streets) {
      if (!s.name || s.kind !== "road") continue;
      const n = s.pts.length;
      const mx = (s.pts[0][0] + s.pts[n - 1][0]) / 2, my = (s.pts[0][1] + s.pts[n - 1][1]) / 2;
      if (Math.hypot(mx, my) > 1900) continue;
      const key = s.name + "|" + Math.round(mx / 420) + "|" + Math.round(my / 420);
      let b = buckets.get(key);
      if (!b) buckets.set(key, b = { name: shortStreet(s.name), list: [] });
      b.list.push([mx, my]);
    }
    model.streetLabels = [...buckets.values()].map(b => [
      b.name,
      b.list.reduce((a, p) => a + p[0], 0) / b.list.length,
      b.list.reduce((a, p) => a + p[1], 0) / b.list.length,
    ]);
  }

  // ------------------------------------------------------------------ visibility (port of check_visibility)
  function raySegT(ox, oy, dx, dy, x1, y1, x2, y2) {
    const sx = x2 - x1, sy = y2 - y1;
    const denom = dx * sy - dy * sx;
    if (Math.abs(denom) < 1e-9) return null;
    const qpx = x1 - ox, qpy = y1 - oy;
    const t = (qpx * sy - qpy * sx) / denom;
    if (t <= 0.5) return null;
    const u = (qpx * dy - qpy * dx) / denom;
    return (u >= -1e-9 && u <= 1 + 1e-9) ? t : null;
  }

  // Returns clearance in degrees (altitude minus highest obstruction angle)
  function clearance(model, ox, oy, groundFt, azDeg, altDeg, maxDist = RAY_MAX_FT) {
    if (altDeg <= 0.5) return altDeg - 90;
    const dx = Math.sin(azDeg * DEG), dy = Math.cos(azDeg * DEG);
    const oz = groundFt + EYE_FT;
    const rx1 = ox + dx * maxDist, ry1 = oy + dy * maxDist;
    const rMinX = Math.min(ox, rx1), rMaxX = Math.max(ox, rx1), rMinY = Math.min(oy, ry1), rMaxY = Math.max(oy, ry1);
    let maxObs = 0;
    const B = model.buildings;
    for (let k = 0; k < B.length; k++) {
      const b = B[k];
      if (b.x1 < rMinX || b.x0 > rMaxX || b.y1 < rMinY || b.y0 > rMaxY) continue;
      const dh = b.top - oz;
      if (dh <= 0) continue;
      const cx = Math.max(b.x0, Math.min(ox, b.x1)), cy = Math.max(b.y0, Math.min(oy, b.y1));
      const minD = Math.hypot(cx - ox, cy - oy);
      if (minD > maxDist) continue;
      if (minD > 0.5 && Math.atan2(dh, minD) * RAD <= maxObs) continue;
      let bestT = Infinity;
      const pts = b.pts;
      for (let i = 0; i < pts.length - 1; i++) {
        const t = raySegT(ox, oy, dx, dy, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]);
        if (t !== null && t <= maxDist && t < bestT) bestT = t;
      }
      if (bestT < Infinity) {
        const a = Math.atan2(dh, bestT) * RAD;
        if (a > maxObs) maxObs = a;
      }
    }
    return Math.round((altDeg - maxObs) * 10) / 10;
  }

  // Closest candidate clear (>= 1.5°) for every (az, alt) sample (port of find_nearest_spot_window)
  function findSpotWindow(model, samples) {
    if (!samples.length || samples.some(s => s[1] <= 0.5)) return null;
    const n = samples.length;
    const fast = [...new Set([0, n >> 1, n - 1])].sort((a, b) => a - b);
    for (const c of model.candidates) {
      let ok = true;
      for (const i of fast) {
        if (clearance(model, c.x, c.y, c.g, samples[i][0], samples[i][1]) < MIN_CLEARANCE) { ok = false; break; }
      }
      if (!ok) continue;
      let minClr = 999, t0 = 0;
      for (let i = 0; i < n; i++) {
        const clr = clearance(model, c.x, c.y, c.g, samples[i][0], samples[i][1]);
        if (i === 0) t0 = clr;
        if (clr < minClr) minClr = clr;
        if (clr < MIN_CLEARANCE) { ok = false; break; }
      }
      if (ok) return { ...c, clearance_deg: t0, min_clearance_deg: minClr };
    }
    return null;
  }

  return {
    FT, EYE_FT, PARAPET_FT, MIN_CLEARANCE, RAY_MAX_FT,
    inNycBox, geocode, reverseGeocode, loadLocation, clearance, findSpotWindow, compass8,
  };
})();

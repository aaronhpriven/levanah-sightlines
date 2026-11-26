# Kiddush Levanah 3D Sightlines

Live site: https://aaronhpriven.github.io/levanah-sightlines/

## Any location (`docs/index.html`)

A static, client-side page that works for **any address or shul worldwide**:

1. **Search** an address / shul name (Photon + NYC GeoSearch, Nominatim fallback), enter `lat, lon`, or use browser geolocation.
2. **Fetch 3D data** (hybrid):
   - **Inside NYC:** NYC Open Data 3D Building Footprints (`5zhs-2jue`, surveyed roof heights) + Street Centerlines (`inkn-q76z`). OpenStreetMap buildings are merged in only where the NYC dataset has none (e.g. just across the city line).
   - **Elsewhere:** OpenStreetMap via Overpass (`height` → `building:levels` → configurable default), with terrain from Open-Meteo. The page shows what share of heights are estimated.
   - Timezone from Open-Meteo, so tzeis and molad times are shown in local time.
3. **Calendar:** Hebrew calendar, molad, Kiddush Levanah window (3 or 7 to 15 days; after Yom Kippur / Tisha B'Av), shkiah + N min tzeis, and Meeus topocentric moon position (`docs/astronomy.js`, port of `src/calendar_moon.py`). Israel uses 1-day Yom Tov, detected automatically.
4. **Candidate spots** come from the real street network (`docs/geodata.js`): outside the building, across the street, every intersection corner (labels follow the local street grid, e.g. Manhattan's 29°), medians of divided avenues, and midblock sidewalk points. Each is ranked by walking distance along the street graph.
5. **Line of sight:** for every night, the closest spot that stays ≥ 1.5° clear (+4 ft parapet, 5.5 ft eye level) for 20 min after tzeis. If none, it tries +30/60/90 min.
6. **3D viewer** (`docs/viewer.js`, generated from the YIWS viewer): 3D model, first-person view, elevation cross-section, 30-minute slider, and a "Closest Now" mode.

Shareable links: `?lat=…&lon=…&name=…&short=Shul` plus optional `year`, `tzeis`, `min`, `yt=israel|diaspora`, `walk`, `defh`. Add `#YYYY-MM-DD` to open one night's viewer directly.

## Young Israel of the West Side (`docs/yiws/`)

Pre-built guide for **210 West 91st Street, New York, NY**, with a printable PDF.

- **Kiddush Levanah window:** 3 to 15 full days after the molad (adjusted after Yom Kippur in Tishrei and Tisha B'Av in Av)
- **Tzeis:** Shkiah + 50 minutes
- **3D Line-of-Sight Model:** Official NYC Open Data 3D Building Footprints (`5zhs-2jue`) with `+4 ft` parapet allowance and `≥ 1.5°` clearance, verified clear across the full **20 minutes post-tzeis**.

Files:
- `docs/yiws/index.html` — Self-contained interactive calendar + 3D viewer
- `docs/yiws/YIWS_Kiddush_Levanah_5787.pdf` — 2-page printable PDF (1 double-sided US Letter sheet)

## Development

`docs/viewer.js` and the shared CSS in `docs/index.html` were generated from the template in `src/build_interactive_calendar.py`. To preview locally:

```sh
python3 -m http.server 8765 --directory docs
```

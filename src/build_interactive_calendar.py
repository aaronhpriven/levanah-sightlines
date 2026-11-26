#!/usr/bin/env python3
"""
Build a single-file, self-contained interactive HTML calendar + 3D Moon Sightline Viewer
for Young Israel of the West Side (210 West 91st St) for all 23 qualifying nights of 5787.

Clicking any night in the calendar opens the interactive 3D NYC building model,
First-Person eye-level view (with 30-min Moon trajectory), 2D elevation cross-section,
and 0–30 min post-tzeis time slider. Ray-casting runs live in JavaScript (<1 ms)
so the entire self-contained HTML file stays compact (~500 KB) and works offline.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calendar_moon import UTC, compass_direction, moon_alt_az
from render_option_d import filter_motzaei_nights, fmt_dt_compact
from visibility import FT_PER_METER, SHUL_LAT, SHUL_LON, VisibilityModel

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUT_DIR, exist_ok=True)


def simplify_ring(ring: list[tuple[float, float]]) -> list[list[int]]:
    """Round building polygon vertices to nearest integer foot and drop consecutive duplicates."""
    out = []
    for x, y in ring:
        ix, iy = int(round(x)), int(round(y))
        if not out or out[-1][0] != ix or out[-1][1] != iy:
            out.append([ix, iy])
    if len(out) >= 3 and out[0] != out[-1]:
        out.append(out[0])
    return out


def build_interactive_html():
    with open(os.path.join(DATA_DIR, "levanah_5787.json")) as f:
        data = json.load(f)

    vm = VisibilityModel()
    shul = vm.candidates[0]
    shul_elev_m = shul["ground_ft"] / FT_PER_METER

    # Collect all 120 valid nights (non-Shabbos/Yom Tov), flagging the 23 Motzaei Shabbos / YK / 9 Av nights
    nights_payload = []
    motzaei_count = 0
    for m in data["months"]:
        win_earliest = fmt_dt_compact(m["earliest_ny"])
        win_latest = fmt_dt_compact(m["latest_ny"])

        for n in m["nights"]:
            if n.get("yom_tov_or_shabbos"):
                continue  # skip Friday nights & Yom Tov nights
            is_yk = (m["month_num"] == 7 and n["heb_day"] == 11)
            is_tb = (m["month_num"] == 5 and n["heb_day"] == 10)
            is_motzaei = bool(n["is_motzaei_shabbos"] or is_yk or is_tb)
            if is_yk:
                special_tag = "Motzaei YK"
            elif is_tb:
                special_tag = "Motzaei 9 Av"
            elif n["is_motzaei_shabbos"]:
                special_tag = "Motzaei Shabbos"
            else:
                special_tag = None
            if is_motzaei:
                motzaei_count += 1

            sp = n["nearest_spot"]
            eval_dt = datetime.datetime.fromisoformat(n["eval_time"])
            tzeis_str = eval_dt.strftime("%-I:%M %p")
            wait_min = sp.get("wait_minutes", 0) if sp else 0
            start_dt = eval_dt + datetime.timedelta(minutes=wait_min)

            # 31 frames (0..30 min from start_dt)
            frames = []
            for off in range(0, 31):
                dt = start_dt + datetime.timedelta(minutes=off)
                alt, az, _ = moon_alt_az(dt.astimezone(UTC), SHUL_LAT, SHUL_LON, shul_elev_m)
                frames.append([
                    round(az, 1),
                    round(alt, 1),
                    dt.strftime("%-I:%M %p"),
                    compass_direction(az),
                ])

            dt_civil = datetime.date.fromisoformat(n["civil_date"])
            date_disp = dt_civil.strftime("%a, %b %-d, %Y")
            date_short = dt_civil.strftime("%b %-d")

            nights_payload.append({
                "id": len(nights_payload),
                "is_motzaei": is_motzaei,
                "month_name": m["month_name"],
                "win_earliest": win_earliest,
                "win_latest": win_latest,
                "civil_date": n["civil_date"],
                "date_disp": date_disp,
                "date_short": date_short,
                "heb_date": n["heb_date_str"],
                "special_tag": special_tag,
                "tzeis_str": tzeis_str,
                "wait_min": wait_min,
                "wait_time_str": sp.get("wait_time_str") if sp else None,
                "illum_pct": round(n["moon_illum_pct"]),
                "moon_note": n.get("moon_note"),
                "spot": {
                    "name": sp["name"],
                    "short_name": sp["short_name"],
                    "x": round(sp["x"], 1),
                    "y": round(sp["y"], 1),
                    "g": round(sp["ground_ft"], 1),
                    "walk_ft": sp["walk_ft"],
                    "min_clr": sp.get("min_clearance_deg", sp.get("clearance_deg")),
                } if sp else None,
                "frames": frames,
            })

    # Include all buildings within 2,150 ft of shul (covers Riverside Dr, Columbus & 93rd, Bway & 88th)
    buildings_payload = []
    for b in vm.buildings:
        cx = 0.5 * (b.bbox[0] + b.bbox[2])
        cy = 0.5 * (b.bbox[1] + b.bbox[3])
        if math.hypot(cx, cy) > 2150:
            continue
        pts = simplify_ring(b.rings[0])
        if len(pts) < 4:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        buildings_payload.append([
            pts,                     # 0: ring [[x,y],...]
            int(round(b.ground_ft)), # 1: ground_ft
            int(round(b.height_ft)), # 2: height_ft
            int(round(b.top_ft)),    # 3: top_ft (includes +4ft parapet)
            int(round(cx)),          # 4: cx
            int(round(cy)),          # 5: cy
            min(xs), min(ys), max(xs), max(ys),  # 6..9: bbox
        ])

    # Include street centerlines within 2,000 ft for orientation + clean street label anchors
    streets_payload = []
    label_buckets: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    major_names = {
        "Broadway", "Amsterdam Ave", "West End Ave", "Columbus Ave", "Riverside Dr",
        "W 87th St", "W 88th St", "W 89th St", "W 90th St", "W 91st St",
        "W 92nd St", "W 93rd St", "W 94th St", "W 95th St",
    }
    for st in vm.streets:
        pts = st["points"]
        if any(math.hypot(p[0], p[1]) < 2000 for p in pts):
            streets_payload.append([[int(round(p[0])), int(round(p[1]))] for p in pts])
            name = st["name"]
            if name in major_names and len(pts) >= 2:
                mx = 0.5 * (pts[0][0] + pts[-1][0])
                my = 0.5 * (pts[0][1] + pts[-1][1])
                if math.hypot(mx, my) < 1800:
                    # Group into ~420 ft spatial cells per street name so labels are nicely spaced
                    cell = (name, int(round(mx / 420.0)), int(round(my / 420.0)))
                    label_buckets.setdefault(cell, []).append((mx, my))

    street_labels_payload = []
    for (name, _, _), coords in label_buckets.items():
        ax = sum(p[0] for p in coords) / len(coords)
        ay = sum(p[1] for p in coords) / len(coords)
        short = name.replace(" Ave", "").replace(" St", "").replace("Riverside Dr", "Riverside")
        street_labels_payload.append([short, int(round(ax)), int(round(ay))])

    # Compact candidate list sorted by walking distance (for live "Closest Right Now" mode)
    candidates_payload = [
        [c["short_name"], round(c["x"], 1), round(c["y"], 1), round(c["ground_ft"], 1), c["walk_ft"]]
        for c in vm.candidates
    ]

    payload = {
        "shul": {
            "name": shul["name"],
            "x": round(shul["x"], 1),
            "y": round(shul["y"], 1),
            "g": round(shul["ground_ft"], 1),
        },
        "candidates": candidates_payload,
        "nights": nights_payload,
        "buildings": buildings_payload,
        "streets": streets_payload,
        "street_labels": street_labels_payload,
    }

    data_json = json.dumps(payload, separators=(",", ":"))
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Young Israel of the West Side — Kiddush Levanah 5787 Interactive 3D Guide</title>
<style>
  :root {{
    --bg: #0b1120;
    --panel: #111827;
    --panel2: #0f172a;
    --border: #1e293b;
    --border2: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --green: #22c55e;
    --red: #ef4444;
    --amber: #f59e0b;
    --blue: #38bdf8;
    --indigo: #6366f1;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }}
  /* -------- CALENDAR VIEW -------- */
  #calView {{
    max-width: 1120px;
    margin: 0 auto;
    padding: 24px 18px 48px;
  }}
  .cal-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 16px;
    flex-wrap: wrap;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border2);
    margin-bottom: 18px;
  }}
  .cal-header h1 {{
    margin: 0;
    font-size: 24px;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: #f8fafc;
  }}
  .cal-header .sub {{
    margin-top: 4px;
    font-size: 13px;
    color: var(--muted);
  }}
  .badge-shul {{
    background: rgba(56, 189, 248, 0.12);
    border: 1px solid rgba(56, 189, 248, 0.35);
    color: #bae6fd;
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 12.5px;
    text-align: right;
  }}
  .badge-shul strong {{ color: #fff; font-size: 13.5px; }}
  .header-right {{
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .pdf-btn {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: #16a34a;
    color: #fff;
    text-decoration: none;
    font-size: 13px;
    font-weight: 700;
    padding: 10px 15px;
    border-radius: 10px;
    border: 1px solid #22c55e;
    transition: background 0.12s, transform 0.1s;
    white-space: nowrap;
  }}
  .pdf-btn:hover {{ background: #15803d; }}
  .toolbar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 14px;
  }}
  .tabs {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .tab-btn {{
    background: var(--panel);
    color: var(--muted);
    border: 1px solid var(--border2);
    border-radius: 8px;
    padding: 7px 13px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.12s;
  }}
  .tab-btn:hover {{ color: #fff; background: #1e293b; }}
  .tab-btn.active {{ background: #2563eb; border-color: #3b82f6; color: #fff; }}
  .tip-pill {{
    font-size: 12px;
    color: #cbd5e1;
    background: rgba(99, 102, 241, 0.12);
    border: 1px solid rgba(99, 102, 241, 0.35);
    padding: 6px 12px;
    border-radius: 8px;
  }}
  .table-wrap {{
    background: var(--panel);
    border: 1px solid var(--border2);
    border-radius: 12px;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  thead th {{
    text-align: left;
    padding: 11px 12px;
    background: var(--panel2);
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border2);
  }}
  tbody tr {{
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.12s;
  }}
  tbody tr:last-child {{ border-bottom: none; }}
  tbody tr:hover {{ background: rgba(56, 189, 248, 0.08); }}
  td {{ padding: 10px 12px; vertical-align: middle; }}
  .m-name {{ font-weight: 700; color: #f8fafc; font-size: 13.5px; }}
  .m-win {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .tag {{
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 5px;
    margin-left: 5px;
    vertical-align: middle;
  }}
  .tag-ms {{ background: rgba(56,189,248,0.16); color: #7dd3fc; }}
  .tag-yk {{ background: rgba(245,158,11,0.18); color: #fcd34d; }}
  .tag-9a {{ background: rgba(244,63,94,0.18); color: #fda4af; }}
  .spot-name {{ font-weight: 700; color: #86efac; }}
  .spot-meta {{ font-size: 11.5px; color: var(--muted); margin-top: 2px; }}
  .spot-none {{ font-weight: 600; color: #fca5a5; }}
  .view-btn {{
    background: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 11.5px;
    font-weight: 700;
    white-space: nowrap;
    cursor: pointer;
  }}
  tr:hover .view-btn {{ background: #2563eb; border-color: #3b82f6; color: #fff; }}
  .cal-footer {{
    margin-top: 16px;
    font-size: 12px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
  }}

  /* -------- 3D VIEWER OVERLAY -------- */
  #viewerOverlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: var(--bg);
    z-index: 100;
    flex-direction: column;
    overflow: hidden;
  }}
  #viewerOverlay.open {{ display: flex; }}
  .v-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 9px 16px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    gap: 12px;
    flex-wrap: wrap;
  }}
  .v-left {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .v-title h2 {{ margin: 0; font-size: 15px; font-weight: 700; }}
  .v-title .sub {{ font-size: 11.5px; color: var(--muted); margin-top: 1px; }}
  .stats {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .pill {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 5px;
  }}
  .pill.clear {{ border-color: rgba(34,197,94,0.45); background: rgba(34,197,94,0.12); color: #86efac; }}
  .pill.blocked {{ border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.12); color: #fca5a5; }}
  .timebar {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 7px 16px;
    background: var(--panel2);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .timebar-label {{ font-size: 12px; font-weight: 700; min-width: 155px; }}
  .timebar-label span {{ color: var(--blue); font-variant-numeric: tabular-nums; }}
  .slider-wrap {{ flex: 1; min-width: 180px; display: flex; flex-direction: column; gap: 2px; }}
  input[type="range"] {{ width: 100%; accent-color: #38bdf8; cursor: pointer; margin: 0; }}
  .slider-ticks {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); }}
  .moon-readout {{ font-size: 12px; color: #cbd5e1; font-variant-numeric: tabular-nums; min-width: 205px; text-align: right; }}
  .v-main {{
    flex: 1;
    display: grid;
    grid-template-columns: 1.35fr 1fr;
    grid-template-rows: 1fr 225px;
    gap: 10px;
    padding: 10px;
    min-height: 0;
  }}
  @media (max-width: 860px) {{
    .v-main {{
      grid-template-columns: 1fr;
      grid-template-rows: 1fr 1fr 190px;
    }}
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
    min-height: 0;
  }}
  .card-hdr {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 11px;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    font-weight: 600;
    background: rgba(15, 23, 42, 0.7);
    gap: 8px;
  }}
  .card-hdr .hint {{ font-weight: 400; color: var(--muted); font-size: 11px; }}
  .btn-group {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  button.ctrl {{
    background: #1e293b;
    color: var(--text);
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 11.5px;
    font-weight: 600;
    cursor: pointer;
  }}
  button.ctrl:hover {{ background: #334155; }}
  button.ctrl.active {{ background: #2563eb; border-color: #3b82f6; color: #fff; }}
  button.ctrl.active-green {{ background: #15803d; border-color: #22c55e; color: #fff; }}
  button.ctrl.active-red {{ background: #b91c1c; border-color: #ef4444; color: #fff; }}
  .canvas-wrap {{ flex: 1; position: relative; min-height: 0; }}
  canvas {{ width: 100%; height: 100%; display: block; }}
  .legend {{
    position: absolute;
    bottom: 10px;
    left: 10px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 6px 9px;
    font-size: 11px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    pointer-events: none;
  }}
  .leg-row {{ display: flex; align-items: center; gap: 7px; }}
  .swatch {{ width: 12px; height: 10px; border-radius: 2px; display: inline-block; }}
  .profile-card {{ grid-column: 1 / -1; }}
</style>
</head>
<body>

<!-- ==================== CALENDAR VIEW ==================== -->
<div id="calView">
  <div class="cal-header">
    <div>
      <h1>Kiddush Levanah 5787 &mdash; Interactive 3D Sightline Guide</h1>
      <div class="sub">Motzaei Shabbos, Motzaei Yom Kippur &amp; Motzaei Tisha B'Av &bull; Verified Clear for 20 Min Post-Tzeis</div>
    </div>
    <div class="header-right">
      <a class="pdf-btn" href="YIWS_Kiddush_Levanah_5787.pdf" download="YIWS_Kiddush_Levanah_5787.pdf">&#128424; Download Printable PDF</a>
      <div class="badge-shul">
        <strong>Young Israel of the West Side</strong><br/>
        210 West 91st Street &bull; NYC 3D Building Model
      </div>
    </div>
  </div>

  <div class="toolbar">
    <div class="tabs">
      <button class="tab-btn active" data-filter="motzaei">Motzaei Shabbos / YK / 9 Av ({motzaei_count})</button>
      <button class="tab-btn" data-filter="all">All Valid Nights ({len(nights_payload)})</button>
    </div>
    <div class="tip-pill">&#128070; Click any night below to inspect its 3D building sightline &amp; 30-min time slider</div>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Month &amp; Window</th>
          <th>Night</th>
          <th>Tzeis</th>
          <th>Moon at Tzeis</th>
          <th>Nearest 20-Min Clear Spot</th>
          <th style="text-align:right;">3D Check</th>
        </tr>
      </thead>
      <tbody id="calBody"></tbody>
    </table>
  </div>

  <div class="cal-footer">
    <span>Window: 3 to 15 full days after molad (after Yom Kippur in Tishrei, after Tisha B'Av in Av) &bull; Tzeis = Shkiah + 50 min</span>
    <span>NYC Open Data 3D Building Footprints (+4 ft parapet buffer, &ge;1.5&deg; clearance)</span>
  </div>
</div>

<!-- ==================== 3D VIEWER OVERLAY ==================== -->
<div id="viewerOverlay">
  <div class="v-header">
    <div class="v-left">
      <button id="btnBack" class="ctrl">&larr; Calendar</button>
      <div class="btn-group">
        <button id="btnPrev" class="ctrl">&lsaquo; Prev</button>
        <button id="btnNext" class="ctrl">Next &rsaquo;</button>
      </div>
      <div class="v-title">
        <h2 id="vTitle"></h2>
        <div id="vSub" class="sub"></div>
      </div>
    </div>
    <div class="stats">
      <div id="pillSpot" class="pill clear"></div>
      <div id="pillShul" class="pill blocked"></div>
    </div>
  </div>

  <div class="timebar">
    <button id="btnPlay" class="ctrl">&#9654; Play</button>
    <div class="btn-group" title="Switch between the fixed spot clear for 20 min post-tzeis vs. the closest spot clear at this exact minute">
      <button id="btnModeStable" class="ctrl active">20-Min Spot</button>
      <button id="btnModeLive" class="ctrl">Closest Now</button>
    </div>
    <div class="timebar-label">Time: <span id="lblTime"></span></div>
    <div class="slider-wrap">
      <input id="timeSlider" type="range" min="0" max="30" step="1" value="0" />
      <div class="slider-ticks">
        <span id="tickStart"></span>
        <span>+10m</span>
        <span>+20m</span>
        <span id="tickEnd"></span>
      </div>
    </div>
    <div id="lblMoon" class="moon-readout"></div>
  </div>

  <div class="v-main">
    <div class="card">
      <div class="card-hdr">
        <div>3D NYC Building Model <span class="hint">&bull; Drag to orbit, scroll to zoom</span></div>
        <div class="btn-group">
          <button id="btnCamIso" class="ctrl active">3D Overview</button>
          <button id="btnCamTop" class="ctrl">Top-Down</button>
        </div>
      </div>
      <div class="canvas-wrap">
        <canvas id="c3d"></canvas>
        <div class="legend">
          <div class="leg-row"><span class="swatch" style="background:#22c55e"></span> <span id="legSpot">Recommended Spot</span></div>
          <div class="leg-row"><span class="swatch" style="background:#ef4444"></span> <span id="legShul">Outside Shul</span></div>
          <div class="leg-row"><span class="swatch" style="background:#dc2626"></span> Building Blocking Ray</div>
          <div class="leg-row"><span class="swatch" style="background:#f59e0b"></span> Closest-Clearance Building</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-hdr">
        <div>First-Person Eye-Level (5.5 ft) <span class="hint">&bull; Dotted = 30m path</span></div>
        <div class="btn-group">
          <button id="btnFpSpot" class="ctrl active-green">Recommended Spot</button>
          <button id="btnFpShul" class="ctrl">Outside Shul</button>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="cFp"></canvas></div>
    </div>

    <div class="card profile-card">
      <div class="card-hdr">
        <div id="profTitle">2D Elevation Cross-Section</div>
        <div class="btn-group">
          <button id="btnProfSpot" class="ctrl active-green">Recommended Spot</button>
          <button id="btnProfShul" class="ctrl">Outside Shul</button>
        </div>
      </div>
      <div class="canvas-wrap"><canvas id="cProf"></canvas></div>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};
const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;
const SHUL = DATA.shul;

// Decode compact building array: [pts, g, h, top, cx, cy, minX, minY, maxX, maxY]
const BUILDINGS = DATA.buildings.map((b, i) => ({{
  id: i, pts: b[0], g: b[1], h: b[2], top: b[3], cx: b[4], cy: b[5],
  x0: b[6], y0: b[7], x1: b[8], y1: b[9],
}}));

// Decode candidate spots sorted by walking distance: [short_name, x, y, g, walk_ft]
const CANDIDATES = DATA.candidates.map(c => ({{
  short_name: c[0], x: c[1], y: c[2], g: c[3], walk_ft: c[4],
}}));

function findClosestSpotAt(azDeg, altDeg) {{
  if (altDeg <= 0.5) return null;
  for (const c of CANDIDATES) {{
    const tr = traceRay(c.x, c.y, c.g, azDeg, altDeg);
    if (tr.isClear) return {{ spot: c, trace: tr }};
  }}
  return null;
}}

// ---------------- CLIENT-SIDE 3D RAY-CASTER (exact match to visibility.py) ----------------
function raySegIntersect(ox, oy, dx, dy, x1, y1, x2, y2) {{
  const sx = x2 - x1, sy = y2 - y1;
  const denom = dx * sy - dy * sx;
  if (Math.abs(denom) < 1e-9) return null;
  const qpx = x1 - ox, qpy = y1 - oy;
  const t = (qpx * sy - qpy * sx) / denom;
  if (t <= 0.5) return null;
  const u = (qpx * dy - qpy * dx) / denom;
  if (u >= -1e-9 && u <= 1.0 + 1e-9) return t;
  return null;
}}

function traceRay(ox, oy, groundFt, azDeg, altDeg, maxDist=1800) {{
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

  for (const b of BUILDINGS) {{
    if (b.x1 < rMinX || b.x0 > rMaxX || b.y1 < rMinY || b.y0 > rMaxY) continue;
    let tMin = Infinity, tMax = -Infinity;
    const pts = b.pts;
    for (let i = 0; i < pts.length - 1; i++) {{
      const t = raySegIntersect(ox, oy, dx, dy, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]);
      if (t !== null && t <= maxDist) {{
        if (t < tMin) tMin = t;
        if (t > tMax) tMax = t;
      }}
    }}
    if (tMin === Infinity) continue;
    if (tMax <= tMin + 1) tMax = Math.min(maxDist, tMin + 40);
    const dh = b.top - oz;
    const obsAngle = dh > 0 ? Math.atan2(dh, tMin) * RAD : 0;
    const rayZ = oz + tMin * tanAlt;
    const blocks = b.top > rayZ - 1e-6;
    if (obsAngle > maxObs) {{ maxObs = obsAngle; limitingId = b.id; }}
    slices.push({{
      id: b.id, tEnter: tMin, tExit: tMax, g: b.g, h: b.h,
      roof: b.g + b.h, top: b.top, rayZ, obsAngle, blocks,
    }});
  }}
  slices.sort((a, b) => a.tEnter - b.tEnter);
  const firstBlock = slices.find(s => s.blocks) || null;
  const clearance = Math.round((altDeg - maxObs) * 10) / 10;
  return {{
    ox, oy, g: groundFt, oz, azDeg, altDeg,
    maxObs: Math.round(maxObs * 10) / 10,
    clearance,
    isClear: altDeg > 0.5 && clearance >= 1.5,
    blockingId: firstBlock ? firstBlock.id : null,
    limitingId,
    firstBlock,
    slices,
  }};
}}

// ---------------- CALENDAR TABLE ----------------
let currentFilter = "motzaei";
const calBody = document.getElementById("calBody");

function getFilteredNights() {{
  return DATA.nights.filter(n => currentFilter === "all" || n.is_motzaei);
}}

function walkStr(ft) {{
  if (ft <= 20) return "0 min";
  const mins = Math.max(1, Math.round(ft / 260));
  return `${{ft.toLocaleString()}} ft (~${{mins}} min)`;
}}

function renderCalendar() {{
  calBody.innerHTML = "";
  const list = getFilteredNights();
  for (const n of list) {{
    const f0 = n.frames[0];
    let tagHtml = "";
    if (n.special_tag) {{
      const tagCls = n.special_tag === "Motzaei YK" ? "tag-yk" : (n.special_tag === "Motzaei 9 Av" ? "tag-9a" : "tag-ms");
      tagHtml = `<span class="tag ${{tagCls}}">${{n.special_tag}}</span>`;
    }}
    const tr = document.createElement("tr");
    tr.onclick = () => openViewer(n.id);

    let spotHtml;
    if (n.spot) {{
      const waitNote = n.wait_min ? ` <span style="color:#fcd34d">(at ${{n.wait_time_str}})</span>` : "";
      spotHtml = `<div class="spot-name">${{n.spot.short_name}}${{waitNote}}</div>
        <div class="spot-meta">${{walkStr(n.spot.walk_ft)}} &bull; min +${{n.spot.min_clr.toFixed(1)}}&deg; clear (0&ndash;20m)</div>`;
    }} else {{
      spotHtml = `<div class="spot-none">Blocked within 6 blocks</div>
        <div class="spot-meta">Moon too low (${{f0[1].toFixed(1)}}&deg;) &mdash; use earlier night</div>`;
    }}

    tr.innerHTML = `
      <td><div class="m-name">${{n.month_name}}</div><div class="m-win">${{n.win_earliest}} &ndash; ${{n.win_latest}}</div></td>
      <td><strong>${{n.date_disp}}</strong>${{tagHtml}}<div class="m-win">${{n.heb_date}}</div></td>
      <td><strong>${{n.tzeis_str}}</strong></td>
      <td><strong>${{f0[3]}} (${{f0[0].toFixed(1)}}&deg;)</strong><div class="m-win">Alt ${{f0[1].toFixed(1)}}&deg; &bull; ${{n.illum_pct}}% lit</div></td>
      <td>${{spotHtml}}</td>
      <td style="text-align:right;"><button class="view-btn">View 3D &rarr;</button></td>
    `;
    calBody.appendChild(tr);
  }}
}}

document.querySelectorAll(".tab-btn").forEach(btn => {{
  btn.onclick = () => {{
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    renderCalendar();
  }};
}});

// ---------------- 3D VIEWER STATE ----------------
let nightIdx = 0;
let frameIdx = 0;
let activeView = "spot";
let spotMode = "stable"; // "stable" (30-min spot) or "live" (closest right now)
let playTimer = null;
let curNight = null;
let curActiveSpot = null;
let curShulTrace = null;
let curSpotTrace = null;
let localBuildings = [];
let fpCenterAz = 100;

const overlay = document.getElementById("viewerOverlay");
const c3d = document.getElementById("c3d");
const cFp = document.getElementById("cFp");
const cProf = document.getElementById("cProf");
const slider = document.getElementById("timeSlider");
const btnPlay = document.getElementById("btnPlay");

let cam = {{ targetX: 0, targetY: 0, targetZ: 120, yaw: -145 * DEG, pitch: 34 * DEG, dist: 1050, fov: 52 * DEG }};

function stopPlay() {{
  if (playTimer) {{
    clearInterval(playTimer);
    playTimer = null;
    btnPlay.innerHTML = "&#9654; Play";
    btnPlay.classList.remove("active");
  }}
}}

function openViewer(id) {{
  stopPlay();
  nightIdx = id;
  curNight = DATA.nights[id];
  frameIdx = 0;
  slider.value = 0;
  activeView = curNight.spot ? "spot" : "shul";

  // Pre-filter nearby buildings around shul & spot for ultra-fast 60fps 3D orbit
  const sx = curNight.spot ? curNight.spot.x : SHUL.x;
  const sy = curNight.spot ? curNight.spot.y : SHUL.y;
  localBuildings = BUILDINGS.filter(b =>
    Math.hypot(b.cx - sx, b.cy - sy) < 1100 || Math.hypot(b.cx - SHUL.x, b.cy - SHUL.y) < 1100
  );
  fpCenterAz = curNight.frames[15][0];

  document.getElementById("tickStart").textContent = curNight.wait_min
    ? `+${{curNight.wait_min}}m (${{curNight.frames[0][2]}})`
    : `Tzeis (${{curNight.frames[0][2]}})`;
  document.getElementById("tickEnd").textContent = `+30m (${{curNight.frames[30][2]}})`;

  overlay.classList.add("open");
  setPreset("iso", false);
  recomputeAndRender();
  requestAnimationFrame(() => recomputeAndRender());
}}

function closeViewer() {{
  stopPlay();
  overlay.classList.remove("open");
}}

document.getElementById("btnBack").onclick = closeViewer;
document.getElementById("btnPrev").onclick = () => {{
  const list = getFilteredNights();
  const pos = list.findIndex(n => n.id === nightIdx);
  const prev = list[(pos - 1 + list.length) % list.length];
  if (prev) openViewer(prev.id);
}};
document.getElementById("btnNext").onclick = () => {{
  const list = getFilteredNights();
  const pos = list.findIndex(n => n.id === nightIdx);
  const next = list[(pos + 1) % list.length];
  if (next) openViewer(next.id);
}};
window.addEventListener("keydown", e => {{ if (e.key === "Escape" && overlay.classList.contains("open")) closeViewer(); }});

function recomputeAndRender() {{
  if (!curNight) return;
  const fr = curNight.frames[frameIdx];
  const [az, alt, timeStr, compass] = fr;
  curShulTrace = traceRay(SHUL.x, SHUL.y, SHUL.g, az, alt);

  if (spotMode === "live") {{
    const liveRes = findClosestSpotAt(az, alt);
    if (liveRes) {{
      curActiveSpot = liveRes.spot;
      curSpotTrace = liveRes.trace;
    }} else {{
      curActiveSpot = null;
      curSpotTrace = null;
    }}
  }} else {{
    curActiveSpot = curNight.spot;
    curSpotTrace = curActiveSpot
      ? traceRay(curActiveSpot.x, curActiveSpot.y, curActiveSpot.g, az, alt)
      : null;
  }}

  // Ensure localBuildings covers the active spot as well as the shul
  const sx = curActiveSpot ? curActiveSpot.x : SHUL.x;
  const sy = curActiveSpot ? curActiveSpot.y : SHUL.y;
  localBuildings = BUILDINGS.filter(b =>
    Math.hypot(b.cx - sx, b.cy - sy) < 1100 || Math.hypot(b.cx - SHUL.x, b.cy - SHUL.y) < 1100
  );

  // Update header & pills
  const tagPart = curNight.special_tag ? ` — ${{curNight.special_tag}}` : "";
  document.getElementById("vTitle").textContent = `${{curNight.date_disp}} (${{curNight.heb_date}} 5787)${{tagPart}}`;
  const waitTxt = curNight.wait_min ? ` • Showing +${{curNight.wait_min}}m clear window` : "";
  document.getElementById("vSub").textContent = `Young Israel of the West Side (210 W 91st St) • Tzeis ${{curNight.tzeis_str}} • ${{curNight.illum_pct}}% lit${{waitTxt}}`;

  document.getElementById("lblTime").textContent = `${{timeStr}} (+${{frameIdx}} min)`;
  document.getElementById("lblMoon").innerHTML = `Moon: <strong>${{compass}} (${{az.toFixed(1)}}&deg;)</strong> &bull; Alt <strong>${{alt.toFixed(1)}}&deg;</strong>`;

  const modeLbl = spotMode === "live" ? "Closest Now" : "20-Min Spot";
  const pillSpot = document.getElementById("pillSpot");
  const btnFpSpot = document.getElementById("btnFpSpot");
  const btnProfSpot = document.getElementById("btnProfSpot");
  if (curSpotTrace && curActiveSpot) {{
    const sc = curSpotTrace.clearance;
    const walkTag = curActiveSpot.walk_ft <= 20 ? "0 ft" : `${{curActiveSpot.walk_ft.toLocaleString()}} ft`;
    pillSpot.style.display = "flex";
    btnFpSpot.style.display = "inline-block";
    btnProfSpot.style.display = "inline-block";
    pillSpot.className = "pill " + (curSpotTrace.isClear ? "clear" : "blocked");
    pillSpot.innerHTML = `<span>${{modeLbl}}:</span> <strong>${{curActiveSpot.short_name}}</strong> (${{walkTag}}, <strong>${{sc >= 0 ? "+" : ""}}${{sc.toFixed(1)}}&deg;</strong>)`;
    document.getElementById("legSpot").textContent = `${{modeLbl}}: ${{curActiveSpot.short_name}} (${{sc >= 0 ? "+" : ""}}${{sc.toFixed(1)}}°)`;
    btnFpSpot.textContent = modeLbl;
    btnProfSpot.textContent = `${{modeLbl}} (${{sc >= 0 ? "+" : ""}}${{sc.toFixed(1)}}°)`;
    btnFpSpot.className = "ctrl " + (activeView === "spot" ? (curSpotTrace.isClear ? "active-green" : "active-red") : "");
    btnProfSpot.className = "ctrl " + (activeView === "spot" ? (curSpotTrace.isClear ? "active-green" : "active-red") : "");
  }} else {{
    pillSpot.style.display = "flex";
    pillSpot.className = "pill blocked";
    pillSpot.innerHTML = `<span>${{modeLbl}}:</span> <strong>Blocked within 6 blocks</strong>`;
    btnFpSpot.style.display = "none";
    btnProfSpot.style.display = "none";
    document.getElementById("legSpot").textContent = "No Clear Spot Within 6 Blocks";
  }}

  const shc = curShulTrace.clearance;
  const pillShul = document.getElementById("pillShul");
  pillShul.className = "pill " + (curShulTrace.isClear ? "clear" : "blocked");
  pillShul.innerHTML = `<span>Outside Shul:</span> <strong>${{curShulTrace.isClear ? "Clear" : "Blocked"}} (${{shc >= 0 ? "+" : ""}}${{shc.toFixed(1)}}&deg;)</strong>`;
  document.getElementById("legShul").textContent = `Outside Shul (${{shc >= 0 ? "+" : ""}}${{shc.toFixed(1)}}°)`;
  document.getElementById("btnProfShul").textContent = `Outside Shul (${{shc >= 0 ? "+" : ""}}${{shc.toFixed(1)}}°)`;
  document.getElementById("btnFpShul").className = "ctrl " + (activeView === "shul" ? (curShulTrace.isClear ? "active-green" : "active-red") : "");
  document.getElementById("btnProfShul").className = "ctrl " + (activeView === "shul" ? (curShulTrace.isClear ? "active-green" : "active-red") : "");
  document.getElementById("profTitle").innerHTML = `2D Elevation Cross-Section Along Azimuth ${{az.toFixed(1)}}&deg; (${{compass}}) <span class="hint">&bull; Dashed cap = +4 ft parapet</span>`;

  draw3D();
  drawFirstPerson();
  drawProfile();
}}

// ---------------- CANVAS HELPERS ----------------
function resizeCanvas(canvas) {{
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {{ w: rect.width, h: rect.height, ctx }};
}}

function project3D(x, y, z, w, h, camPos, basis, f) {{
  const rx = x - camPos.x, ry = y - camPos.y, rz = z - camPos.z;
  const cx = rx * basis.rx + ry * basis.ry + rz * basis.rz;
  const cy = rx * basis.ux + ry * basis.uy + rz * basis.uz;
  const cz = rx * basis.fx + ry * basis.fy + rz * basis.fz;
  if (cz <= 5) return null;
  return {{ sx: w * 0.5 + (cx / cz) * f, sy: h * 0.5 - (cy / cz) * f, cz }};
}}

function makeCameraBasis(camPos, tx, ty, tz) {{
  let fx = tx - camPos.x, fy = ty - camPos.y, fz = tz - camPos.z;
  const fl = Math.hypot(fx, fy, fz) || 1;
  fx /= fl; fy /= fl; fz /= fl;
  let rx = fy, ry = -fx, rz = 0;
  let rl = Math.hypot(rx, ry, rz);
  if (rl < 1e-4) {{ rx = 1; ry = 0; rz = 0; rl = 1; }}
  rx /= rl; ry /= rl; rz /= rl;
  return {{ fx, fy, fz, rx, ry, rz, ux: ry * fz - rz * fy, uy: rz * fx - rx * fz, uz: rx * fy - ry * fx }};
}}

function draw3D() {{
  if (!curNight || !curShulTrace) return;
  const {{ w, h, ctx }} = resizeCanvas(c3d);
  const [az, alt] = curNight.frames[frameIdx];
  const rayDx = Math.sin(az * DEG), rayDy = Math.cos(az * DEG);
  const tanAlt = Math.tan(Math.max(0.5, alt) * DEG);

  ctx.fillStyle = "#0b1120";
  ctx.fillRect(0, 0, w, h);

  const camPos = {{
    x: cam.targetX - Math.cos(cam.pitch) * Math.sin(cam.yaw) * cam.dist,
    y: cam.targetY - Math.cos(cam.pitch) * Math.cos(cam.yaw) * cam.dist,
    z: cam.targetZ + Math.sin(cam.pitch) * cam.dist,
  }};
  const basis = makeCameraBasis(camPos, cam.targetX, cam.targetY, cam.targetZ);
  const f = (h * 0.5) / Math.tan(cam.fov * 0.5);

  ctx.strokeStyle = "rgba(148, 163, 184, 0.24)";
  ctx.lineWidth = 1.3;
  for (const pts of DATA.streets) {{
    ctx.beginPath();
    let started = false;
    for (const pt of pts) {{
      const p = project3D(pt[0], pt[1], 90, w, h, camPos, basis, f);
      if (!p) {{ started = false; continue; }}
      if (!started) {{ ctx.moveTo(p.sx, p.sy); started = true; }}
      else ctx.lineTo(p.sx, p.sy);
    }}
    ctx.stroke();
  }}

  const blockId = !curShulTrace.isClear ? curShulTrace.blockingId : null;
  const limitId = curSpotTrace ? curSpotTrace.limitingId : null;

  const sortedB = localBuildings.map(b => ({{
    b,
    d2: (b.cx - camPos.x) ** 2 + (b.cy - camPos.y) ** 2 + ((b.g + b.h * 0.5) - camPos.z) ** 2,
  }})).sort((a, b) => b.d2 - a.d2);

  for (const {{ b }} of sortedB) {{
    const pts = b.pts;
    const isBlock = (b.id === blockId);
    const isLimit = (b.id === limitId && !isBlock);
    const botP = [], topP = [];
    let anyVis = false;
    for (let i = 0; i < pts.length; i++) {{
      const pb = project3D(pts[i][0], pts[i][1], b.g, w, h, camPos, basis, f);
      const pt = project3D(pts[i][0], pts[i][1], b.top, w, h, camPos, basis, f);
      botP.push(pb); topP.push(pt);
      if (pb || pt) anyVis = true;
    }}
    if (!anyVis) continue;

    const hNorm = Math.min(1, b.h / 260);
    let wallFill, roofFill, strokeCol;
    if (isBlock) {{
      wallFill = "rgba(220,38,38,0.85)"; roofFill = "rgba(248,113,113,0.92)"; strokeCol = "#fecaca";
    }} else if (isLimit) {{
      wallFill = "rgba(217,119,6,0.82)"; roofFill = "rgba(251,191,36,0.9)"; strokeCol = "#fef08a";
    }} else {{
      const r = Math.round(35 + hNorm * 35), g = Math.round(48 + hNorm * 45), bl = Math.round(72 + hNorm * 65);
      wallFill = `rgba(${{r}},${{g}},${{bl}},0.82)`;
      roofFill = `rgba(${{r+25}},${{g+28}},${{bl+35}},0.90)`;
      strokeCol = "rgba(148,163,184,0.22)";
    }}

    const walls = [];
    for (let i = 0; i < pts.length - 1; i++) {{
      const b0 = botP[i], b1 = botP[i+1], t0 = topP[i], t1 = topP[i+1];
      if (!b0 || !b1 || !t0 || !t1) continue;
      walls.push({{ b0, b1, t0, t1, avgZ: (b0.cz + b1.cz + t0.cz + t1.cz) * 0.25 }});
    }}
    walls.sort((a, b) => b.avgZ - a.avgZ);

    ctx.lineWidth = isBlock || isLimit ? 1.2 : 0.6;
    ctx.strokeStyle = strokeCol;
    ctx.fillStyle = wallFill;
    for (const wl of walls) {{
      ctx.beginPath();
      ctx.moveTo(wl.b0.sx, wl.b0.sy); ctx.lineTo(wl.b1.sx, wl.b1.sy);
      ctx.lineTo(wl.t1.sx, wl.t1.sy); ctx.lineTo(wl.t0.sx, wl.t0.sy);
      ctx.closePath(); ctx.fill(); ctx.stroke();
    }}
    if (topP.every(p => p !== null)) {{
      ctx.fillStyle = roofFill;
      ctx.beginPath();
      ctx.moveTo(topP[0].sx, topP[0].sy);
      for (let i = 1; i < topP.length; i++) ctx.lineTo(topP[i].sx, topP[i].sy);
      ctx.closePath(); ctx.fill(); ctx.stroke();
    }}
  }}

  function drawRay3D(ox, oy, oz, len, color, width, dashed=false) {{
    ctx.save();
    ctx.strokeStyle = color; ctx.lineWidth = width;
    if (dashed) ctx.setLineDash([6, 4]);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i <= 28; i++) {{
      const t = len * i / 28;
      const p = project3D(ox + rayDx * t, oy + rayDy * t, oz + t * tanAlt, w, h, camPos, basis, f);
      if (!p) {{ started = false; continue; }}
      if (!started) {{ ctx.moveTo(p.sx, p.sy); started = true; }}
      else ctx.lineTo(p.sx, p.sy);
    }}
    ctx.stroke();
    ctx.restore();
  }}

  const fb = curShulTrace.firstBlock;
  if (fb) {{
    drawRay3D(SHUL.x, SHUL.y, curShulTrace.oz, fb.tEnter, "#ef4444", 3.2, false);
    drawRay3D(SHUL.x + rayDx * fb.tEnter, SHUL.y + rayDy * fb.tEnter, curShulTrace.oz + fb.tEnter * tanAlt, 900 - fb.tEnter, "rgba(239,68,68,0.4)", 2, true);
    const hp = project3D(SHUL.x + rayDx * fb.tEnter, SHUL.y + rayDy * fb.tEnter, curShulTrace.oz + fb.tEnter * tanAlt, w, h, camPos, basis, f);
    if (hp) {{
      ctx.fillStyle = "#fef08a"; ctx.strokeStyle = "#dc2626"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(hp.sx, hp.sy, 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }}
  }} else {{
    drawRay3D(SHUL.x, SHUL.y, curShulTrace.oz, 900, curShulTrace.isClear ? "#38bdf8" : "#f59e0b", 3.2, false);
  }}

  if (curSpotTrace && curActiveSpot) {{
    const sp = curActiveSpot;
    drawRay3D(sp.x, sp.y, curSpotTrace.oz, 950, curSpotTrace.isClear ? "#22c55e" : "#ef4444", 3.8, false);
    const mp = project3D(sp.x + rayDx * 950, sp.y + rayDy * 950, curSpotTrace.oz + 950 * tanAlt, w, h, camPos, basis, f);
    if (mp) {{
      ctx.fillStyle = "#fef08a"; ctx.shadowColor = "#fde047"; ctx.shadowBlur = 14;
      ctx.beginPath(); ctx.arc(mp.sx, mp.sy, 8, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
    }}
  }}

  const pinBoxes = [];
  function drawPin(x, y, z, label, col, labelDy) {{
    const p = project3D(x, y, z, w, h, camPos, basis, f);
    if (!p) return;
    ctx.fillStyle = col; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(p.sx, p.sy, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.font = "700 11px -apple-system, sans-serif";
    const tw = ctx.measureText(label).width;
    const rx = p.sx + 9, ry = p.sy + labelDy;
    ctx.fillStyle = "rgba(15,23,42,0.88)";
    ctx.fillRect(rx, ry, tw + 10, 18);
    ctx.fillStyle = "#f8fafc";
    ctx.fillText(label, rx + 5, ry + 13);
    pinBoxes.push({{ x0: p.sx - 12, y0: Math.min(p.sy - 12, ry - 4), x1: rx + tw + 16, y1: Math.max(p.sy + 12, ry + 22) }});
  }}
  drawPin(SHUL.x, SHUL.y, curShulTrace.oz, "210 W 91st (Shul)", "#3b82f6", 10);
  if (curActiveSpot && curActiveSpot.walk_ft > 10) {{
    drawPin(curActiveSpot.x, curActiveSpot.y, curSpotTrace.oz, curActiveSpot.short_name, "#22c55e", -22);
  }}

  // Draw 3D street name labels (at most 1 per unique street, closest to viewport center, no pin overlap)
  ctx.font = "600 10px -apple-system, sans-serif";
  const bestPerStreet = new Map();
  for (const sl of DATA.street_labels) {{
    const p = project3D(sl[1], sl[2], 96, w, h, camPos, basis, f);
    if (!p || p.cz > 1850 || p.sx < 45 || p.sx > w - 85 || p.sy < 22 || p.sy > h - 25) continue;
    if (p.sx < 215 && p.sy > h - 108) continue;
    if (p.sx > w - 105 && p.sy < 105) continue;
    if (pinBoxes.some(b => p.sx + 36 > b.x0 && p.sx - 36 < b.x1 && p.sy + 10 > b.y0 && p.sy - 10 < b.y1)) continue;
    const centerDist = Math.hypot(p.sx - w * 0.5, p.sy - h * 0.5);
    const prev = bestPerStreet.get(sl[0]);
    if (!prev || centerDist < prev.centerDist) {{
      bestPerStreet.set(sl[0], {{ name: sl[0], sx: p.sx, sy: p.sy, centerDist }});
    }}
  }}
  const placedLabels = [];
  for (const item of [...bestPerStreet.values()].sort((a, b) => a.centerDist - b.centerDist)) {{
    if (placedLabels.some(q => Math.abs(q.x - item.sx) < 68 && Math.abs(q.y - item.sy) < 20)) continue;
    placedLabels.push({{ x: item.sx, y: item.sy }});
    const tw = ctx.measureText(item.name).width;
    ctx.fillStyle = "rgba(15, 23, 42, 0.78)";
    ctx.fillRect(item.sx - tw * 0.5 - 4, item.sy - 7, tw + 8, 14);
    ctx.fillStyle = "#cbd5e1";
    ctx.fillText(item.name, item.sx - tw * 0.5, item.sy + 3.5);
  }}

  // Draw live rotating compass rose (top-right)
  const cx = w - 46, cy = 46, r = 32;
  ctx.save();
  ctx.fillStyle = "rgba(15, 23, 42, 0.88)";
  ctx.strokeStyle = "#334155";
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

  // Helper: map world azimuth (0=N, 90=E) to compass canvas (x, y) given current cam.yaw
  const compPt = (azRad, rad) => {{
    const rel = azRad - cam.yaw;
    return [cx + Math.sin(rel) * rad, cy - Math.cos(rel) * rad];
  }};

  // Subtle crosshairs
  ctx.strokeStyle = "rgba(148, 163, 184, 0.22)";
  ctx.lineWidth = 1;
  const [nx0, ny0] = compPt(0, r - 11), [sx0, sy0] = compPt(Math.PI, r - 11);
  const [ex0, ey0] = compPt(Math.PI * 0.5, r - 11), [wx0, wy0] = compPt(Math.PI * 1.5, r - 11);
  ctx.beginPath(); ctx.moveTo(nx0, ny0); ctx.lineTo(sx0, sy0); ctx.moveTo(ex0, ey0); ctx.lineTo(wx0, wy0); ctx.stroke();

  // North red needle
  const [ntx, nty] = compPt(0, r - 10);
  const [nlx, nly] = compPt(Math.PI * 0.5, 4);
  const [nrx, nry] = compPt(Math.PI * 1.5, 4);
  ctx.fillStyle = "#ef4444";
  ctx.beginPath(); ctx.moveTo(ntx, nty); ctx.lineTo(nlx, nly); ctx.lineTo(nrx, nry); ctx.closePath(); ctx.fill();

  // South gray needle
  const [stx, sty] = compPt(Math.PI, r - 12);
  ctx.fillStyle = "#64748b";
  ctx.beginPath(); ctx.moveTo(stx, sty); ctx.lineTo(nlx, nly); ctx.lineTo(nrx, nry); ctx.closePath(); ctx.fill();

  // Moon azimuth marker on compass rim
  const [mmx, mmy] = compPt(az * DEG, r - 2);
  ctx.fillStyle = "#fde047";
  ctx.strokeStyle = "#0f172a";
  ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.arc(mmx, mmy, 4.2, 0, Math.PI * 2); ctx.fill(); ctx.stroke();

  // Cardinal labels
  ctx.font = "700 9.5px -apple-system, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  const cardinals = [["N", 0, "#f87171"], ["E", Math.PI * 0.5, "#94a3b8"], ["S", Math.PI, "#94a3b8"], ["W", Math.PI * 1.5, "#94a3b8"]];
  for (const [lbl, radA, col] of cardinals) {{
    const [lx, ly] = compPt(radA, r - 7);
    ctx.fillStyle = col;
    ctx.fillText(lbl, lx, ly);
  }}
  ctx.restore();
}}

function drawFirstPerson() {{
  const {{ w, h, ctx }} = resizeCanvas(cFp);
  const tr = (activeView === "spot" && curSpotTrace) ? curSpotTrace : curShulTrace;
  const [az, alt] = curNight.frames[frameIdx];
  const ox = tr.ox, oy = tr.oy, oz = tr.oz;

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, "#020617"); grad.addColorStop(0.55, "#0f172a"); grad.addColorStop(1, "#1e293b");
  ctx.fillStyle = grad; ctx.fillRect(0, 0, w, h);

  const maxAlt = Math.max(52, Math.ceil((Math.max(...curNight.frames.map(f => f[1])) + 12) / 10) * 10);
  const altMin = -4, azSpan = 90;
  const toX = a => {{ let d = a - fpCenterAz; while (d > 180) d -= 360; while (d < -180) d += 360; return w * 0.5 + (d / azSpan) * w; }};
  const toY = e => h - ((e - altMin) / (maxAlt - altMin)) * h;

  ctx.strokeStyle = "rgba(148,163,184,0.16)"; ctx.fillStyle = "#64748b";
  ctx.font = "10px -apple-system, sans-serif"; ctx.lineWidth = 1;
  for (let a = 0; a <= maxAlt; a += 10) {{
    const y = toY(a);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    ctx.fillText(a + "°", 6, y - 3);
  }}
  for (let da = -40; da <= 40; da += 10) {{
    const x = toX(fpCenterAz + da);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    if (da === 0) {{ ctx.fillStyle = "#94a3b8"; ctx.fillText(`${{fpCenterAz.toFixed(1)}}°`, x + 4, 14); ctx.fillStyle = "#64748b"; }}
  }}

  // 30-min trajectory arc
  ctx.save();
  ctx.strokeStyle = "rgba(253,224,71,0.45)"; ctx.lineWidth = 1.5; ctx.setLineDash([3, 3]);
  ctx.beginPath();
  curNight.frames.forEach((f, i) => {{ const px = toX(f[0]), py = toY(f[1]); if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); }});
  ctx.stroke(); ctx.restore();

  // Moon disc behind buildings
  const mx = toX(az), my = toY(alt);
  ctx.save();
  ctx.fillStyle = "#fef9c3"; ctx.shadowColor = "#fde047"; ctx.shadowBlur = 18;
  ctx.beginPath(); ctx.arc(mx, my, 10, 0, Math.PI * 2); ctx.fill();
  ctx.restore();

  const sortedB = localBuildings.map(b => ({{ b, d2: (b.cx - ox) ** 2 + (b.cy - oy) ** 2 }}))
    .filter(x => x.d2 < 1600 * 1600)
    .sort((a, b) => b.d2 - a.d2);

  for (const {{ b, d2 }} of sortedB) {{
    const isBlock = !tr.isClear && b.id === tr.blockingId;
    const isLimit = tr.isClear && b.id === tr.limitingId;
    const shade = Math.max(0.25, 1 - Math.sqrt(d2) / 1600);
    const pts = b.pts;
    for (let i = 0; i < pts.length - 1; i++) {{
      const x1 = pts[i][0] - ox, y1 = pts[i][1] - oy;
      const x2 = pts[i+1][0] - ox, y2 = pts[i+1][1] - oy;
      const d1 = Math.hypot(x1, y1), d2e = Math.hypot(x2, y2);
      if (d1 < 5 || d2e < 5) continue;
      let az1 = Math.atan2(x1, y1) * RAD; if (az1 < 0) az1 += 360;
      let az2 = Math.atan2(x2, y2) * RAD; if (az2 < 0) az2 += 360;
      let da1 = az1 - fpCenterAz; while (da1 > 180) da1 -= 360; while (da1 < -180) da1 += 360;
      let da2 = az2 - fpCenterAz; while (da2 > 180) da2 -= 360; while (da2 < -180) da2 += 360;
      if (Math.abs(da1) > 65 && Math.abs(da2) > 65) continue;
      if (Math.abs(da1 - da2) > 120) continue;

      ctx.beginPath();
      ctx.moveTo(toX(az1), toY(Math.atan2(b.g - oz, d1) * RAD));
      ctx.lineTo(toX(az2), toY(Math.atan2(b.g - oz, d2e) * RAD));
      ctx.lineTo(toX(az2), toY(Math.atan2(b.top - oz, d2e) * RAD));
      ctx.lineTo(toX(az1), toY(Math.atan2(b.top - oz, d1) * RAD));
      ctx.closePath();

      if (isBlock) {{ ctx.fillStyle = "rgba(220,38,38,0.9)"; ctx.strokeStyle = "#fca5a5"; }}
      else if (isLimit) {{ ctx.fillStyle = "rgba(217,119,6,0.88)"; ctx.strokeStyle = "#fde047"; }}
      else {{ const c = Math.round(28 + shade * 42); ctx.fillStyle = `rgba(${{c}},${{c+10}},${{c+26}},0.94)`; ctx.strokeStyle = "rgba(148,163,184,0.22)"; }}
      ctx.lineWidth = isBlock || isLimit ? 1.2 : 0.7;
      ctx.fill(); ctx.stroke();
    }}
  }}

  ctx.strokeStyle = tr.isClear ? "#22c55e" : "#ef4444";
  ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
  ctx.beginPath(); ctx.arc(mx, my, 15, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);

  ctx.font = "600 10px -apple-system, sans-serif"; ctx.fillStyle = "#fde047";
  const fs = curNight.frames[0], fe = curNight.frames[30];
  ctx.fillText(fs[2], toX(fs[0]) - 46, toY(fs[1]) + 13);
  ctx.fillText(fe[2], toX(fe[0]) + 10, toY(fe[1]) - 6);

  const badge = tr.isClear
    ? `CLEAR: Moon +${{tr.clearance.toFixed(1)}}° above skyline`
    : (tr.clearance >= 0 ? `TIGHT: +${{tr.clearance.toFixed(1)}}° (< 1.5° margin)` : `BLOCKED: Building rises ${{Math.abs(tr.clearance).toFixed(1)}}° above Moon`);
  ctx.font = "700 12px -apple-system, sans-serif";
  const bw = ctx.measureText(badge).width + 18;
  ctx.fillStyle = tr.isClear ? "rgba(21,128,61,0.92)" : "rgba(185,28,28,0.92)";
  ctx.fillRect(w - bw - 10, 10, bw, 24);
  ctx.fillStyle = "#fff"; ctx.fillText(badge, w - bw - 1, 26);
}}

function drawProfile() {{
  const {{ w, h, ctx }} = resizeCanvas(cProf);
  const tr = (activeView === "spot" && curSpotTrace) ? curSpotTrace : curShulTrace;
  const alt = curNight.frames[frameIdx][1];
  const tanAlt = Math.tan(Math.max(0.5, alt) * DEG);

  ctx.fillStyle = "#0b1120"; ctx.fillRect(0, 0, w, h);
  const padL = 52, padR = 24, padT = 18, padB = 28;
  const pw = w - padL - padR, ph = h - padT - padB;
  const maxDist = 1100, minElev = 40;
  const maxElev = Math.max(460, tr.oz + maxDist * Math.min(tanAlt, 1.0) * 0.6);
  const xOf = d => padL + (d / maxDist) * pw;
  const yOf = z => padT + ph - ((z - minElev) / (maxElev - minElev)) * ph;

  ctx.strokeStyle = "rgba(148,163,184,0.14)"; ctx.fillStyle = "#94a3b8";
  ctx.font = "10px -apple-system, sans-serif"; ctx.lineWidth = 1;
  for (let d = 0; d <= maxDist; d += 100) {{
    const x = xOf(d);
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ph); ctx.stroke();
    ctx.fillText(d + " ft", x - 12, h - 8);
  }}
  for (let z = 100; z <= maxElev; z += 100) {{
    const y = yOf(z);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillText(z + " ft", 8, y + 3);
  }}

  ctx.strokeStyle = "#475569"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(xOf(0), yOf(tr.g)); ctx.lineTo(xOf(maxDist), yOf(tr.g)); ctx.stroke();

  for (const s of tr.slices) {{
    if (s.tEnter > maxDist) continue;
    const x1 = xOf(s.tEnter), x2 = xOf(Math.min(maxDist, s.tExit));
    const bw = Math.max(4, x2 - x1);
    const yG = yOf(s.g), yR = yOf(s.roof), yT = yOf(s.top);
    const isBlock = s.blocks, isLimit = s.id === tr.limitingId;
    ctx.fillStyle = isBlock ? "rgba(220,38,38,0.78)" : (isLimit ? "rgba(217,119,6,0.75)" : "rgba(71,85,105,0.75)");
    ctx.fillRect(x1, yR, bw, yG - yR);
    ctx.strokeStyle = isBlock ? "#fca5a5" : (isLimit ? "#fde047" : "#94a3b8");
    ctx.lineWidth = 1; ctx.strokeRect(x1, yR, bw, yG - yR);
    ctx.strokeStyle = "#e2e8f0"; ctx.setLineDash([3, 2]);
    ctx.beginPath(); ctx.moveTo(x1, yT); ctx.lineTo(x1 + bw, yT); ctx.stroke(); ctx.setLineDash([]);
    if (isBlock || isLimit || s.h >= 120) {{
      ctx.fillStyle = isBlock ? "#fca5a5" : (isLimit ? "#fde047" : "#cbd5e1");
      ctx.font = "600 10px -apple-system, sans-serif";
      ctx.fillText(`${{s.h}} ft (${{s.obsAngle.toFixed(1)}}°)`, x1, yT - 4);
    }}
  }}

  const rayEndD = Math.min(maxDist, (maxElev - tr.oz) / tanAlt);
  ctx.strokeStyle = tr.isClear ? "#22c55e" : "#ef4444"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(xOf(0), yOf(tr.oz)); ctx.lineTo(xOf(rayEndD), yOf(tr.oz + rayEndD * tanAlt)); ctx.stroke();

  ctx.fillStyle = "#38bdf8";
  ctx.beginPath(); ctx.arc(xOf(0), yOf(tr.oz), 5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#e2e8f0"; ctx.font = "700 11px -apple-system, sans-serif";
  ctx.fillText(`Observer (eye ${{tr.oz.toFixed(0)}} ft) → Ray ${{alt.toFixed(1)}}°`, xOf(0) + 10, yOf(tr.oz) - 8);
}}

// ---------------- CONTROLS ----------------
let dragging = false, lastX = 0, lastY = 0;
c3d.addEventListener("mousedown", e => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; }});
window.addEventListener("mouseup", () => {{ dragging = false; }});
window.addEventListener("mousemove", e => {{
  if (!dragging) return;
  cam.yaw += (e.clientX - lastX) * 0.008;
  cam.pitch = Math.max(5 * DEG, Math.min(86 * DEG, cam.pitch + (e.clientY - lastY) * 0.008));
  lastX = e.clientX; lastY = e.clientY;
  draw3D();
}});
c3d.addEventListener("wheel", e => {{
  e.preventDefault();
  cam.dist = Math.max(250, Math.min(2600, cam.dist * (1 + e.deltaY * 0.001)));
  draw3D();
}}, {{ passive: false }});

function setPreset(name, shouldDraw=true) {{
  const [az] = curNight.frames[frameIdx];
  const rdx = Math.sin(az * DEG), rdy = Math.cos(az * DEG);
  const sp = curActiveSpot || curNight.spot || SHUL;
  for (const id of ["btnCamIso", "btnCamTop"]) document.getElementById(id).classList.remove("active");
  if (name === "iso") {{
    document.getElementById("btnCamIso").classList.add("active");
    cam.targetX = (SHUL.x + sp.x) * 0.5 + rdx * 140;
    cam.targetY = (SHUL.y + sp.y) * 0.5 + rdy * 140;
    cam.targetZ = 120; cam.yaw = (az - 230) * DEG; cam.pitch = 34 * DEG;
    cam.dist = Math.max(950, Math.hypot(sp.x - SHUL.x, sp.y - SHUL.y) * 1.1 + 500);
  }} else if (name === "top") {{
    document.getElementById("btnCamTop").classList.add("active");
    cam.targetX = (SHUL.x + sp.x) * 0.5 + rdx * 140;
    cam.targetY = (SHUL.y + sp.y) * 0.5 + rdy * 140;
    cam.targetZ = 100; cam.yaw = 0; cam.pitch = 85 * DEG;
    cam.dist = Math.max(1150, Math.hypot(sp.x - SHUL.x, sp.y - SHUL.y) * 1.2 + 650);
  }}
  if (shouldDraw && curNight && curShulTrace) draw3D();
}}

document.getElementById("btnCamIso").onclick = () => setPreset("iso");
document.getElementById("btnCamTop").onclick = () => setPreset("top");
document.getElementById("btnFpSpot").onclick = () => {{ activeView = "spot"; recomputeAndRender(); }};
document.getElementById("btnFpShul").onclick = () => {{ activeView = "shul"; recomputeAndRender(); }};
document.getElementById("btnProfSpot").onclick = () => {{ activeView = "spot"; recomputeAndRender(); }};
document.getElementById("btnProfShul").onclick = () => {{ activeView = "shul"; recomputeAndRender(); }};

function setSpotMode(mode) {{
  spotMode = mode;
  document.getElementById("btnModeStable").classList.toggle("active", mode === "stable");
  document.getElementById("btnModeLive").classList.toggle("active", mode === "live");
  if (mode === "live" && !curActiveSpot) activeView = "spot";
  recomputeAndRender();
}}
document.getElementById("btnModeStable").onclick = () => setSpotMode("stable");
document.getElementById("btnModeLive").onclick = () => setSpotMode("live");

slider.addEventListener("input", e => {{ frameIdx = parseInt(e.target.value, 10); recomputeAndRender(); }});
btnPlay.onclick = () => {{
  if (playTimer) {{ stopPlay(); return; }}
  if (frameIdx >= 30) frameIdx = 0;
  btnPlay.innerHTML = "&#9646;&#9646; Pause";
  btnPlay.classList.add("active");
  playTimer = setInterval(() => {{
    frameIdx = (frameIdx + 1) % 31;
    slider.value = frameIdx;
    recomputeAndRender();
  }}, 240);
}};

window.addEventListener("resize", () => {{ if (overlay.classList.contains("open")) recomputeAndRender(); }});
renderCalendar();
// Optional deep link: #2026-11-21 opens that night's 3D viewer directly
if (location.hash && location.hash.length > 1) {{
  const target = location.hash.slice(1);
  const found = DATA.nights.find(n => n.civil_date === target);
  if (found) openViewer(found.id);
}}
</script>
</body>
</html>
"""
    out_path = os.path.join(OUT_DIR, "YIWS_Kiddush_Levanah_5787_Interactive.html")
    with open(out_path, "w") as f:
        f.write(html_doc)
    size_kb = os.path.getsize(out_path) / 1024.0
    print(f"Wrote {out_path} ({size_kb:.1f} KB — {len(nights_payload)} nights, {len(buildings_payload)} buildings, {len(streets_payload)} streets)")


if __name__ == "__main__":
    build_interactive_html()

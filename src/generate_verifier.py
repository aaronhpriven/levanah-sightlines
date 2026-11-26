#!/usr/bin/env python3
"""
Generate visual verification artifacts for a specific Kiddush Levanah night:
  1. Self-contained interactive 3D + First-Person + 2D Cross-Section HTML viewer
  2. Google Earth 3D KML overlay with eye-level cameras and 3D sightline rays

Usage:
  python3 src/generate_verifier.py 2026-11-21
"""

from __future__ import annotations

import datetime
import json
import math
import os
import sys
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calendar_moon import UTC, compass_direction, moon_alt_az
from visibility import (
    DEG,
    FT_PER_METER,
    RAD,
    SHUL_LAT,
    SHUL_LON,
    VisibilityModel,
    ft_to_latlon,
    ray_segment_intersect,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUT_DIR, exist_ok=True)


def trace_ray_profile(
    vm: VisibilityModel,
    ox: float,
    oy: float,
    ground_ft: float,
    az_deg: float,
    alt_deg: float,
    eye_height_ft: float = 5.5,
    max_dist_ft: float = 1600.0,
) -> dict:
    """
    Trace a 3D ray and return every building slice intersected along the ray,
    ordered by distance, along with exact entry/exit distances, heights, and
    obstruction angles.
    """
    az_rad = az_deg * DEG
    dx = math.sin(az_rad)
    dy = math.cos(az_rad)
    oz = ground_ft + eye_height_ft
    tan_alt = math.tan(alt_deg * DEG)

    slices = []
    max_obs_angle = 0.0
    blocking_idx = None
    limiting_idx = None

    for idx, b in enumerate(vm.buildings):
        ts = []
        for ring in b.rings:
            n = len(ring)
            for i in range(n - 1):
                x1, y1 = ring[i]
                x2, y2 = ring[i + 1]
                t = ray_segment_intersect(ox, oy, dx, dy, x1, y1, x2, y2)
                if t is not None and t <= max_dist_ft:
                    ts.append(t)
        if not ts:
            continue
        t_enter = min(ts)
        t_exit = max(ts) if len(ts) > 1 else min(max_dist_ft, t_enter + 40.0)
        dh = b.top_ft - oz
        obs_angle = math.atan2(dh, t_enter) * RAD if dh > 0 else 0.0
        ray_z_at_enter = oz + t_enter * tan_alt
        blocks = b.top_ft > ray_z_at_enter - 1e-6

        if obs_angle > max_obs_angle:
            max_obs_angle = obs_angle
            limiting_idx = idx
        if blocks and (blocking_idx is None or t_enter < slices[0]["t_enter"] if slices else True):
            pass

        slices.append({
            "b_idx": idx,
            "t_enter": round(t_enter, 1),
            "t_exit": round(t_exit, 1),
            "ground_ft": round(b.ground_ft, 1),
            "height_ft": round(b.height_ft, 1),
            "roof_ft": round(b.ground_ft + b.height_ft, 1),
            "top_ft": round(b.top_ft, 1),  # includes +4ft parapet buffer
            "ray_z_enter": round(ray_z_at_enter, 1),
            "obs_angle_deg": round(obs_angle, 2),
            "blocks": blocks,
        })

    slices.sort(key=lambda s: s["t_enter"])
    first_block = next((s for s in slices if s["blocks"]), None)
    if first_block:
        blocking_idx = first_block["b_idx"]

    clearance = round(alt_deg - max_obs_angle, 1)
    return {
        "ox": round(ox, 1),
        "oy": round(oy, 1),
        "ground_ft": round(ground_ft, 1),
        "oz": round(oz, 1),
        "az_deg": az_deg,
        "alt_deg": alt_deg,
        "max_obs_angle_deg": round(max_obs_angle, 1),
        "clearance_deg": clearance,
        "is_clear": clearance >= 1.5,
        "blocking_b_idx": blocking_idx,
        "limiting_b_idx": limiting_idx,
        "first_block": first_block,
        "slices": slices,
    }


def generate_kml(night: dict, shul: dict, spot: dict, shul_trace: dict, spot_trace: dict, out_path: str):
    az = night["moon_az_deg"]
    alt = night["moon_alt_deg"]
    az_rad = az * DEG
    dx = math.sin(az_rad)
    dy = math.cos(az_rad)
    tan_alt = math.tan(alt * DEG)

    def xy_to_lonlat(x: float, y: float) -> tuple[float, float]:
        lat, lon = ft_to_latlon(x, y)
        return lon, lat

    shul_lon, shul_lat = xy_to_lonlat(shul["x"], shul["y"])
    spot_lon, spot_lat = xy_to_lonlat(spot["x"], spot["y"])

    def build_ray_coords(ox: float, oy: float, oz_ft: float, length_ft: float, steps: int = 24) -> str:
        pts = []
        for i in range(steps + 1):
            t = length_ft * i / steps
            lon, lat = xy_to_lonlat(ox + dx * t, oy + dy * t)
            z_m = (oz_ft + t * tan_alt) / FT_PER_METER
            pts.append(f"{lon:.7f},{lat:.7f},{z_m:.2f}")
        return " ".join(pts)

    spot_ray_len = 1200.0
    shul_ray_len = 1200.0
    spot_ray_coords = build_ray_coords(spot["x"], spot["y"], spot_trace["oz"], spot_ray_len)
    shul_ray_coords = build_ray_coords(shul["x"], shul["y"], shul_trace["oz"], shul_ray_len)

    # Moon target point at end of recommended ray
    moon_lon, moon_lat = xy_to_lonlat(spot["x"] + dx * spot_ray_len, spot["y"] + dy * spot_ray_len)
    moon_z_m = (spot_trace["oz"] + spot_ray_len * tan_alt) / FT_PER_METER

    # First blocking hit point along the shul ray (if any)
    hit_placemark = ""
    if shul_trace["first_block"]:
        fb = shul_trace["first_block"]
        t_hit = fb["t_enter"]
        hx, hy = shul["x"] + dx * t_hit, shul["y"] + dy * t_hit
        hlon, hlat = xy_to_lonlat(hx, hy)
        hz_ray_m = fb["ray_z_enter"] / FT_PER_METER
        hz_roof_m = fb["top_ft"] / FT_PER_METER
        hit_placemark = f"""
      <Placemark>
        <name>Shul Ray Blocked Here ({fb['t_enter']:.0f} ft away)</name>
        <description><![CDATA[
          <b>Blocking Building</b><br/>
          Distance from Shul sidewalk: {fb['t_enter']:.0f} ft<br/>
          NYC Roof Elevation: {fb['roof_ft']:.0f} ft (+4 ft parapet = {fb['top_ft']:.0f} ft)<br/>
          Moon Ray Elevation here: {fb['ray_z_enter']:.0f} ft<br/>
          Building Top Angle: {fb['obs_angle_deg']:.1f}° (Moon is {alt:.1f}°)
        ]]></description>
        <styleUrl>#hitPin</styleUrl>
        <Point>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>{hlon:.7f},{hlat:.7f},{hz_ray_m:.2f}</coordinates>
        </Point>
      </Placemark>
      <Placemark>
        <name>Blocking Building Rooftop Reference</name>
        <styleUrl>#roofLine</styleUrl>
        <LineString>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>
            {hlon:.7f},{hlat:.7f},{hz_ray_m:.2f}
            {hlon:.7f},{hlat:.7f},{hz_roof_m:.2f}
          </coordinates>
        </LineString>
      </Placemark>"""

    # Tilt in KML Camera: 0 = straight down, 90 = horizontal, 90 + alt = looking up at alt!
    cam_tilt = 90.0 + alt
    eye_m = 5.5 / FT_PER_METER
    date_label = f"{night['day_of_week']}, {night['civil_date']} ({night['heb_date_str']})"

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>YIWS Kiddush Levanah 3D Verification — {xml_escape(date_label)}</name>
    <description><![CDATA[
      <b>Young Israel of the West Side (210 W 91st St)</b><br/>
      Night: {xml_escape(date_label)} &bull; Tzeis: 5:23 PM<br/>
      Moon: Azimuth {az:.1f}° ({night['moon_compass']}), Altitude {alt:.1f}°<br/>
      Recommended Spot: {xml_escape(spot['name'])} ({spot['walk_ft']} ft walk, +{spot_trace['clearance_deg']:.1f}° clearance)<br/>
      Outside Shul: Blocked ({shul_trace['clearance_deg']:.1f}°)<br/><br/>
      <i>Tip: Enable Google Earth's 3D Buildings layer, then double-click the "Eye-Level View" cameras in Folder 1 to verify the sightline against real photogrammetry.</i>
    ]]></description>

    <Style id="greenRay">
      <LineStyle><color>ff22c55e</color><width>5</width></LineStyle>
    </Style>
    <Style id="greenCurtain">
      <LineStyle><color>cc22c55e</color><width>2</width></LineStyle>
      <PolyStyle><color>3322c55e</color></PolyStyle>
    </Style>
    <Style id="redRay">
      <LineStyle><color>ff4444ef</color><width>4</width></LineStyle>
    </Style>
    <Style id="roofLine">
      <LineStyle><color>ff00d4ff</color><width>4</width></LineStyle>
    </Style>
    <Style id="shulPin">
      <IconStyle>
        <color>ff2563eb</color><scale>1.2</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/paddle/blu-stars.png</href></Icon>
      </IconStyle>
    </Style>
    <Style id="spotPin">
      <IconStyle>
        <color>ff22c55e</color><scale>1.2</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/paddle/grn-circle.png</href></Icon>
      </IconStyle>
    </Style>
    <Style id="hitPin">
      <IconStyle>
        <color>ff4444ef</color><scale>1.1</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-diamond.png</href></Icon>
      </IconStyle>
    </Style>
    <Style id="moonPin">
      <IconStyle>
        <color>ff93c5fd</color><scale>1.3</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/shapes/star.png</href></Icon>
      </IconStyle>
    </Style>

    <Folder>
      <name>1. Eye-Level Cameras (Double-Click to Fly In)</name>
      <open>1</open>

      <Placemark>
        <name>Eye-Level View: Recommended Spot (CLEAR +{spot_trace['clearance_deg']:.1f}°)</name>
        <description>Camera at 5.5 ft eye level on {xml_escape(spot['name'])}, aimed at Azimuth {az:.1f}°, Altitude {alt:.1f}°.</description>
        <Camera>
          <longitude>{spot_lon:.7f}</longitude>
          <latitude>{spot_lat:.7f}</latitude>
          <altitude>{eye_m:.2f}</altitude>
          <heading>{az:.2f}</heading>
          <tilt>{cam_tilt:.2f}</tilt>
          <roll>0</roll>
          <altitudeMode>relativeToGround</altitudeMode>
        </Camera>
        <styleUrl>#spotPin</styleUrl>
        <Point>
          <altitudeMode>relativeToGround</altitudeMode>
          <coordinates>{spot_lon:.7f},{spot_lat:.7f},{eye_m:.2f}</coordinates>
        </Point>
      </Placemark>

      <Placemark>
        <name>Eye-Level View: Outside Shul (BLOCKED {shul_trace['clearance_deg']:.1f}°)</name>
        <description>Camera at 5.5 ft eye level right outside 210 W 91st St, aimed at Azimuth {az:.1f}°, Altitude {alt:.1f}°.</description>
        <Camera>
          <longitude>{shul_lon:.7f}</longitude>
          <latitude>{shul_lat:.7f}</latitude>
          <altitude>{eye_m:.2f}</altitude>
          <heading>{az:.2f}</heading>
          <tilt>{cam_tilt:.2f}</tilt>
          <roll>0</roll>
          <altitudeMode>relativeToGround</altitudeMode>
        </Camera>
        <styleUrl>#shulPin</styleUrl>
        <Point>
          <altitudeMode>relativeToGround</altitudeMode>
          <coordinates>{shul_lon:.7f},{shul_lat:.7f},{eye_m:.2f}</coordinates>
        </Point>
      </Placemark>

      <Placemark>
        <name>3D Neighborhood Overview</name>
        <LookAt>
          <longitude>{spot_lon:.7f}</longitude>
          <latitude>{spot_lat:.7f}</latitude>
          <altitude>60</altitude>
          <heading>55</heading>
          <tilt>62</tilt>
          <range>420</range>
          <altitudeMode>relativeToGround</altitudeMode>
        </LookAt>
        <Point>
          <coordinates>{shul_lon:.7f},{shul_lat:.7f},0</coordinates>
        </Point>
      </Placemark>
    </Folder>

    <Folder>
      <name>2. 3D Moon Sightline Rays</name>
      <open>1</open>

      <Placemark>
        <name>CLEAR Sightline from Recommended Spot (+{spot_trace['clearance_deg']:.1f}°)</name>
        <description>3D ray from {xml_escape(spot['name'])} (ground {spot['ground_ft']:.0f} ft + 5.5 ft eye) at Az {az:.1f}°, Alt {alt:.1f}°.</description>
        <styleUrl>#greenRay</styleUrl>
        <LineString>
          <tessellate>0</tessellate>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>{spot_ray_coords}</coordinates>
        </LineString>
      </Placemark>

      <Placemark>
        <name>Clear Sightline Vertical Curtain (toggle on/off)</name>
        <visibility>0</visibility>
        <styleUrl>#greenCurtain</styleUrl>
        <LineString>
          <extrude>1</extrude>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>{spot_ray_coords}</coordinates>
        </LineString>
      </Placemark>

      <Placemark>
        <name>BLOCKED Sightline from Outside Shul ({shul_trace['clearance_deg']:.1f}°)</name>
        <description>3D ray from 210 W 91st St sidewalk (ground {shul['ground_ft']:.0f} ft + 5.5 ft eye) at Az {az:.1f}°, Alt {alt:.1f}°.</description>
        <styleUrl>#redRay</styleUrl>
        <LineString>
          <tessellate>0</tessellate>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>{shul_ray_coords}</coordinates>
        </LineString>
      </Placemark>
      {hit_placemark}
    </Folder>

    <Folder>
      <name>3. Moon Target Marker</name>
      <Placemark>
        <name>Moon Direction ({night['moon_compass']} {az:.1f}°, Alt {alt:.1f}°)</name>
        <description>Point along the clear sightline 1,200 ft from the recommended spot at exact lunar altitude {alt:.1f}°.</description>
        <styleUrl>#moonPin</styleUrl>
        <Point>
          <altitudeMode>absolute</altitudeMode>
          <coordinates>{moon_lon:.7f},{moon_lat:.7f},{moon_z_m:.2f}</coordinates>
        </Point>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""
    with open(out_path, "w") as f:
        f.write(kml)
    print(f"Wrote KML: {out_path}")


def generate_html_verifier(
    vm: VisibilityModel,
    night: dict,
    shul: dict,
    spot: dict,
    timeline: list[dict],
    out_path: str,
):
    # Collect buildings within 1,100 ft of the shul or spot
    buildings_payload = []
    idx_map = {}
    for idx, b in enumerate(vm.buildings):
        cx = 0.5 * (b.bbox[0] + b.bbox[2])
        cy = 0.5 * (b.bbox[1] + b.bbox[3])
        if math.hypot(cx - spot["x"], cy - spot["y"]) > 1050 and math.hypot(cx - shul["x"], cy - shul["y"]) > 1050:
            continue
        ring = b.rings[0]
        pts = [[round(p[0], 1), round(p[1], 1)] for p in ring]
        new_id = len(buildings_payload)
        idx_map[idx] = new_id
        buildings_payload.append({
            "id": new_id,
            "orig_idx": idx,
            "pts": pts,
            "g": round(b.ground_ft, 1),
            "h": round(b.height_ft, 1),
            "top": round(b.top_ft, 1),
            "cx": round(cx, 1),
            "cy": round(cy, 1),
        })

    # Collect nearby street centerlines for visual orientation
    streets_payload = []
    for st in vm.streets:
        pts = st["points"]
        if any(math.hypot(p[0] - spot["x"], p[1] - spot["y"]) < 1050 for p in pts):
            streets_payload.append({
                "name": st["name"],
                "pts": [[round(p[0], 1), round(p[1], 1)] for p in pts],
            })

    def remap_trace(tr: dict) -> dict:
        out = dict(tr)
        out["blocking_id"] = idx_map.get(tr["blocking_b_idx"])
        out["limiting_id"] = idx_map.get(tr["limiting_b_idx"])
        return out

    frames_payload = []
    for fr in timeline:
        frames_payload.append({
            "offset_min": fr["offset_min"],
            "time_str": fr["time_str"],
            "az": fr["az"],
            "alt": fr["alt"],
            "compass": fr["compass"],
            "shul_trace": remap_trace(fr["shul_trace"]),
            "spot_trace": remap_trace(fr["spot_trace"]),
        })

    payload = {
        "night": night,
        "shul": shul,
        "spot": spot,
        "frames": frames_payload,
        "buildings": buildings_payload,
        "streets": streets_payload,
    }

    t0 = frames_payload[0]
    t_end = frames_payload[-1]
    data_json = json.dumps(payload, separators=(",", ":"))
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>3D Projection Verifier — {night['civil_date']} ({night['heb_date_str']})</title>
<style>
  :root {{
    --bg: #0b1120;
    --panel: #111827;
    --border: #1e293b;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --green: #22c55e;
    --red: #ef4444;
    --amber: #f59e0b;
    --blue: #38bdf8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 9px 18px;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    gap: 14px;
    flex-wrap: wrap;
  }}
  .title-block h1 {{
    margin: 0;
    font-size: 15.5px;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}
  .title-block .sub {{
    font-size: 12px;
    color: var(--muted);
    margin-top: 2px;
  }}
  .stats {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .pill {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .pill strong {{ font-weight: 700; }}
  .pill.clear {{ border-color: rgba(34,197,94,0.45); background: rgba(34,197,94,0.12); color: #86efac; }}
  .pill.blocked {{ border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.12); color: #fca5a5; }}
  .timebar {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 18px;
    background: #0f172a;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .timebar-label {{
    font-size: 12px;
    font-weight: 700;
    color: #e2e8f0;
    min-width: 155px;
  }}
  .timebar-label span {{
    color: var(--blue);
    font-variant-numeric: tabular-nums;
  }}
  .slider-wrap {{
    flex: 1;
    min-width: 200px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  input[type="range"] {{
    width: 100%;
    accent-color: #38bdf8;
    cursor: pointer;
    margin: 0;
  }}
  .slider-ticks {{
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .moon-readout {{
    font-size: 12px;
    color: #cbd5e1;
    font-variant-numeric: tabular-nums;
    min-width: 210px;
    text-align: right;
  }}
  .main {{
    flex: 1;
    display: grid;
    grid-template-columns: 1.35fr 1fr;
    grid-template-rows: 1fr 235px;
    gap: 10px;
    padding: 10px;
    min-height: 0;
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
    padding: 7px 12px;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    font-weight: 600;
    background: rgba(15, 23, 42, 0.7);
    gap: 8px;
  }}
  .card-hdr .hint {{ font-weight: 400; color: var(--muted); font-size: 11px; }}
  .btn-group {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  button {{
    background: #1e293b;
    color: var(--text);
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
  }}
  button:hover {{ background: #334155; }}
  button.active {{
    background: #2563eb;
    border-color: #3b82f6;
    color: #fff;
  }}
  button.active-green {{
    background: #15803d;
    border-color: #22c55e;
    color: #fff;
  }}
  button.active-red {{
    background: #b91c1c;
    border-color: #ef4444;
    color: #fff;
  }}
  .canvas-wrap {{
    flex: 1;
    position: relative;
    min-height: 0;
  }}
  canvas {{
    width: 100%;
    height: 100%;
    display: block;
  }}
  .legend {{
    position: absolute;
    bottom: 10px;
    left: 10px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 11px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    pointer-events: none;
  }}
  .leg-row {{ display: flex; align-items: center; gap: 7px; }}
  .swatch {{ width: 12px; height: 10px; border-radius: 2px; display: inline-block; }}
  .profile-card {{
    grid-column: 1 / -1;
  }}
</style>
</head>
<body>
<header>
  <div class="title-block">
    <h1>3D Moon Sightline Verifier &mdash; {night['day_of_week']}, Nov 21, 2026 ({night['heb_date_str']} 5787)</h1>
    <div class="sub">Young Israel of the West Side (210 W 91st St) &bull; Tzeis {t0['time_str']} &bull; {night['moon_illum_pct']:.0f}% illuminated</div>
  </div>
  <div class="stats">
    <div id="pillSpot" class="pill clear"></div>
    <div id="pillShul" class="pill blocked"></div>
  </div>
</header>

<div class="timebar">
  <button id="btnPlay">&#9654; Play</button>
  <div class="timebar-label">Time: <span id="lblTime">{t0['time_str']} (+0 min)</span></div>
  <div class="slider-wrap">
    <input id="timeSlider" type="range" min="0" max="{len(frames_payload) - 1}" step="1" value="0" />
    <div class="slider-ticks">
      <span>Tzeis ({t0['time_str']})</span>
      <span>+10m</span>
      <span>+20m</span>
      <span>+30m ({t_end['time_str']})</span>
    </div>
  </div>
  <div id="lblMoon" class="moon-readout"></div>
</div>

<div class="main">
  <!-- 1. 3D Orbit View -->
  <div class="card">
    <div class="card-hdr">
      <div>3D NYC Building Model <span class="hint">&bull; Drag to orbit, scroll to zoom</span></div>
      <div class="btn-group">
        <button id="btnCamIso" class="active">3D Overview</button>
        <button id="btnCamSpot">Behind Spot</button>
        <button id="btnCamShul">Behind Shul</button>
        <button id="btnCamTop">Top-Down</button>
      </div>
    </div>
    <div class="canvas-wrap">
      <canvas id="c3d"></canvas>
      <div class="legend">
        <div class="leg-row"><span class="swatch" style="background:#22c55e"></span> <span id="legSpot">Recommended Spot Ray</span></div>
        <div class="leg-row"><span class="swatch" style="background:#ef4444"></span> <span id="legShul">Outside Shul Ray</span></div>
        <div class="leg-row"><span class="swatch" style="background:#dc2626"></span> Building Blocking Ray</div>
        <div class="leg-row"><span class="swatch" style="background:#f59e0b"></span> Closest-Clearance Building</div>
      </div>
    </div>
  </div>

  <!-- 2. First-Person Eye-Level View -->
  <div class="card">
    <div class="card-hdr">
      <div>First-Person Eye-Level View (5.5 ft) <span class="hint">&bull; Dotted line = 30-min Moon path</span></div>
      <div class="btn-group">
        <button id="btnFpSpot" class="active-green">Recommended Spot</button>
        <button id="btnFpShul">Outside Shul</button>
      </div>
    </div>
    <div class="canvas-wrap">
      <canvas id="cFp"></canvas>
    </div>
  </div>

  <!-- 3. 2D Elevation Cross-Section -->
  <div class="card profile-card">
    <div class="card-hdr">
      <div id="profTitle">2D Elevation Cross-Section <span class="hint">&bull; Dashed cap = +4 ft parapet buffer</span></div>
      <div class="btn-group">
        <button id="btnProfSpot" class="active-green">Recommended Spot</button>
        <button id="btnProfShul">Outside Shul</button>
      </div>
    </div>
    <div class="canvas-wrap">
      <canvas id="cProf"></canvas>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};
const DEG = Math.PI / 180;

let frameIdx = 0;
let activeView = "spot"; // "spot" or "shul" for FP and Profile
let playTimer = null;

// Lock First-Person center azimuth to midpoint of 30-min window so skyline stays steady as Moon moves
const FP_CENTER_AZ = DATA.frames[Math.floor(DATA.frames.length / 2)].az;

function curFrame() {{ return DATA.frames[frameIdx]; }}

// ---------------- 1. 3D ORBIT RENDERER ----------------
const c3d = document.getElementById("c3d");
const f0 = DATA.frames[0];
const f0dx = Math.sin(f0.az * DEG), f0dy = Math.cos(f0.az * DEG);

let cam = {{
  targetX: (DATA.shul.x + DATA.spot.x) * 0.5 + f0dx * 140,
  targetY: (DATA.shul.y + DATA.spot.y) * 0.5 + f0dy * 140,
  targetZ: 120,
  yaw: -145 * DEG,
  pitch: 34 * DEG,
  dist: 1050,
  fov: 52 * DEG,
}};

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
  const rx = x - camPos.x;
  const ry = y - camPos.y;
  const rz = z - camPos.z;
  const cx = rx * basis.rx + ry * basis.ry + rz * basis.rz;
  const cy = rx * basis.ux + ry * basis.uy + rz * basis.uz;
  const cz = rx * basis.fx + ry * basis.fy + rz * basis.fz;
  if (cz <= 5) return null;
  return {{
    sx: w * 0.5 + (cx / cz) * f,
    sy: h * 0.5 - (cy / cz) * f,
    cz,
  }};
}}

function makeCameraBasis(camPos, targetX, targetY, targetZ) {{
  let fx = targetX - camPos.x, fy = targetY - camPos.y, fz = targetZ - camPos.z;
  const fl = Math.hypot(fx, fy, fz) || 1;
  fx /= fl; fy /= fl; fz /= fl;
  let rx = fy, ry = -fx, rz = 0;
  let rl = Math.hypot(rx, ry, rz);
  if (rl < 1e-4) {{ rx = 1; ry = 0; rz = 0; rl = 1; }}
  rx /= rl; ry /= rl; rz /= rl;
  const ux = ry * fz - rz * fy;
  const uy = rz * fx - rx * fz;
  const uz = rx * fy - ry * fx;
  return {{ fx, fy, fz, rx, ry, rz, ux, uy, uz }};
}}

function draw3D() {{
  const {{ w, h, ctx }} = resizeCanvas(c3d);
  const fr = curFrame();
  const rayDx = Math.sin(fr.az * DEG);
  const rayDy = Math.cos(fr.az * DEG);
  const tanAlt = Math.tan(fr.alt * DEG);

  ctx.fillStyle = "#0b1120";
  ctx.fillRect(0, 0, w, h);

  const camPos = {{
    x: cam.targetX - Math.cos(cam.pitch) * Math.sin(cam.yaw) * cam.dist,
    y: cam.targetY - Math.cos(cam.pitch) * Math.cos(cam.yaw) * cam.dist,
    z: cam.targetZ + Math.sin(cam.pitch) * cam.dist,
  }};
  const basis = makeCameraBasis(camPos, cam.targetX, cam.targetY, cam.targetZ);
  const f = (h * 0.5) / Math.tan(cam.fov * 0.5);

  ctx.strokeStyle = "rgba(148, 163, 184, 0.28)";
  ctx.lineWidth = 1.5;
  for (const st of DATA.streets) {{
    ctx.beginPath();
    let started = false;
    for (const pt of st.pts) {{
      const p = project3D(pt[0], pt[1], 92, w, h, camPos, basis, f);
      if (!p) {{ started = false; continue; }}
      if (!started) {{ ctx.moveTo(p.sx, p.sy); started = true; }}
      else ctx.lineTo(p.sx, p.sy);
    }}
    ctx.stroke();
  }}

  const blockId = fr.shul_trace.blocking_id;
  const limitId = fr.spot_trace.limiting_id;

  const sortedB = DATA.buildings.map(b => {{
    const d2 = (b.cx - camPos.x) ** 2 + (b.cy - camPos.y) ** 2 + ((b.g + b.h * 0.5) - camPos.z) ** 2;
    return {{ b, d2 }};
  }}).sort((a, b) => b.d2 - a.d2);

  for (const {{ b }} of sortedB) {{
    const pts = b.pts;
    if (pts.length < 3) continue;
    const isBlock = (b.id === blockId && !fr.shul_trace.is_clear);
    const isLimit = (b.id === limitId && !isBlock);

    const botProj = [];
    const topProj = [];
    let anyVis = false;
    for (let i = 0; i < pts.length; i++) {{
      const pb = project3D(pts[i][0], pts[i][1], b.g, w, h, camPos, basis, f);
      const pt = project3D(pts[i][0], pts[i][1], b.top, w, h, camPos, basis, f);
      botProj.push(pb);
      topProj.push(pt);
      if (pb || pt) anyVis = true;
    }}
    if (!anyVis) continue;

    const hNorm = Math.min(1, b.h / 260);
    let wallFill, roofFill, strokeCol;
    if (isBlock) {{
      wallFill = "rgba(220, 38, 38, 0.85)";
      roofFill = "rgba(248, 113, 113, 0.92)";
      strokeCol = "#fecaca";
    }} else if (isLimit) {{
      wallFill = "rgba(217, 119, 6, 0.82)";
      roofFill = "rgba(251, 191, 36, 0.9)";
      strokeCol = "#fef08a";
    }} else {{
      const r = Math.round(35 + hNorm * 35);
      const g = Math.round(48 + hNorm * 45);
      const bl = Math.round(72 + hNorm * 65);
      wallFill = `rgba(${{r}},${{g}},${{bl}},0.82)`;
      roofFill = `rgba(${{r+25}},${{g+28}},${{bl+35}},0.90)`;
      strokeCol = "rgba(148, 163, 184, 0.25)";
    }}

    const walls = [];
    for (let i = 0; i < pts.length - 1; i++) {{
      const b0 = botProj[i], b1 = botProj[i + 1];
      const t0 = topProj[i], t1 = topProj[i + 1];
      if (!b0 || !b1 || !t0 || !t1) continue;
      const avgZ = (b0.cz + b1.cz + t0.cz + t1.cz) * 0.25;
      walls.push({{ b0, b1, t0, t1, avgZ }});
    }}
    walls.sort((a, b) => b.avgZ - a.avgZ);

    ctx.lineWidth = isBlock || isLimit ? 1.2 : 0.6;
    ctx.strokeStyle = strokeCol;
    ctx.fillStyle = wallFill;
    for (const wl of walls) {{
      ctx.beginPath();
      ctx.moveTo(wl.b0.sx, wl.b0.sy);
      ctx.lineTo(wl.b1.sx, wl.b1.sy);
      ctx.lineTo(wl.t1.sx, wl.t1.sy);
      ctx.lineTo(wl.t0.sx, wl.t0.sy);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }}

    if (topProj.every(p => p !== null)) {{
      ctx.fillStyle = roofFill;
      ctx.beginPath();
      ctx.moveTo(topProj[0].sx, topProj[0].sy);
      for (let i = 1; i < topProj.length; i++) ctx.lineTo(topProj[i].sx, topProj[i].sy);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }}
  }}

  function drawRay3D(ox, oy, oz, len, color, width, dashed=false) {{
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    if (dashed) ctx.setLineDash([6, 4]);
    ctx.beginPath();
    let started = false;
    const steps = 30;
    for (let i = 0; i <= steps; i++) {{
      const t = len * i / steps;
      const p = project3D(ox + rayDx * t, oy + rayDy * t, oz + t * tanAlt, w, h, camPos, basis, f);
      if (!p) {{ started = false; continue; }}
      if (!started) {{ ctx.moveTo(p.sx, p.sy); started = true; }}
      else ctx.lineTo(p.sx, p.sy);
    }}
    ctx.stroke();
    ctx.restore();
  }}

  // Shul ray (red if blocked, cyan-green if it becomes clear!)
  const fb = fr.shul_trace.first_block;
  if (fb) {{
    drawRay3D(DATA.shul.x, DATA.shul.y, fr.shul_trace.oz, fb.t_enter, "#ef4444", 3.2, false);
    drawRay3D(
      DATA.shul.x + rayDx * fb.t_enter,
      DATA.shul.y + rayDy * fb.t_enter,
      fr.shul_trace.oz + fb.t_enter * tanAlt,
      850 - fb.t_enter,
      "rgba(239, 68, 68, 0.45)", 2.0, true
    );
    const hitP = project3D(
      DATA.shul.x + rayDx * fb.t_enter,
      DATA.shul.y + rayDy * fb.t_enter,
      fr.shul_trace.oz + fb.t_enter * tanAlt,
      w, h, camPos, basis, f
    );
    if (hitP) {{
      ctx.fillStyle = "#fef08a";
      ctx.strokeStyle = "#dc2626";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(hitP.sx, hitP.sy, 5.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }}
  }} else {{
    drawRay3D(DATA.shul.x, DATA.shul.y, fr.shul_trace.oz, 850, fr.shul_trace.is_clear ? "#38bdf8" : "#f59e0b", 3.2, false);
  }}

  // Recommended spot ray
  drawRay3D(DATA.spot.x, DATA.spot.y, fr.spot_trace.oz, 950, fr.spot_trace.is_clear ? "#22c55e" : "#ef4444", 3.8, false);

  // Moon icon at end of clear ray
  const moonP = project3D(
    DATA.spot.x + rayDx * 950,
    DATA.spot.y + rayDy * 950,
    fr.spot_trace.oz + 950 * tanAlt,
    w, h, camPos, basis, f
  );
  if (moonP) {{
    ctx.fillStyle = "#fef08a";
    ctx.shadowColor = "#fde047";
    ctx.shadowBlur = 14;
    ctx.beginPath();
    ctx.arc(moonP.sx, moonP.sy, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }}

  function drawPin(x, y, z, label, col, labelDy=-10) {{
    const p = project3D(x, y, z, w, h, camPos, basis, f);
    if (!p) return;
    ctx.fillStyle = col;
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(p.sx, p.sy, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.font = "700 11px -apple-system, sans-serif";
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = "rgba(15, 23, 42, 0.88)";
    ctx.fillRect(p.sx + 9, p.sy + labelDy, tw + 10, 18);
    ctx.fillStyle = "#f8fafc";
    ctx.fillText(label, p.sx + 14, p.sy + labelDy + 13);
  }}
  drawPin(DATA.shul.x, DATA.shul.y, fr.shul_trace.oz, "210 W 91st (Shul)", "#3b82f6", 10);
  drawPin(DATA.spot.x, DATA.spot.y, fr.spot_trace.oz, "Recommended Spot", "#22c55e", -22);
}}

// Mouse orbit controls
let dragging = false, lastX = 0, lastY = 0;
c3d.addEventListener("mousedown", e => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; }});
window.addEventListener("mouseup", () => {{ dragging = false; }});
window.addEventListener("mousemove", e => {{
  if (!dragging) return;
  const dx = e.clientX - lastX, dy = e.clientY - lastY;
  lastX = e.clientX; lastY = e.clientY;
  cam.yaw += dx * 0.008;
  cam.pitch = Math.max(5 * DEG, Math.min(86 * DEG, cam.pitch + dy * 0.008));
  draw3D();
}});
c3d.addEventListener("wheel", e => {{
  e.preventDefault();
  cam.dist = Math.max(250, Math.min(2400, cam.dist * (1 + e.deltaY * 0.001)));
  draw3D();
}}, {{ passive: false }});

function setPreset(name) {{
  const fr = curFrame();
  const rdx = Math.sin(fr.az * DEG), rdy = Math.cos(fr.az * DEG);
  for (const id of ["btnCamIso", "btnCamSpot", "btnCamShul", "btnCamTop"]) {{
    document.getElementById(id).classList.remove("active");
  }}
  if (name === "iso") {{
    document.getElementById("btnCamIso").classList.add("active");
    cam.targetX = (DATA.shul.x + DATA.spot.x) * 0.5 + rdx * 140;
    cam.targetY = (DATA.shul.y + DATA.spot.y) * 0.5 + rdy * 140;
    cam.targetZ = 120; cam.yaw = -145 * DEG; cam.pitch = 34 * DEG; cam.dist = 1050;
  }} else if (name === "spot") {{
    document.getElementById("btnCamSpot").classList.add("active");
    cam.targetX = DATA.spot.x + rdx * 220;
    cam.targetY = DATA.spot.y + rdy * 220;
    cam.targetZ = 160; cam.yaw = (fr.az - 180) * DEG; cam.pitch = 16 * DEG; cam.dist = 460;
  }} else if (name === "shul") {{
    document.getElementById("btnCamShul").classList.add("active");
    cam.targetX = DATA.shul.x + rdx * 180;
    cam.targetY = DATA.shul.y + rdy * 180;
    cam.targetZ = 150; cam.yaw = (fr.az - 180) * DEG; cam.pitch = 16 * DEG; cam.dist = 420;
  }} else if (name === "top") {{
    document.getElementById("btnCamTop").classList.add("active");
    cam.targetX = (DATA.shul.x + DATA.spot.x) * 0.5 + rdx * 140;
    cam.targetY = (DATA.shul.y + DATA.spot.y) * 0.5 + rdy * 140;
    cam.targetZ = 100; cam.yaw = 0; cam.pitch = 85 * DEG; cam.dist = 1250;
  }}
  draw3D();
}}
document.getElementById("btnCamIso").onclick = () => setPreset("iso");
document.getElementById("btnCamSpot").onclick = () => setPreset("spot");
document.getElementById("btnCamShul").onclick = () => setPreset("shul");
document.getElementById("btnCamTop").onclick = () => setPreset("top");

// ---------------- 2. FIRST-PERSON EYE-LEVEL VIEW ----------------
const cFp = document.getElementById("cFp");

function drawFirstPerson() {{
  const {{ w, h, ctx }} = resizeCanvas(cFp);
  const fr = curFrame();
  const tr = activeView === "spot" ? fr.spot_trace : fr.shul_trace;
  const ox = tr.ox, oy = tr.oy, oz = tr.oz;

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, "#020617");
  grad.addColorStop(0.55, "#0f172a");
  grad.addColorStop(1, "#1e293b");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  const azSpan = 90;
  const altMin = -4, altMax = 52;
  const toX = azDeg => {{
    let d = azDeg - FP_CENTER_AZ;
    while (d > 180) d -= 360;
    while (d < -180) d += 360;
    return w * 0.5 + (d / azSpan) * w;
  }};
  const toY = altDeg => h - ((altDeg - altMin) / (altMax - altMin)) * h;

  // Elevation & Azimuth grid
  ctx.strokeStyle = "rgba(148, 163, 184, 0.16)";
  ctx.fillStyle = "#64748b";
  ctx.font = "10px -apple-system, sans-serif";
  ctx.lineWidth = 1;
  for (let a = 0; a <= 50; a += 10) {{
    const y = toY(a);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    ctx.fillText(a + "°", 6, y - 3);
  }}
  for (let da = -40; da <= 40; da += 10) {{
    const x = toX(FP_CENTER_AZ + da);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    if (da === 0) {{
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(`${{FP_CENTER_AZ.toFixed(1)}}°`, x + 4, 14);
      ctx.fillStyle = "#64748b";
    }}
  }}

  // Draw 30-min lunar trajectory arc BEHIND buildings
  ctx.save();
  ctx.strokeStyle = "rgba(253, 224, 71, 0.45)";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  DATA.frames.forEach((f, idx) => {{
    const px = toX(f.az), py = toY(f.alt);
    if (idx === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }});
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();

  // Draw Moon BEHIND buildings so buildings occlude it when blocked
  const mx = toX(fr.az), my = toY(fr.alt);
  ctx.save();
  ctx.fillStyle = "#fef9c3";
  ctx.shadowColor = "#fde047";
  ctx.shadowBlur = 18;
  ctx.beginPath();
  ctx.arc(mx, my, 10, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  const blockId = tr.blocking_id;
  const limitId = tr.limiting_id;

  const sortedB = DATA.buildings.map(b => {{
    const d2 = (b.cx - ox) ** 2 + (b.cy - oy) ** 2;
    return {{ b, d2 }};
  }}).sort((a, b) => b.d2 - a.d2);

  for (const {{ b, d2 }} of sortedB) {{
    if (d2 > 1400 * 1400) continue;
    const pts = b.pts;
    const isBlock = (!tr.is_clear && b.id === blockId);
    const isLimit = (tr.is_clear && b.id === limitId);
    const dist = Math.sqrt(d2);
    const shade = Math.max(0.25, 1 - dist / 1400);

    for (let i = 0; i < pts.length - 1; i++) {{
      const x1 = pts[i][0] - ox, y1 = pts[i][1] - oy;
      const x2 = pts[i + 1][0] - ox, y2 = pts[i + 1][1] - oy;
      const d1 = Math.hypot(x1, y1), d2e = Math.hypot(x2, y2);
      if (d1 < 5 || d2e < 5) continue;

      let az1 = Math.atan2(x1, y1) / DEG; if (az1 < 0) az1 += 360;
      let az2 = Math.atan2(x2, y2) / DEG; if (az2 < 0) az2 += 360;
      let da1 = az1 - FP_CENTER_AZ; while (da1 > 180) da1 -= 360; while (da1 < -180) da1 += 360;
      let da2 = az2 - FP_CENTER_AZ; while (da2 > 180) da2 -= 360; while (da2 < -180) da2 += 360;
      if (Math.abs(da1) > 65 && Math.abs(da2) > 65) continue;
      if (Math.abs(da1 - da2) > 120) continue;

      const top1 = Math.atan2(b.top - oz, d1) / DEG;
      const top2 = Math.atan2(b.top - oz, d2e) / DEG;
      const bot1 = Math.atan2(b.g - oz, d1) / DEG;
      const bot2 = Math.atan2(b.g - oz, d2e) / DEG;

      ctx.beginPath();
      ctx.moveTo(toX(az1), toY(bot1));
      ctx.lineTo(toX(az2), toY(bot2));
      ctx.lineTo(toX(az2), toY(top2));
      ctx.lineTo(toX(az1), toY(top1));
      ctx.closePath();

      if (isBlock) {{
        ctx.fillStyle = "rgba(220, 38, 38, 0.90)";
        ctx.strokeStyle = "#fca5a5";
      }} else if (isLimit) {{
        ctx.fillStyle = "rgba(217, 119, 6, 0.88)";
        ctx.strokeStyle = "#fde047";
      }} else {{
        const c = Math.round(28 + shade * 42);
        ctx.fillStyle = `rgba(${{c}},${{c + 10}},${{c + 26}},0.94)`;
        ctx.strokeStyle = "rgba(148, 163, 184, 0.25)";
      }}
      ctx.lineWidth = isBlock || isLimit ? 1.2 : 0.7;
      ctx.fill();
      ctx.stroke();
    }}
  }}

  // Overlay subtle Moon crosshair & trajectory dots so user can see where Moon is even behind a building
  ctx.strokeStyle = tr.is_clear ? "#22c55e" : "#ef4444";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.arc(mx, my, 15, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);

  // Label t+0 and t+30 on path
  ctx.font = "600 10px -apple-system, sans-serif";
  ctx.fillStyle = "#fde047";
  const fStart = DATA.frames[0], fEnd = DATA.frames[DATA.frames.length - 1];
  ctx.fillText(fStart.time_str, toX(fStart.az) - 48, toY(fStart.alt) + 12);
  ctx.fillText(fEnd.time_str, toX(fEnd.az) + 10, toY(fEnd.alt) - 6);

  const badgeText = tr.is_clear
    ? `CLEAR: Moon +${{tr.clearance_deg.toFixed(1)}}° above skyline`
    : (tr.clearance_deg >= 0
      ? `TIGHT: +${{tr.clearance_deg.toFixed(1)}}° (< 1.5° margin)`
      : `BLOCKED: Building rises ${{Math.abs(tr.clearance_deg).toFixed(1)}}° above Moon`);
  ctx.font = "700 12px -apple-system, sans-serif";
  const bw = ctx.measureText(badgeText).width + 18;
  ctx.fillStyle = tr.is_clear ? "rgba(21, 128, 61, 0.92)" : "rgba(185, 28, 28, 0.92)";
  ctx.fillRect(w - bw - 10, 10, bw, 24);
  ctx.fillStyle = "#fff";
  ctx.fillText(badgeText, w - bw - 1, 26);
}}

// ---------------- 3. 2D ELEVATION CROSS-SECTION ----------------
const cProf = document.getElementById("cProf");

function drawProfile() {{
  const {{ w, h, ctx }} = resizeCanvas(cProf);
  const fr = curFrame();
  const tr = activeView === "spot" ? fr.spot_trace : fr.shul_trace;
  const tanAlt = Math.tan(fr.alt * DEG);

  ctx.fillStyle = "#0b1120";
  ctx.fillRect(0, 0, w, h);

  const padL = 52, padR = 24, padT = 18, padB = 30;
  const pw = w - padL - padR;
  const ph = h - padT - padB;

  const maxDist = 1000;
  const minElev = 50;
  const maxElev = Math.max(460, tr.oz + maxDist * tanAlt * 0.65);

  const xOf = d => padL + (d / maxDist) * pw;
  const yOf = z => padT + ph - ((z - minElev) / (maxElev - minElev)) * ph;

  ctx.strokeStyle = "rgba(148, 163, 184, 0.14)";
  ctx.fillStyle = "#94a3b8";
  ctx.font = "10px -apple-system, sans-serif";
  ctx.lineWidth = 1;
  for (let d = 0; d <= maxDist; d += 100) {{
    const x = xOf(d);
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ph); ctx.stroke();
    ctx.fillText(d + " ft", x - 12, h - 10);
  }}
  for (let z = 100; z <= maxElev; z += 100) {{
    const y = yOf(z);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillText(z + " ft", 8, y + 3);
  }}

  ctx.strokeStyle = "#475569";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(tr.ground_ft));
  ctx.lineTo(xOf(maxDist), yOf(tr.ground_ft));
  ctx.stroke();

  for (const s of tr.slices) {{
    if (s.t_enter > maxDist) continue;
    const x1 = xOf(s.t_enter);
    const x2 = xOf(Math.min(maxDist, s.t_exit));
    const bw = Math.max(4, x2 - x1);
    const yGround = yOf(s.ground_ft);
    const yRoof = yOf(s.roof_ft);
    const yTop = yOf(s.top_ft);

    const isBlock = s.blocks;
    const isLimit = (s.b_idx === tr.limiting_b_idx);

    ctx.fillStyle = isBlock
      ? "rgba(220, 38, 38, 0.78)"
      : (isLimit ? "rgba(217, 119, 6, 0.75)" : "rgba(71, 85, 105, 0.75)");
    ctx.fillRect(x1, yRoof, bw, yGround - yRoof);
    ctx.strokeStyle = isBlock ? "#fca5a5" : (isLimit ? "#fde047" : "#94a3b8");
    ctx.lineWidth = 1;
    ctx.strokeRect(x1, yRoof, bw, yGround - yRoof);

    ctx.strokeStyle = "#e2e8f0";
    ctx.setLineDash([3, 2]);
    ctx.beginPath();
    ctx.moveTo(x1, yTop); ctx.lineTo(x1 + bw, yTop);
    ctx.stroke();
    ctx.setLineDash([]);

    if (isBlock || isLimit || s.height_ft >= 120) {{
      ctx.fillStyle = isBlock ? "#fca5a5" : (isLimit ? "#fde047" : "#cbd5e1");
      ctx.font = "600 10px -apple-system, sans-serif";
      ctx.fillText(`${{Math.round(s.height_ft)}} ft (${{s.obs_angle_deg.toFixed(1)}}°)`, x1, yTop - 4);
    }}
  }}

  const rayEndD = Math.min(maxDist, (maxElev - tr.oz) / tanAlt);
  ctx.strokeStyle = tr.is_clear ? "#22c55e" : "#ef4444";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(tr.oz));
  ctx.lineTo(xOf(rayEndD), yOf(tr.oz + rayEndD * tanAlt));
  ctx.stroke();

  ctx.fillStyle = "#38bdf8";
  ctx.beginPath();
  ctx.arc(xOf(0), yOf(tr.oz), 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "700 11px -apple-system, sans-serif";
  ctx.fillText(`Observer (eye ${{tr.oz.toFixed(0)}} ft) → Ray ${{fr.alt.toFixed(1)}}°`, xOf(0) + 10, yOf(tr.oz) - 8);
}}

function updateUI() {{
  const fr = curFrame();
  const sClr = fr.spot_trace.clearance_deg;
  const shClr = fr.shul_trace.clearance_deg;

  document.getElementById("lblTime").textContent = `${{fr.time_str}} (+${{fr.offset_min}} min)`;
  document.getElementById("lblMoon").innerHTML = `Moon: <strong>${{fr.compass}} (${{fr.az.toFixed(1)}}°)</strong> &bull; Alt <strong>${{fr.alt.toFixed(1)}}°</strong>`;

  const pillSpot = document.getElementById("pillSpot");
  pillSpot.className = "pill " + (fr.spot_trace.is_clear ? "clear" : "blocked");
  pillSpot.innerHTML = `<span>Recommended Spot:</span> <strong>${{DATA.spot.short_name}}</strong> (<strong>${{sClr >= 0 ? "+" : ""}}${{sClr.toFixed(1)}}°</strong>)`;

  const pillShul = document.getElementById("pillShul");
  pillShul.className = "pill " + (fr.shul_trace.is_clear ? "clear" : "blocked");
  pillShul.innerHTML = `<span>Outside Shul:</span> <strong>${{fr.shul_trace.is_clear ? "Clear" : "Blocked"}} (${{shClr >= 0 ? "+" : ""}}${{shClr.toFixed(1)}}°)</strong>`;

  document.getElementById("legSpot").textContent = `Recommended Spot (${{sClr >= 0 ? "+" : ""}}${{sClr.toFixed(1)}}°)`;
  document.getElementById("legShul").textContent = `Outside Shul (${{shClr >= 0 ? "+" : ""}}${{shClr.toFixed(1)}}°)`;
  document.getElementById("profTitle").innerHTML = `2D Elevation Cross-Section Along Azimuth ${{fr.az.toFixed(1)}}° (${{fr.compass}}) <span class="hint">&bull; Dashed cap = +4 ft parapet buffer</span>`;
  document.getElementById("btnProfSpot").textContent = `Recommended Spot (${{sClr >= 0 ? "+" : ""}}${{sClr.toFixed(1)}}°)`;
  document.getElementById("btnProfShul").textContent = `Outside Shul (${{shClr >= 0 ? "+" : ""}}${{shClr.toFixed(1)}}°)`;

  document.getElementById("btnFpSpot").className = activeView === "spot" ? (fr.spot_trace.is_clear ? "active-green" : "active-red") : "";
  document.getElementById("btnFpShul").className = activeView === "shul" ? (fr.shul_trace.is_clear ? "active-green" : "active-red") : "";
  document.getElementById("btnProfSpot").className = activeView === "spot" ? (fr.spot_trace.is_clear ? "active-green" : "active-red") : "";
  document.getElementById("btnProfShul").className = activeView === "shul" ? (fr.shul_trace.is_clear ? "active-green" : "active-red") : "";
}}

function renderAll() {{
  updateUI();
  draw3D();
  drawFirstPerson();
  drawProfile();
}}

function setActiveView(mode) {{
  activeView = mode;
  renderAll();
}}

document.getElementById("btnFpSpot").onclick = () => setActiveView("spot");
document.getElementById("btnFpShul").onclick = () => setActiveView("shul");
document.getElementById("btnProfSpot").onclick = () => setActiveView("spot");
document.getElementById("btnProfShul").onclick = () => setActiveView("shul");

const slider = document.getElementById("timeSlider");
slider.addEventListener("input", e => {{
  frameIdx = parseInt(e.target.value, 10);
  renderAll();
}});

const btnPlay = document.getElementById("btnPlay");
btnPlay.onclick = () => {{
  if (playTimer) {{
    clearInterval(playTimer);
    playTimer = null;
    btnPlay.innerHTML = "&#9654; Play";
    btnPlay.classList.remove("active");
  }} else {{
    if (frameIdx >= DATA.frames.length - 1) frameIdx = 0;
    btnPlay.innerHTML = "&#9646;&#9646; Pause";
    btnPlay.classList.add("active");
    playTimer = setInterval(() => {{
      frameIdx = (frameIdx + 1) % DATA.frames.length;
      slider.value = frameIdx;
      renderAll();
    }}, 240);
  }}
}};

window.addEventListener("resize", renderAll);
renderAll();
</script>
</body>
</html>
"""
    with open(out_path, "w") as f:
        f.write(html_doc)
    print(f"Wrote HTML verifier: {out_path} ({len(buildings_payload)} buildings, {len(frames_payload)} time frames)")


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-21"
    with open(os.path.join(DATA_DIR, "levanah_5787.json")) as f:
        data = json.load(f)

    night = None
    for m in data["months"]:
        for n in m["nights"]:
            if n["civil_date"] == target_date:
                night = n
                break
    if not night:
        raise SystemExit(f"Date {target_date} not found in levanah_5787.json")

    vm = VisibilityModel()
    shul = vm.candidates[0]
    spot = night["nearest_spot"]
    shul_elev_m = shul["ground_ft"] / FT_PER_METER
    base_dt = datetime.datetime.fromisoformat(night["eval_time"])

    timeline = []
    for offset_min in range(0, 31):
        dt = base_dt + datetime.timedelta(minutes=offset_min)
        alt, az, _ = moon_alt_az(dt.astimezone(UTC), SHUL_LAT, SHUL_LON, shul_elev_m)
        alt_r = round(alt, 1)
        az_r = round(az, 1)
        shul_tr = trace_ray_profile(vm, shul["x"], shul["y"], shul["ground_ft"], az_r, alt_r)
        spot_tr = trace_ray_profile(vm, spot["x"], spot["y"], spot["ground_ft"], az_r, alt_r)
        timeline.append({
            "offset_min": offset_min,
            "time_str": dt.strftime("%-I:%M %p"),
            "az": az_r,
            "alt": alt_r,
            "compass": compass_direction(az_r),
            "shul_trace": shul_tr,
            "spot_trace": spot_tr,
        })

    t0 = timeline[0]
    t30 = timeline[-1]
    print(f"T+00m ({t0['time_str']}): Az {t0['az']}° Alt {t0['alt']}° | Spot {t0['spot_trace']['clearance_deg']}° | Shul {t0['shul_trace']['clearance_deg']}°")
    print(f"T+30m ({t30['time_str']}): Az {t30['az']}° Alt {t30['alt']}° | Spot {t30['spot_trace']['clearance_deg']}° | Shul {t30['shul_trace']['clearance_deg']}°")
    shul_clear_min = next((f for f in timeline if f["shul_trace"]["is_clear"]), None)
    if shul_clear_min:
        print(f"Outside Shul becomes CLEAR at +{shul_clear_min['offset_min']}m ({shul_clear_min['time_str']})")

    slug = "nov21" if target_date == "2026-11-21" else target_date.replace("-", "")
    html_path = os.path.join(OUT_DIR, f"verify_{slug}.html")
    kml_path = os.path.join(OUT_DIR, f"verify_{slug}.kml")

    generate_html_verifier(vm, night, shul, spot, timeline, html_path)
    generate_kml(night, shul, spot, t0["shul_trace"], t0["spot_trace"], kml_path)


if __name__ == "__main__":
    main()

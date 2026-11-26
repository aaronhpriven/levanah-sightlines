#!/usr/bin/env python3
"""
Generate 3 print-ready HTML/PDF layout options for Kiddush Levanah 5787 at 210 W 91st St:
  - Option A: 1 page/month (bulletin-board style) with real NYC SVG neighborhood map
  - Option B: 1 page/month large-print table-only with UWS street directions & compass arrows
  - Option C: Compact multi-month packet (2 months per page, ~7 pages for full year)
"""

from __future__ import annotations

import datetime
import html
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from visibility import VisibilityModel

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
OUT_DIR = os.path.join(ROOT_DIR, "output")
SAMPLE_DIR = os.path.join(OUT_DIR, "samples")
os.makedirs(SAMPLE_DIR, exist_ok=True)

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def fmt_time(iso_str: str) -> str:
    dt = datetime.datetime.fromisoformat(iso_str)
    return dt.strftime("%-I:%M %p")


def fmt_date_short(iso_date: str) -> str:
    d = datetime.date.fromisoformat(iso_date)
    return d.strftime("%b %-d")


def fmt_dt_banner(iso_str: str) -> str:
    dt = datetime.datetime.fromisoformat(iso_str)
    return dt.strftime("%a, %b %-d at %-I:%M %p")


def walk_time_str(ft: int) -> str:
    if ft <= 15:
        return "0 ft (outside)"
    if ft <= 60:
        return f"{ft} ft (across st)"
    mins = max(1, round(ft / 250.0))
    return f"{ft} ft (~{mins} min)"


def arrow_svg(az_deg: float, size: int = 16) -> str:
    """Small crisp compass arrow pointing in azimuth direction (0=up/N, 90=right/E)."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 20 20" style="vertical-align:-3px;margin-right:3px;">'
        f'<g transform="rotate({az_deg:.1f} 10 10)">'
        f'<line x1="10" y1="16" x2="10" y2="5" stroke="#1e3a5f" stroke-width="2" stroke-linecap="round"/>'
        f'<polygon points="10,2 6.5,8 13.5,8" fill="#1e3a5f"/>'
        f'</g></svg>'
    )


def render_neighborhood_svg(vm: VisibilityModel, month_data: dict, width: int = 720, height: int = 290) -> tuple[str, dict[str, str]]:
    """
    Render a crisp vector neighborhood map of the Upper West Side around 210 W 91st St
    rotated to Manhattan street grid (Uptown = Up, Hudson = Left, Central Park = Right)
    so it reads intuitively like a NYC map!
    Returns (svg_html, spot_key_to_letter).
    """
    # Collect unique spots used in this month's non-Shabbos/Yom-Tov nights
    spots_ordered: list[dict] = []
    seen_names: set[str] = set()
    for n in month_data["nights"]:
        if n.get("yom_tov_or_shabbos"):
            continue
        sp = n.get("nearest_spot")
        if sp and sp["short_name"] not in seen_names:
            seen_names.add(sp["short_name"])
            spots_ordered.append(sp)

    # Assign letters A, B, C... (Shul front gets 'S' or '★')
    spot_letters: dict[str, str] = {}
    letter_idx = 0
    for sp in spots_ordered:
        if sp["kind"] == "shul":
            spot_letters[sp["short_name"]] = "★"
        else:
            spot_letters[sp["short_name"]] = chr(ord("A") + letter_idx)
            letter_idx += 1

    # Rotate coordinates into Manhattan Grid space so Uptown is UP (+v) and East is RIGHT (+u)
    # Grid North (Uptown) = (sin 29°, cos 29°), Grid East = (cos 29°, -sin 29°)
    ang = math.radians(29.0)
    ca, sa = math.cos(ang), math.sin(ang)
    sx0, sy0 = vm.shul_sidewalk_xy

    def to_grid(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - sx0, y - sy0
        u = dx * ca - dy * sa   # East (toward Amsterdam/Columbus)
        v = dx * sa + dy * ca   # Uptown (toward 92nd/93rd)
        return u, v

    # Determine map bounds to comfortably include shul + all month spots (default ~W 89th-93rd, Riverside-Amsterdam)
    us = [0.0, -950.0, 350.0]
    vs = [0.0, -450.0, 450.0]
    for sp in spots_ordered:
        u, v = to_grid(sp["x"], sp["y"])
        us.append(u)
        vs.append(v)

    min_u = min(us) - 140
    max_u = max(us) + 140
    min_v = min(vs) - 110
    max_v = max(vs) + 110

    # Maintain aspect ratio
    span_u = max_u - min_u
    span_v = max_v - min_v
    target_aspect = width / height
    if span_u / span_v < target_aspect:
        need_u = span_v * target_aspect
        pad = (need_u - span_u) / 2
        min_u -= pad
        max_u += pad
    else:
        need_v = span_u / target_aspect
        pad = (need_v - span_v) / 2
        min_v -= pad
        max_v += pad

    def proj(x: float, y: float) -> tuple[float, float]:
        u, v = to_grid(x, y)
        px = (u - min_u) / (max_u - min_u) * width
        py = height - (v - min_v) / (max_v - min_v) * height
        return px, py

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" style="width:100%;height:auto;background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;display:block;">'
    ]

    # 1. Draw buildings (light gray polygons, slightly darker for taller buildings)
    b_elems = []
    for b in vm.buildings:
        bx0, by0, bx1, by1 = b.bbox
        # Quick visibility check
        u0, v0 = to_grid(0.5 * (bx0 + bx1), 0.5 * (by0 + by1))
        if u0 < min_u - 250 or u0 > max_u + 250 or v0 < min_v - 250 or v0 > max_v + 250:
            continue
        fill = "#e2e8f0" if b.height_ft < 90 else ("#cbd5e1" if b.height_ft < 160 else "#94a3b8")
        for ring in b.rings:
            pts_str = " ".join(f"{proj(px, py)[0]:.1f},{proj(px, py)[1]:.1f}" for px, py in ring)
            b_elems.append(f'<polygon points="{pts_str}" fill="{fill}" stroke="#ffffff" stroke-width="0.5"/>')
    parts.append("<g>" + "".join(b_elems) + "</g>")

    # 2. Draw street centerlines
    st_elems = []
    label_anchors: dict[str, list[tuple[float, float]]] = {}
    for st in vm.streets:
        pts_p = [proj(px, py) for px, py in st["points"]]
        if all(p[0] < -50 or p[0] > width + 50 or p[1] < -50 or p[1] > height + 50 for p in pts_p):
            continue
        d_str = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts_p)
        sw = 3.2 if "Broadway" in st["name"] else (2.2 if any(a in st["name"] for a in ("Amsterdam", "West End", "Riverside", "Columbus")) else 1.2)
        col = "#ffffff"
        st_elems.append(f'<polyline points="{d_str}" fill="none" stroke="#94a3b8" stroke-width="{sw + 1.2}" stroke-linecap="round"/>')
        st_elems.append(f'<polyline points="{d_str}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linecap="round"/>')
        # Record visible midpoint for street label
        mid = pts_p[len(pts_p) // 2]
        if 30 < mid[0] < width - 30 and 18 < mid[1] < height - 18:
            label_anchors.setdefault(st["name"], []).append(mid)
    parts.append("<g>" + "".join(st_elems) + "</g>")

    # 3. Clean street labels for major avenues & cross streets
    lbl_elems = []
    for name, pts in label_anchors.items():
        if "Park Path" in name or "Path" in name:
            continue
        if any(a in name for a in ("Broadway", "Amsterdam", "West End", "Riverside Dr", "Columbus")):
            avg_x = sum(p[0] for p in pts) / len(pts)
            lbl_elems.append(
                f'<text x="{avg_x:.1f}" y="14" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" '
                f'font-size="9" font-weight="700" fill="#334155" paint-order="stroke" stroke="#f8fafc" stroke-width="3">{html.escape(name)}</text>'
            )
        elif name.startswith("W ") and name.endswith("St"):
            avg_y = sum(p[1] for p in pts) / len(pts)
            lbl_elems.append(
                f'<text x="{width - 8}" y="{avg_y + 3:.1f}" text-anchor="end" font-family="Helvetica,Arial,sans-serif" '
                f'font-size="8.5" font-weight="600" fill="#475569" paint-order="stroke" stroke="#f8fafc" stroke-width="3">{html.escape(name)}</text>'
            )
    parts.append("<g>" + "".join(lbl_elems) + "</g>")

    # 4. Draw Shul marker (210 W 91st St)
    shx, shy = proj(sx0, sy0)
    parts.append(
        f'<g>'
        f'<circle cx="{shx:.1f}" cy="{shy:.1f}" r="9" fill="#0f172a" stroke="#ffffff" stroke-width="2"/>'
        f'<text x="{shx:.1f}" y="{shy + 3.5:.1f}" text-anchor="middle" font-size="10" fill="#fbbf24" font-family="sans-serif">★</text>'
        f'</g>'
    )

    # 5. Draw numbered/lettered viewing spot pins
    for sp in spots_ordered:
        lbl = spot_letters[sp["short_name"]]
        if lbl == "★":
            continue
        px, py = proj(sp["x"], sp["y"])
        parts.append(
            f'<g>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="8" fill="#1d4ed8" stroke="#ffffff" stroke-width="1.8"/>'
            f'<text x="{px:.1f}" y="{py + 3.2:.1f}" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" '
            f'font-size="9" font-weight="700" fill="#ffffff">{lbl}</text>'
            f'</g>'
        )

    # 6. North arrow (True North is 29° counter-clockwise from Grid Up!)
    parts.append(
        '<g transform="translate(26, 26)">'
        '<circle cx="0" cy="0" r="15" fill="#ffffff" fill-opacity="0.9" stroke="#cbd5e1" stroke-width="1"/>'
        '<g transform="rotate(-29)">'
        '<line x1="0" y1="8" x2="0" y2="-7" stroke="#0f172a" stroke-width="1.6"/>'
        '<polygon points="0,-10 -3,-4 3,-4" fill="#dc2626"/>'
        '</g>'
        '<text x="0" y="13" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-size="7" font-weight="700" fill="#334155">N</text>'
        '</g>'
    )

    # 7. Scale bar & building height legend
    parts.append(
        f'<g transform="translate(12, {height - 16})">'
        f'<rect x="0" y="-10" width="210" height="18" rx="3" fill="#ffffff" fill-opacity="0.9" stroke="#cbd5e1" stroke-width="0.8"/>'
        f'<text x="7" y="2" font-family="Helvetica,Arial,sans-serif" font-size="8" fill="#334155">'
        f'★ 210 W 91st (Shul)   •   Darker gray = taller buildings</text>'
        f'</g>'
    )

    parts.append("</svg>")
    return "\n".join(parts), spot_letters


BASE_CSS = """
@page {
  size: letter portrait;
  margin: 0.42in 0.48in;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: #0f172a;
  margin: 0;
  padding: 0;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
.page {
  page-break-after: always;
}
.page:last-child {
  page-break-after: auto;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  border-bottom: 2.5px solid #0f172a;
  padding-bottom: 6px;
  margin-bottom: 10px;
}
.title {
  font-size: 21px;
  font-weight: 800;
  letter-spacing: -0.3px;
  color: #0f172a;
  margin: 0;
}
.subtitle {
  font-size: 11px;
  color: #475569;
  margin-top: 2px;
}
.shul-badge {
  text-align: right;
  font-size: 11px;
  color: #334155;
  line-height: 1.35;
}
.shul-badge strong {
  color: #0f172a;
  font-size: 12px;
}
.zman-banner {
  display: flex;
  gap: 12px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 10px;
}
.zman-box {
  flex: 1;
}
.zman-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: #475569;
  font-weight: 700;
}
.zman-val {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  margin-top: 2px;
}
.zman-sub {
  font-size: 9.5px;
  color: #64748b;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 10.5px;
}
th {
  background: #0f172a;
  color: #ffffff;
  text-align: left;
  padding: 6px 7px;
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  font-weight: 700;
}
td {
  padding: 5.5px 7px;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: middle;
}
tr:nth-child(even) td {
  background: #f8fafc;
}
tr.motzaei td {
  background: #eff6ff !important;
  font-weight: 600;
}
tr.shabbos td {
  color: #94a3b8;
  background: #fafafa !important;
}
.pill {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 8.5px;
  font-weight: 700;
  text-transform: uppercase;
  vertical-align: middle;
  margin-left: 4px;
}
.pill-ms { background: #1d4ed8; color: #ffffff; }
.pill-yt { background: #e2e8f0; color: #64748b; }
.pin {
  display: inline-block;
  width: 17px;
  height: 17px;
  line-height: 17px;
  text-align: center;
  border-radius: 50%;
  background: #1d4ed8;
  color: #ffffff;
  font-size: 9.5px;
  font-weight: 700;
  margin-right: 5px;
}
.pin-shul {
  background: #0f172a;
  color: #fbbf24;
}
.map-section {
  margin-top: 12px;
}
.map-title {
  font-size: 10.5px;
  font-weight: 700;
  color: #334155;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 5px;
}
.footer {
  margin-top: 10px;
  font-size: 8.5px;
  color: #64748b;
  border-top: 1px solid #e2e8f0;
  padding-top: 5px;
  display: flex;
  justify-content: space-between;
}
"""


def render_option_a(vm: VisibilityModel, months: list[dict], out_html: str):
    """Option A: 1 page per month with table + real NYC SVG neighborhood map."""
    pages = []
    for m in months:
        svg_map, spot_letters = render_neighborhood_svg(vm, m, width=720, height=285)
        rows = []
        for n in m["nights"]:
            cls = "shabbos" if n["yom_tov_or_shabbos"] else ("motzaei" if n["is_motzaei_shabbos"] else "")
            badge = ""
            if n["yom_tov_or_shabbos"]:
                badge = f'<span class="pill pill-yt">{html.escape(n["yom_tov_or_shabbos"])}</span>'
            elif n["is_motzaei_shabbos"]:
                badge = '<span class="pill pill-ms">Motzaei Shabbos</span>'

            sp = n.get("nearest_spot")
            if n["yom_tov_or_shabbos"]:
                spot_html = f'<span style="font-style:italic;">Not recited ({html.escape(n["yom_tov_or_shabbos"])})</span>'
            elif sp:
                ltr = spot_letters.get(sp["short_name"], "•")
                pin_cls = "pin pin-shul" if ltr == "★" else "pin"
                spot_html = (
                    f'<span class="{pin_cls}">{ltr}</span>'
                    f'<strong>{html.escape(sp["short_name"])}</strong> '
                    f'<span style="color:#475569;font-size:9.5px;">({walk_time_str(sp["walk_ft"])})</span>'
                )
            else:
                spot_html = f'<span style="color:#b91c1c;">{html.escape(n.get("moon_note") or "Blocked within 6 blocks")}</span>'

            dir_html = (
                f'{arrow_svg(n["moon_az_deg"], 15)}'
                f'<strong>{n["moon_compass"]}</strong> '
                f'<span style="color:#64748b;font-size:9.5px;">({round(n["moon_az_deg"])}°)</span>'
            )
            alt_html = f'{round(n["moon_alt_deg"])}°' if n["moon_alt_deg"] > 0 else "—"
            note_extra = f'<div style="font-size:8.5px;color:#64748b;">{html.escape(n["window_note"])}</div>' if n.get("window_note") else ""

            rows.append(
                f'<tr class="{cls}">'
                f'<td><strong>{n["day_of_week"]}, {fmt_date_short(n["civil_date"])}</strong>{badge}{note_extra}</td>'
                f'<td>{html.escape(n["heb_date_str"])}</td>'
                f'<td>{fmt_time(n["tzeis"])}</td>'
                f'<td>{dir_html}</td>'
                f'<td style="text-align:center;">{alt_html}</td>'
                f'<td>{spot_html}</td>'
                f'</tr>'
            )

        special = f' &bull; {html.escape(m["special_note"])}' if m.get("special_note") else ""
        pages.append(f"""
        <div class="page">
          <div class="header">
            <div>
              <h1 class="title">Kiddush Levanah &mdash; {html.escape(m['month_name'])} {m['hebrew_year']}</h1>
              <div class="subtitle">Option A Preview: Monthly Bulletin Sheet + 3D Building Visibility Map</div>
            </div>
            <div class="shul-badge">
              <strong>210 West 91st Street</strong><br/>
              Upper West Side, NYC
            </div>
          </div>

          <div class="zman-banner">
            <div class="zman-box">
              <div class="zman-label">Earliest Time (3 Full Days{special})</div>
              <div class="zman-val">{fmt_dt_banner(m['earliest_ny'])}</div>
            </div>
            <div class="zman-box">
              <div class="zman-label">Latest Time (15 Full Days)</div>
              <div class="zman-val">{fmt_dt_banner(m['latest_ny'])}</div>
            </div>
            <div class="zman-box" style="flex:0.75;">
              <div class="zman-label">Molad (NYC Time)</div>
              <div class="zman-val" style="font-size:11.5px;">{fmt_dt_banner(m['molad_ny'])}</div>
            </div>
          </div>

          <table>
            <thead>
              <tr>
                <th style="width:22%;">Night</th>
                <th style="width:11%;">Hebrew</th>
                <th style="width:10%;">Tzeis (50m)</th>
                <th style="width:14%;">Direction</th>
                <th style="width:7%;text-align:center;">Angle</th>
                <th style="width:36%;">Nearest Clear Spot from 210 W 91st</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows)}
            </tbody>
          </table>

          <div class="map-section">
            <div class="map-title">Neighborhood Viewing Map (Uptown = Up &bull; Letters match table above)</div>
            {svg_map}
          </div>

          <div class="footer">
            <span>Tzeis = Shkiah + 50 min &bull; Moon angle projected against NYC 3D building heights (eye level 5.5 ft, +1.5° roof margin)</span>
            <span>210 W 91st St &bull; 5787</span>
          </div>
        </div>
        """)

    html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{BASE_CSS}</style></head><body>{''.join(pages)}</body></html>"
    with open(out_html, "w") as f:
        f.write(html_doc)


def render_option_b(months: list[dict], out_html: str):
    """Option B: 1 page per month large-print table only with UWS street directions."""
    extra_css = """
    table { font-size: 12px; }
    th { padding: 8px 8px; font-size: 10.5px; }
    td { padding: 9px 8px; }
    .title { font-size: 25px; }
    .zman-val { font-size: 15px; }
    .uws-dir { font-size: 10px; color: #475569; margin-top: 2px; }
    .tip-box {
      margin-top: 16px;
      padding: 10px 14px;
      background: #f8fafc;
      border-left: 4px solid #1d4ed8;
      border-radius: 4px;
      font-size: 11px;
      color: #334155;
      line-height: 1.5;
    }
    """
    pages = []
    for m in months:
        rows = []
        for n in m["nights"]:
            cls = "shabbos" if n["yom_tov_or_shabbos"] else ("motzaei" if n["is_motzaei_shabbos"] else "")
            badge = ""
            if n["yom_tov_or_shabbos"]:
                badge = f'<span class="pill pill-yt">{html.escape(n["yom_tov_or_shabbos"])}</span>'
            elif n["is_motzaei_shabbos"]:
                badge = '<span class="pill pill-ms">Motzaei Shabbos</span>'

            sp = n.get("nearest_spot")
            if n["yom_tov_or_shabbos"]:
                spot_html = f'<span style="font-style:italic;">Not recited ({html.escape(n["yom_tov_or_shabbos"])})</span>'
                walk_html = "—"
            elif sp:
                spot_html = f'<strong>{html.escape(sp["name"])}</strong>'
                walk_html = walk_time_str(sp["walk_ft"])
            else:
                spot_html = f'<span style="color:#b91c1c;">{html.escape(n.get("moon_note") or "Blocked within 6 blocks")}</span>'
                walk_html = "—"

            dir_html = (
                f'<div>{arrow_svg(n["moon_az_deg"], 17)}<strong>{n["moon_compass"]}</strong> ({round(n["moon_az_deg"])}°) &bull; <strong>{round(n["moon_alt_deg"])}° up</strong></div>'
                f'<div class="uws-dir">{html.escape(n["moon_uws_dir"])}</div>'
            )

            rows.append(
                f'<tr class="{cls}">'
                f'<td><strong>{n["day_of_week"]}, {fmt_date_short(n["civil_date"])}</strong><br/><span style="font-size:10px;color:#64748b;">{html.escape(n["heb_date_str"])}</span>{badge}</td>'
                f'<td><strong>{fmt_time(n["tzeis"])}</strong></td>'
                f'<td>{dir_html}</td>'
                f'<td>{spot_html}</td>'
                f'<td style="white-space:nowrap;">{walk_html}</td>'
                f'</tr>'
            )

        special = f' &bull; {html.escape(m["special_note"])}' if m.get("special_note") else ""
        pages.append(f"""
        <div class="page">
          <div class="header">
            <div>
              <h1 class="title">Kiddush Levanah &mdash; {html.escape(m['month_name'])} {m['hebrew_year']}</h1>
              <div class="subtitle">Option B Preview: Large-Print Monthly Bulletin Sheet (No Map)</div>
            </div>
            <div class="shul-badge">
              <strong>210 West 91st Street</strong><br/>
              Upper West Side, NYC
            </div>
          </div>

          <div class="zman-banner">
            <div class="zman-box">
              <div class="zman-label">Earliest Time (3 Full Days{special})</div>
              <div class="zman-val">{fmt_dt_banner(m['earliest_ny'])}</div>
            </div>
            <div class="zman-box">
              <div class="zman-label">Latest Time (15 Full Days)</div>
              <div class="zman-val">{fmt_dt_banner(m['latest_ny'])}</div>
            </div>
          </div>

          <table>
            <thead>
              <tr>
                <th style="width:19%;">Date</th>
                <th style="width:11%;">Tzeis</th>
                <th style="width:30%;">Where to Look (at Tzeis)</th>
                <th style="width:27%;">Nearest Clear Spot</th>
                <th style="width:13%;">Walk</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows)}
            </tbody>
          </table>

          <div class="tip-box">
            <strong>How to read this sheet:</strong> Walk to the listed corner or sidewalk at <em>tzeis</em> (50 min after shkiah) and look in the indicated direction and elevation angle (e.g., 45° is halfway up the sky). All spots are verified against NYC 3D building heights from 210 W 91st St.
          </div>

          <div class="footer">
            <span>Molad (NYC): {fmt_dt_banner(m['molad_ny'])} &bull; Tzeis = Shkiah + 50 min</span>
            <span>210 W 91st St &bull; 5787</span>
          </div>
        </div>
        """)

    html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{BASE_CSS}{extra_css}</style></head><body>{''.join(pages)}</body></html>"
    with open(out_html, "w") as f:
        f.write(html_doc)


def render_option_c(months: list[dict], out_html: str):
    """Option C: Compact packet — 2 Hebrew months per US Letter page (~7 pages for full year)."""
    extra_css = """
    @page { margin: 0.32in 0.4in; }
    .month-block { margin-bottom: 14px; }
    .m-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      background: #0f172a;
      color: #ffffff;
      padding: 5px 10px;
      border-radius: 4px 4px 0 0;
    }
    .m-head h2 { margin: 0; font-size: 13.5px; font-weight: 800; }
    .m-head .z-inline { font-size: 9.5px; color: #e2e8f0; }
    .m-head .z-inline strong { color: #fbbf24; }
    table { font-size: 9.2px; }
    th { background: #334155; padding: 3.5px 6px; font-size: 8.2px; }
    td { padding: 3.2px 6px; }
    .pill { font-size: 7.5px; padding: 0.5px 4px; }
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1.5px solid #cbd5e1;
      padding-bottom: 4px;
      margin-bottom: 8px;
      font-size: 10px;
      color: #475569;
    }
    .top-bar strong { color: #0f172a; font-size: 11.5px; }
    """
    pages = []
    for i in range(0, len(months), 2):
        chunk = months[i:i + 2]
        blocks = []
        for m in chunk:
            rows = []
            for n in m["nights"]:
                cls = "shabbos" if n["yom_tov_or_shabbos"] else ("motzaei" if n["is_motzaei_shabbos"] else "")
                badge = ""
                if n["yom_tov_or_shabbos"]:
                    badge = f'<span class="pill pill-yt">{html.escape(n["yom_tov_or_shabbos"])}</span>'
                elif n["is_motzaei_shabbos"]:
                    badge = '<span class="pill pill-ms">Motzaei Shabbos</span>'

                sp = n.get("nearest_spot")
                if n["yom_tov_or_shabbos"]:
                    spot_html = "—"
                    walk_html = "—"
                elif sp:
                    spot_html = f'<strong>{html.escape(sp["short_name"])}</strong>'
                    walk_html = f'{sp["walk_ft"]} ft'
                else:
                    spot_html = html.escape(n.get("moon_note") or "Blocked")
                    walk_html = "—"

                rows.append(
                    f'<tr class="{cls}">'
                    f'<td><strong>{n["day_of_week"]} {fmt_date_short(n["civil_date"])}</strong>{badge}</td>'
                    f'<td>{html.escape(n["heb_date_str"])}</td>'
                    f'<td>{fmt_time(n["tzeis"])}</td>'
                    f'<td>{arrow_svg(n["moon_az_deg"], 12)}<strong>{n["moon_compass"]}</strong> ({round(n["moon_az_deg"])}°)</td>'
                    f'<td style="text-align:center;">{round(n["moon_alt_deg"])}°</td>'
                    f'<td>{spot_html}</td>'
                    f'<td style="text-align:right;color:#475569;">{walk_html}</td>'
                    f'</tr>'
                )

            blocks.append(f"""
            <div class="month-block">
              <div class="m-head">
                <h2>{html.escape(m['month_name'])} {m['hebrew_year']}</h2>
                <div class="z-inline">
                  <strong>Earliest:</strong> {fmt_dt_banner(m['earliest_ny'])} &nbsp;|&nbsp;
                  <strong>Latest:</strong> {fmt_dt_banner(m['latest_ny'])}
                </div>
              </div>
              <table>
                <thead>
                  <tr>
                    <th style="width:23%;">Night</th>
                    <th style="width:11%;">Hebrew</th>
                    <th style="width:10%;">Tzeis</th>
                    <th style="width:15%;">Direction</th>
                    <th style="width:6%;text-align:center;">Alt</th>
                    <th style="width:27%;">Nearest Clear Spot</th>
                    <th style="width:8%;text-align:right;">Walk</th>
                  </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </div>
            """)

        pages.append(f"""
        <div class="page">
          <div class="top-bar">
            <strong>Kiddush Levanah Guide 5787 &mdash; 210 West 91st St (Option C: Compact 2-Months/Page)</strong>
            <span>Tzeis = Shkiah + 50m &bull; 3d to 15d after molad</span>
          </div>
          {''.join(blocks)}
        </div>
        """)

    html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{BASE_CSS}{extra_css}</style></head><body>{''.join(pages)}</body></html>"
    with open(out_html, "w") as f:
        f.write(html_doc)


def html_to_pdf_and_png(html_path: str, pdf_path: str, png_path: str):
    import tempfile
    with tempfile.TemporaryDirectory(prefix="chrome_levanah_") as tmpdir:
        subprocess.run(
            [
                CHROME_BIN,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={tmpdir}/p1",
                f"--print-to-pdf={pdf_path}",
                "--no-pdf-header-footer",
                f"file://{html_path}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                CHROME_BIN,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={tmpdir}/p2",
                f"--screenshot={png_path}",
                "--window-size=850,1100",
                "--force-device-scale-factor=2",
                f"file://{html_path}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    with open(os.path.join(DATA_DIR, "levanah_5787.json")) as f:
        data = json.load(f)

    vm = VisibilityModel()
    # Pick Teves & Shevat 5787 as the sample months (upcoming months!)
    teves = [m for m in data["months"] if m["month_name"] == "Teves"]
    teves_shevat = [m for m in data["months"] if m["month_name"] in ("Teves", "Shevat")]

    render_option_a(vm, teves, os.path.join(SAMPLE_DIR, "option_a_map.html"))
    render_option_b(teves, os.path.join(SAMPLE_DIR, "option_b_large_table.html"))
    render_option_c(teves_shevat, os.path.join(SAMPLE_DIR, "option_c_compact.html"))

    for stem in ("option_a_map", "option_b_large_table", "option_c_compact"):
        hp = os.path.join(SAMPLE_DIR, f"{stem}.html")
        pp = os.path.join(SAMPLE_DIR, f"{stem}.pdf")
        gp = os.path.join(SAMPLE_DIR, f"{stem}.png")
        html_to_pdf_and_png(hp, pp, gp)
        print(f"Generated {pp} and {gp}")

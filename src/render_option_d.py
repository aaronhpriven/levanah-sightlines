#!/usr/bin/env python3
"""
Option D: Full-Year 5787 Motzaei Shabbos (+ Motzaei Yom Kippur & Motzaei Tisha B'Av) Guide
with a Neighborhood Viewing Map on EACH page.
Fits the entire 13-month leap year 5787 on 2 pages (1 double-sided US Letter sheet)!
"""

from __future__ import annotations

import datetime
import html
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_layouts import (
    BASE_CSS,
    CHROME_BIN,
    DATA_DIR,
    OUT_DIR,
    SAMPLE_DIR,
    arrow_svg,
    fmt_date_short,
    fmt_time,
    render_neighborhood_svg,
    walk_time_str,
)
from visibility import VisibilityModel


def fmt_dt_compact(iso_str: str) -> str:
    dt = datetime.datetime.fromisoformat(iso_str)
    return dt.strftime("%b %-d, %-I:%M%p").replace("AM", "am").replace("PM", "pm")


def filter_motzaei_nights(month: dict) -> list[dict]:
    out = []
    for n in month["nights"]:
        is_yk = (month["month_num"] == 7 and n["heb_day"] == 11)
        is_tb = (month["month_num"] == 5 and n["heb_day"] == 10)
        if n["is_motzaei_shabbos"] or is_yk or is_tb:
            n_copy = dict(n)
            if is_yk:
                n_copy["special_tag"] = "Motzaei YK"
            elif is_tb:
                n_copy["special_tag"] = "Motzaei 9 Av"
            else:
                n_copy["special_tag"] = "Motzaei Shabbos"
            out.append(n_copy)
    return out


OPTION_D_CSS = """
@page {
  size: letter portrait;
  margin: 0.36in 0.44in;
}
.header {
  margin-bottom: 8px;
  padding-bottom: 5px;
}
.title { font-size: 19px; }
.subtitle { font-size: 10px; }
table { font-size: 9.8px; }
th { padding: 5px 6px; font-size: 8.8px; }
td { padding: 4.5px 6px; }
.m-cell {
  background: #f1f5f9 !important;
  border-right: 1px solid #cbd5e1;
  vertical-align: top;
}
.m-name {
  font-size: 10.5px;
  font-weight: 800;
  color: #0f172a;
}
.m-win {
  font-size: 8px;
  color: #475569;
  line-height: 1.3;
  margin-top: 2px;
}
tr.month-end td {
  border-bottom: 1.5px solid #94a3b8;
}
.pill-yk { background: #7c3aed; color: #ffffff; }
.pill-tb { background: #b45309; color: #ffffff; }
.note-sub {
  font-size: 8.2px;
  color: #b45309;
  margin-top: 1px;
}
.map-section { margin-top: 10px; }
.map-title { font-size: 9.8px; margin-bottom: 4px; }
.footer { margin-top: 7px; font-size: 8.2px; }
"""


def build_page_html(vm: VisibilityModel, months_chunk: list[dict], page_title: str, page_num: int, total_pages: int) -> str:
    # Build combined pseudo-month for the SVG map so all spots on this page get clean A, B, C... pins
    combined_nights = []
    filtered_by_month = []
    for m in months_chunk:
        fn = filter_motzaei_nights(m)
        filtered_by_month.append((m, fn))
        combined_nights.extend(fn)

    map_height = 290 if len(combined_nights) <= 11 else 255
    svg_map, spot_letters = render_neighborhood_svg(vm, {"nights": combined_nights}, width=730, height=map_height)

    rows = []
    for m, fn in filtered_by_month:
        n_rows = len(fn)
        win_html = (
            f'<div class="m-name">{html.escape(m["month_name"])}</div>'
            f'<div class="m-win">'
            f'<strong>Earliest:</strong> {fmt_dt_compact(m["earliest_ny"])}<br/>'
            f'<strong>Latest:</strong> {fmt_dt_compact(m["latest_ny"])}'
            f'</div>'
        )
        for idx, n in enumerate(fn):
            tr_cls = "month-end" if idx == n_rows - 1 else ""
            tag = n["special_tag"]
            if tag == "Motzaei YK":
                pill = '<span class="pill pill-yk">Motzaei YK</span>'
            elif tag == "Motzaei 9 Av":
                pill = '<span class="pill pill-tb">Motzaei 9 Av</span>'
            else:
                pill = ''

            sp = n.get("nearest_spot")
            if sp:
                ltr = spot_letters.get(sp["short_name"], "•")
                pin_cls = "pin pin-shul" if ltr == "★" else "pin"
                wait_note = ""
                if sp.get("wait_time_str"):
                    wait_note = f'<div class="note-sub">Clear at {sp["wait_time_str"]} ({round(sp["later_alt_deg"])}° {sp["later_compass"]})</div>'
                spot_html = (
                    f'<span class="{pin_cls}">{ltr}</span>'
                    f'<strong>{html.escape(sp["short_name"])}</strong> '
                    f'<span style="color:#475569;font-size:8.8px;">({walk_time_str(sp["walk_ft"])})</span>'
                    f'{wait_note}'
                )
            else:
                extra = f' ({n["window_note"]})' if n.get("window_note") else ""
                spot_html = f'<span style="color:#b91c1c;font-size:9px;">Low/blocked at tzeis{html.escape(extra)} &mdash; use earlier night</span>'

            dir_html = (
                f'{arrow_svg(n["moon_az_deg"], 14)}'
                f'<strong>{n["moon_compass"]}</strong> '
                f'<span style="color:#64748b;font-size:8.8px;">({round(n["moon_az_deg"])}°)</span>'
            )

            m_td = f'<td class="m-cell" rowspan="{n_rows}">{win_html}</td>' if idx == 0 else ""
            rows.append(
                f'<tr class="{tr_cls}">'
                f'{m_td}'
                f'<td><strong>{n["day_of_week"]}, {fmt_date_short(n["civil_date"])}</strong> '
                f'<span style="color:#64748b;font-size:8.8px;">({html.escape(n["heb_date_str"])})</span>{pill}</td>'
                f'<td><strong>{fmt_time(n["tzeis"])}</strong></td>'
                f'<td>{dir_html}</td>'
                f'<td style="text-align:center;">{round(n["moon_alt_deg"])}°</td>'
                f'<td>{spot_html}</td>'
                f'</tr>'
            )

    return f"""
    <div class="page">
      <div class="header">
        <div>
          <h1 class="title">Kiddush Levanah 5787 &mdash; {html.escape(page_title)}</h1>
          <div class="subtitle">Motzaei Shabbos, Motzaei Yom Kippur &amp; Motzaei Tisha B'Av &bull; 3D Building Visibility Guide</div>
        </div>
        <div class="shul-badge">
          <strong>Young Israel of the West Side</strong><br/>
          210 West 91st Street &bull; Page {page_num} of {total_pages}
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th style="width:21%;">Month &amp; Window</th>
            <th style="width:20%;">Night</th>
            <th style="width:9%;">Tzeis</th>
            <th style="width:13%;">Direction</th>
            <th style="width:6%;text-align:center;">Angle</th>
            <th style="width:31%;">Nearest Clear Spot from Shul</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>

      <div class="map-section">
        <div class="map-title">Neighborhood Viewing Map &mdash; {html.escape(page_title)} (Uptown = Up &bull; Letters match table above)</div>
        {svg_map}
      </div>

      <div class="footer">
        <span>Window: 3 to 15 full days after molad (after YK in Tishrei, after 9 Av in Av) &bull; Tzeis = Shkiah + 50 min &bull; Verified clear for 20 min post-tzeis</span>
        <span>Young Israel of the West Side &bull; 5787</span>
      </div>
    </div>
    """


def render_pdf_and_page_pngs(full_html_path: str, page1_html: str, page2_html: str):
    pdf_path = os.path.join(OUT_DIR, "YIWS_Kiddush_Levanah_5787.pdf")
    p1_png = os.path.join(SAMPLE_DIR, "yiws_page1.png")
    p2_png = os.path.join(SAMPLE_DIR, "yiws_page2.png")

    with tempfile.TemporaryDirectory(prefix="chrome_optd_") as tmpdir:
        p1_h = os.path.join(tmpdir, "p1.html")
        p2_h = os.path.join(tmpdir, "p2.html")
        with open(p1_h, "w") as f:
            f.write(page1_html)
        with open(p2_h, "w") as f:
            f.write(page2_html)

        subprocess.run(
            [
                CHROME_BIN, "--headless=new", "--disable-gpu", "--no-sandbox",
                f"--user-data-dir={tmpdir}/u0",
                f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                f"file://{full_html_path}",
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for idx, (hp, gp) in enumerate([(p1_h, p1_png), (p2_h, p2_png)], 1):
            subprocess.run(
                [
                    CHROME_BIN, "--headless=new", "--disable-gpu", "--no-sandbox",
                    f"--user-data-dir={tmpdir}/u{idx}",
                    f"--screenshot={gp}", "--window-size=850,1100", "--force-device-scale-factor=2",
                    f"file://{hp}",
                ],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    print(f"Generated {pdf_path}, {p1_png}, {p2_png}")


if __name__ == "__main__":
    with open(os.path.join(DATA_DIR, "levanah_5787.json")) as f:
        data = json.load(f)

    vm = VisibilityModel()
    months = data["months"]
    # Split 13 months into 2 balanced pages:
    # Page 1: Tishrei – Adar I (6 months, 10 nights)
    # Page 2: Adar II – Elul (7 months, 13 nights)
    p1_body = build_page_html(vm, months[:6], "Fall & Winter (Tishrei – Adar I)", 1, 2)
    p2_body = build_page_html(vm, months[6:], "Spring & Summer (Adar II – Elul)", 2, 2)

    wrap = lambda body: f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{BASE_CSS}{OPTION_D_CSS}</style></head><body>{body}</body></html>"
    full_html = wrap(p1_body + p2_body)
    full_html_path = os.path.join(SAMPLE_DIR, "option_d_motzaei_shabbos.html")
    with open(full_html_path, "w") as f:
        f.write(full_html)

    render_pdf_and_page_pngs(full_html_path, wrap(p1_body), wrap(p2_body))

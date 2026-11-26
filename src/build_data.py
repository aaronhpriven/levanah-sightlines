#!/usr/bin/env python3
"""
Combine Hebrew calendar / lunar calculations with 3D NYC building visibility
for 210 West 91st St for the full Hebrew year 5787.
"""

from __future__ import annotations

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calendar_moon import UTC, compass_direction, compute_year, moon_alt_az
from visibility import SHUL_LAT, SHUL_LON, VisibilityModel

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def build_all(year: int = 5787, tzeis_minutes: int = 50):
    vm = VisibilityModel()
    shul_elev_ft = vm.local_ground_elev_ft(vm.shul_sidewalk_xy[0], vm.shul_sidewalk_xy[1])
    shul_elev_m = shul_elev_ft / 3.28084

    months = compute_year(
        year=year,
        shul_lat=SHUL_LAT,
        shul_lon=SHUL_LON,
        shul_elev_m=shul_elev_m,
        tzeis_minutes=tzeis_minutes,
    )

    def window_samples(start_dt: datetime.datetime, duration_min: int = 20) -> list[tuple[float, float]]:
        samples = []
        for off in range(0, duration_min + 1):
            dt = start_dt + datetime.timedelta(minutes=off)
            a, z, _ = moon_alt_az(dt.astimezone(UTC), SHUL_LAT, SHUL_LON, shul_elev_m)
            samples.append((z, a))
        return samples

    total_nights = 0
    found_spots = 0
    for m in months:
        latest_dt = datetime.datetime.fromisoformat(m["latest_ny"])
        for n in m["nights"]:
            total_nights += 1
            alt = n["moon_alt_deg"]
            az = n["moon_az_deg"]
            eval_dt = datetime.datetime.fromisoformat(n["eval_time"])
            if alt > 0.5:
                # Require full 20-min post-tzeis visibility
                spot = vm.find_nearest_spot_window(window_samples(eval_dt, 20))
                if spot:
                    found_spots += 1
                    n["nearest_spot"] = spot
                else:
                    # If blocked (or doesn't stay clear for 20m) at tzeis, check +30m, +60m, +90m
                    later_spot = None
                    for add_min in (30, 60, 90):
                        try_dt = eval_dt + datetime.timedelta(minutes=add_min)
                        if try_dt >= latest_dt:
                            break
                        a2, z2, _ = moon_alt_az(try_dt.astimezone(UTC), SHUL_LAT, SHUL_LON, shul_elev_m)
                        if a2 > 0.5:
                            s2 = vm.find_nearest_spot_window(window_samples(try_dt, 20))
                            if s2:
                                s2["wait_time_str"] = try_dt.strftime("%-I:%M %p")
                                s2["wait_minutes"] = add_min
                                s2["later_alt_deg"] = round(a2, 1)
                                s2["later_az_deg"] = round(z2, 1)
                                s2["later_compass"] = compass_direction(z2)
                                later_spot = s2
                                break
                    if later_spot:
                        found_spots += 1
                        n["nearest_spot"] = later_spot
                        n["moon_note"] = f"Blocked at tzeis; clear at {later_spot['wait_time_str']} ({round(later_spot['later_alt_deg'])}°)"
                    else:
                        n["nearest_spot"] = None
                # Also check visibility right outside the shul for comparison
                shul_cand = vm.candidates[0]
                shul_clear, shul_clr_deg = vm.check_visibility(
                    shul_cand["x"], shul_cand["y"], shul_cand["ground_ft"], az, alt
                )
                n["visible_outside_shul"] = shul_clear
                n["shul_clearance_deg"] = shul_clr_deg
            else:
                n["nearest_spot"] = None
                n["visible_outside_shul"] = False
                n["shul_clearance_deg"] = None

    out_path = os.path.join(DATA_DIR, f"levanah_{year}.json")
    payload = {
        "hebrew_year": year,
        "shul_address": "210 West 91st St, New York, NY 10024",
        "shul_lat": SHUL_LAT,
        "shul_lon": SHUL_LON,
        "shul_sidewalk_xy": list(vm.shul_sidewalk_xy),
        "tzeis_rule": f"Shkiah + {tzeis_minutes} min",
        "window_rule": "3 full days to 15 full days after molad",
        "months": months,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Saved {out_path}: {len(months)} months, {total_nights} nights, {found_spots} nights with clear spots.")
    return payload


if __name__ == "__main__":
    data = build_all(5787, tzeis_minutes=50)
    # Print a detailed preview of Kislev 5787 and Nissan 5787
    for m in data["months"]:
        if m["month_name"] in ("Kislev", "Teves", "Nissan"):
            print(f"\n=== {m['month_name']} 5787 (Earliest: {m['earliest_ny'][:16]} | Latest: {m['latest_ny'][:16]}) ===")
            for n in m["nights"]:
                spot = n["nearest_spot"]
                spot_str = f"{spot['short_name']} ({spot['walk_ft']} ft, +{spot['clearance_deg']}°)" if spot else (n["moon_note"] or "No clear spot within 6 blocks")
                flag = f" [{n['yom_tov_or_shabbos']}]" if n["yom_tov_or_shabbos"] else (" [MOTZAEI SHABBOS]" if n["is_motzaei_shabbos"] else "")
                print(
                    f"  {n['civil_date']} ({n['day_of_week']}) {n['heb_date_str']:10s} | "
                    f"Tzeis {n['tzeis'][11:16]} | Moon {n['moon_compass']:3s} ({n['moon_az_deg']:5.1f}°) alt {n['moon_alt_deg']:4.1f}° | "
                    f"{spot_str}{flag}"
                )

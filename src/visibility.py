#!/usr/bin/env python3
"""
3D NYC Building Line-of-Sight Engine for 210 West 91st St.
Uses cached NYC Open Data Building Footprints (5zhs-2jue) and OSM street network.
Pure Python (zero external dependencies).
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# 210 West 91st St (from NYC Planning Labs GeoSearch)
SHUL_LAT = 40.790886
SHUL_LON = -73.973311

FT_PER_METER = 3.280839895
DEG = math.pi / 180.0
RAD = 180.0 / math.pi

# Manhattan street grid rotation: Uptown is ~29.0° east of true north
GRID_ANGLE_RAD = 29.0 * DEG
COS_G = math.cos(GRID_ANGLE_RAD)
SIN_G = math.sin(GRID_ANGLE_RAD)

# Meters per degree at SHUL_LAT
M_PER_DEG_LAT = 111132.954
M_PER_DEG_LON = 111319.491 * math.cos(SHUL_LAT * DEG)


def latlon_to_ft(lat: float, lon: float) -> tuple[float, float]:
    """Convert (lat, lon) to local (x_east_ft, y_north_ft) relative to 210 W 91st St."""
    x = (lon - SHUL_LON) * M_PER_DEG_LON * FT_PER_METER
    y = (lat - SHUL_LAT) * M_PER_DEG_LAT * FT_PER_METER
    return x, y


def ft_to_latlon(x: float, y: float) -> tuple[float, float]:
    lat = SHUL_LAT + (y / FT_PER_METER) / M_PER_DEG_LAT
    lon = SHUL_LON + (x / FT_PER_METER) / M_PER_DEG_LON
    return lat, lon


def grid_walk_distance_ft(x: float, y: float, ox: float = 0.0, oy: float = 0.0) -> float:
    """Manhattan walking distance along the rotated UWS street grid (in feet)."""
    dx = x - ox
    dy = y - oy
    # Project onto grid axes: uptown=(sin 29, cos 29), east-crosstown=(cos 29, -sin 29)
    along_ave = abs(dx * SIN_G + dy * COS_G)
    along_st = abs(dx * COS_G - dy * SIN_G)
    return along_ave + along_st


def point_in_polygon(px: float, py: float, ring: list[tuple[float, float]]) -> bool:
    """Standard ray-casting point-in-polygon test."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def ray_segment_intersect(
    ox: float, oy: float, dx: float, dy: float,
    x1: float, y1: float, x2: float, y2: float,
) -> float | None:
    """
    Intersect ray P(t) = (ox, oy) + t*(dx, dy) (t > 0) with segment (x1,y1)-(x2,y2).
    Returns t if intersected, else None.
    """
    sx = x2 - x1
    sy = y2 - y1
    denom = dx * sy - dy * sx
    if abs(denom) < 1e-9:
        return None
    qpx = x1 - ox
    qpy = y1 - oy
    t = (qpx * sy - qpy * sx) / denom
    if t <= 0.5:  # ignore self-touching at < 0.5 ft
        return None
    u = (qpx * dy - qpy * dx) / denom
    if -1e-9 <= u <= 1.0 + 1e-9:
        return t
    return None


class Building:
    __slots__ = ("rings", "bbox", "ground_ft", "height_ft", "top_ft")

    def __init__(self, rings: list[list[tuple[float, float]]], ground_ft: float, height_ft: float):
        self.rings = rings
        self.ground_ft = ground_ft
        self.height_ft = height_ft
        # Add 4 ft parapet/rooftop allowance
        self.top_ft = ground_ft + height_ft + 4.0
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))


class VisibilityModel:
    def __init__(self):
        self.buildings: list[Building] = []
        self.streets: list[dict] = []
        self.candidates: list[dict] = []
        self.shul_sidewalk_xy: tuple[float, float] = (0.0, 0.0)
        self._load_buildings()
        self._load_streets_and_build_candidates()

    def _load_buildings(self):
        path = os.path.join(DATA_DIR, "nyc_buildings.geojson")
        with open(path) as f:
            gj = json.load(f)

        elevs = []
        raw = []
        for feat in gj.get("features", []):
            props = feat.get("properties", {})
            geom = feat.get("geometry")
            if not geom:
                continue
            try:
                h = float(props.get("height_roof") or 0.0)
            except (TypeError, ValueError):
                h = 0.0
            try:
                g = float(props.get("ground_elevation")) if props.get("ground_elevation") is not None else None
            except (TypeError, ValueError):
                g = None
            if g is not None:
                elevs.append(g)
            if h <= 5.0:
                continue

            rings = []
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])
            if gtype == "Polygon":
                for ring in coords[:1]:  # outer ring
                    rings.append([latlon_to_ft(pt[1], pt[0]) for pt in ring])
            elif gtype == "MultiPolygon":
                for poly in coords:
                    for ring in poly[:1]:
                        rings.append([latlon_to_ft(pt[1], pt[0]) for pt in ring])
            if rings:
                raw.append((rings, g, h))

        median_elev = sorted(elevs)[len(elevs) // 2] if elevs else 85.0
        for rings, g, h in raw:
            self.buildings.append(Building(rings, g if g is not None else median_elev, h))

    def is_inside_building(self, x: float, y: float, pad: float = 2.0) -> bool:
        for b in self.buildings:
            x0, y0, x1, y1 = b.bbox
            if x < x0 - pad or x > x1 + pad or y < y0 - pad or y > y1 + pad:
                continue
            for ring in b.rings:
                if point_in_polygon(x, y, ring):
                    return True
        return False

    def local_ground_elev_ft(self, x: float, y: float) -> float:
        """Estimate ground elevation at (x, y) from nearest building's ground_elevation."""
        best_d2 = 1e18
        best_g = 85.0
        for b in self.buildings:
            cx = 0.5 * (b.bbox[0] + b.bbox[2])
            cy = 0.5 * (b.bbox[1] + b.bbox[3])
            d2 = (cx - x) ** 2 + (cy - y) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_g = b.ground_ft
        return best_g

    def _clean_street_name(self, name: str) -> str:
        name = name.strip()
        # Normalize NYC CSCL street labels (e.g. "W 91 ST", "BROADWAY", "AMSTERDAM AVE")
        words = name.split()
        out = []
        for w in words:
            uw = w.upper()
            if uw == "W":
                out.append("W")
            elif uw == "E":
                out.append("E")
            elif uw == "ST":
                out.append("St")
            elif uw == "AVE":
                out.append("Ave")
            elif uw == "DR":
                out.append("Dr")
            elif uw == "PKWY":
                out.append("Pkwy")
            elif uw == "PLZ":
                out.append("Plz")
            elif uw.isdigit():
                n = int(uw)
                suf = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
                out.append(f"{n}{suf}")
            else:
                out.append(w.capitalize())
        res = " ".join(out)
        res = res.replace("West ", "W ").replace(" Street", " St").replace(" Avenue", " Ave")
        return res

    def _load_streets_and_build_candidates(self):
        st_path = os.path.join(DATA_DIR, "nyc_streets.geojson")
        named_ways_by_name: dict[str, list[list[tuple[float, float]]]] = defaultdict(list)
        # Cluster endpoints (rounded to 15 ft grid) to detect intersections
        endpoint_streets: dict[tuple[int, int], set[str]] = defaultdict(set)
        endpoint_coords: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)

        if os.path.exists(st_path):
            with open(st_path) as f:
                gj = json.load(f)
            for feat in gj.get("features", []):
                props = feat.get("properties", {})
                geom = feat.get("geometry")
                if not geom:
                    continue
                # Skip highway ramps / non-walkable parkways (e.g. Henry Hudson Pkwy)
                raw_name = props.get("stname_label") or props.get("full_street_name") or ""
                if not raw_name:
                    continue
                cname = self._clean_street_name(raw_name)
                if any(bad in cname for bad in ("Henry Hudson", "Ramp", "Exit", "Pedestrian Path", "Driveway", "Alley")):
                    continue
                try:
                    st_width = float(props.get("streetwidth") or 34.0)
                except (TypeError, ValueError):
                    st_width = 34.0

                gtype = geom.get("type")
                lines = []
                if gtype == "LineString":
                    lines = [geom["coordinates"]]
                elif gtype == "MultiLineString":
                    lines = geom["coordinates"]

                for line in lines:
                    pts = [latlon_to_ft(pt[1], pt[0]) for pt in line]
                    if len(pts) < 2:
                        continue
                    named_ways_by_name[cname].append(pts)
                    self.streets.append({"name": cname, "width": st_width, "points": pts})
                    for ep in (pts[0], pts[-1]):
                        key = (round(ep[0] / 15.0), round(ep[1] / 15.0))
                        endpoint_streets[key].add(cname)
                        endpoint_coords[key].append(ep)

        # Find W 91st St centerline closest to (0, 0) to place the shul sidewalk accurately
        w91_closest = (0.0, 45.0)
        best_d2 = 1e18
        for pts in named_ways_by_name.get("W 91st St", []):
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                dx, dy = x2 - x1, y2 - y1
                seg2 = dx * dx + dy * dy
                if seg2 < 1e-6:
                    continue
                t = max(0.0, min(1.0, (-(x1 * dx + y1 * dy)) / seg2))
                px, py = x1 + t * dx, y1 + t * dy
                d2 = px * px + py * py
                if d2 < best_d2:
                    best_d2 = d2
                    w91_closest = (px, py)

        # Unit vector from building (0,0) toward W 91st St centerline (grid north)
        vx, vy = w91_closest[0], w91_closest[1]
        vlen = math.hypot(vx, vy) or 1.0
        ux, uy = vx / vlen, vy / vlen

        # Shul front sidewalk is ~18 ft south of W 91st St centerline (just outside 210 W 91st)
        shul_front = (w91_closest[0] - ux * 18.0, w91_closest[1] - uy * 18.0)
        if self.is_inside_building(shul_front[0], shul_front[1]):
            shul_front = (w91_closest[0] - ux * 12.0, w91_closest[1] - uy * 12.0)
        if self.is_inside_building(shul_front[0], shul_front[1]):
            shul_front = w91_closest
        self.shul_sidewalk_xy = shul_front

        raw_candidates: list[dict] = []

        def add_cand(name: str, short_name: str, x: float, y: float, kind: str):
            walk_ft = grid_walk_distance_ft(x, y, shul_front[0], shul_front[1])
            if walk_ft > 1650:
                return
            if self.is_inside_building(x, y, pad=1.0):
                return
            raw_candidates.append({
                "name": name,
                "short_name": short_name,
                "x": round(x, 1),
                "y": round(y, 1),
                "walk_ft": round(walk_ft),
                "ground_ft": round(self.local_ground_elev_ft(x, y), 1),
                "kind": kind,
            })

        # 1. Right in front of shul & directly across W 91st St
        add_cand("In front of shul (210 W 91st, S side)", "Outside Shul", shul_front[0], shul_front[1], "shul")
        add_cand("Across from shul (W 91st, N side)", "Across 91st", w91_closest[0] + ux * 18.0, w91_closest[1] + uy * 18.0, "midblock")

        # 2. All named street intersections (plus their 4 sidewalk corners!)
        inter_groups: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        for key, st_set in endpoint_streets.items():
            if len(st_set) >= 2:
                st_list = sorted(st_set)
                pts_k = endpoint_coords[key]
                kx = sum(p[0] for p in pts_k) / len(pts_k)
                ky = sum(p[1] for p in pts_k) / len(pts_k)
                if math.hypot(kx, ky) > 1550:
                    continue
                for i in range(len(st_list)):
                    for j in range(i + 1, len(st_list)):
                        s1, s2 = st_list[i], st_list[j]
                        if s1 != s2:
                            inter_groups[(s1, s2)].append((kx, ky))

        def format_inter(s1: str, s2: str) -> tuple[str, str]:
            aves = ("Broadway", "Amsterdam", "West End", "Columbus", "Riverside", "Central Park")
            s1_is_ave = any(a in s1 for a in aves)
            s2_is_ave = any(a in s2 for a in aves)
            if s2_is_ave and not s1_is_ave:
                s1, s2 = s2, s1
            full = f"{s1} & {s2}"
            short = full.replace(" St", "").replace(" Ave", "").replace("Riverside Dr", "Riverside")
            return full, short

        corner_dirs = [
            ("NE", COS_G + SIN_G, -SIN_G + COS_G),
            ("NW", -COS_G + SIN_G, SIN_G + COS_G),
            ("SE", COS_G - SIN_G, -SIN_G - COS_G),
            ("SW", -COS_G - SIN_G, SIN_G - COS_G),
        ]

        for (s1, s2), pts in inter_groups.items():
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            full_name, short_name = format_inter(s1, s2)
            if "Broadway" in full_name:
                cross = s2 if "Broadway" in s1 else s1
                add_cand(f"Broadway Mall at {cross}", f"Bway Mall/{cross.replace(' St', '')}", cx, cy, "mall")
            off = 34.0 if "Broadway" in full_name else 24.0
            for label, dx_c, dy_c in corner_dirs:
                clen = math.hypot(dx_c, dy_c)
                for scale in (1.0, 0.75, 0.5):
                    tx = cx + (dx_c / clen) * off * scale
                    ty = cy + (dy_c / clen) * off * scale
                    if not self.is_inside_building(tx, ty, pad=1.0):
                        add_cand(f"{label} corner of {full_name}", f"{short_name} ({label})", tx, ty, "corner")
                        break

        # 3. Midblock points along W 91st St (between West End & Amsterdam)
        for pts in named_ways_by_name.get("W 91st St", []):
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                seg_len = math.hypot(x2 - x1, y2 - y1)
                if seg_len < 30:
                    continue
                steps = max(1, int(seg_len // 70))
                for k in range(1, steps):
                    t = k / steps
                    mx = x1 + t * (x2 - x1)
                    my = y1 + t * (y2 - y1)
                    if math.hypot(mx, my) > 700:
                        continue
                    east_off = (mx - shul_front[0]) * COS_G - (my - shul_front[1]) * SIN_G
                    if abs(east_off) < 55:
                        continue
                    # Skip points very close to an avenue intersection (corners handle those cleanly)
                    if 105 <= east_off <= 215 or -335 <= east_off <= -230:
                        continue
                    if east_off > 200:
                        desc_full = "W 91st St (betw. Amsterdam & Columbus)"
                        desc_short = "W 91st (Amst–Columbus)"
                    elif east_off > 0:
                        desc_full = "W 91st St (betw. Shul & Amsterdam)"
                        desc_short = "W 91st (Shul–Amst)"
                    elif east_off < -320:
                        desc_full = "W 91st St (betw. Broadway & West End)"
                        desc_short = "W 91st (Bway–West End)"
                    else:
                        desc_full = "W 91st St (betw. Shul & Broadway)"
                        desc_short = "W 91st (Shul–Bway)"
                    add_cand(f"{desc_full}, N side", f"{desc_short}, N side", mx + ux * 18, my + uy * 18, "midblock")
                    add_cand(f"{desc_full}, S side", f"{desc_short}, S side", mx - ux * 18, my - uy * 18, "midblock")

        raw_candidates.sort(key=lambda c: c["walk_ft"])
        self.candidates = raw_candidates

    def check_visibility(
        self,
        ox: float,
        oy: float,
        ground_ft: float,
        az_deg: float,
        alt_deg: float,
        eye_height_ft: float = 5.5,
        max_dist_ft: float = 1800.0,
    ) -> tuple[bool, float]:
        """
        Cast a 3D ray from (ox, oy, ground_ft + eye_height_ft) toward (az_deg, alt_deg).
        Returns (is_clear, clearance_deg) where clearance_deg = alt_deg - max_obstruction_angle_deg.
        Positive clearance_deg means unobstructed.
        """
        if alt_deg <= 0.5:
            return False, alt_deg - 90.0

        az_rad = az_deg * DEG
        dx = math.sin(az_rad)
        dy = math.cos(az_rad)
        oz = ground_ft + eye_height_ft
        max_obs_angle = 0.0

        # Ray bounding box for quick culling
        rx1 = ox + dx * max_dist_ft
        ry1 = oy + dy * max_dist_ft
        r_min_x = min(ox, rx1)
        r_max_x = max(ox, rx1)
        r_min_y = min(oy, ry1)
        r_max_y = max(oy, ry1)

        for b in self.buildings:
            bx0, by0, bx1, by1 = b.bbox
            if bx1 < r_min_x or bx0 > r_max_x or by1 < r_min_y or by0 > r_max_y:
                continue
            # Quick height check: if building top <= eye level, can't block upward ray
            dh = b.top_ft - oz
            if dh <= 0:
                continue
            # Quick angular check using closest bbox corner
            cx = max(bx0, min(ox, bx1))
            cy = max(by0, min(oy, by1))
            min_d = math.hypot(cx - ox, cy - oy)
            if min_d > max_dist_ft:
                continue
            if min_d > 0.5 and math.atan2(dh, min_d) * RAD <= max_obs_angle:
                continue

            # Exact ray vs polygon edges
            best_t = None
            for ring in b.rings:
                n = len(ring)
                for i in range(n - 1):
                    x1, y1 = ring[i]
                    x2, y2 = ring[i + 1]
                    t = ray_segment_intersect(ox, oy, dx, dy, x1, y1, x2, y2)
                    if t is not None and t <= max_dist_ft:
                        if best_t is None or t < best_t:
                            best_t = t
            if best_t is not None:
                obs_angle = math.atan2(dh, best_t) * RAD
                if obs_angle > max_obs_angle:
                    max_obs_angle = obs_angle

        clearance = alt_deg - max_obs_angle
        return (clearance >= 1.5), round(clearance, 1)

    def find_nearest_spot(self, az_deg: float, alt_deg: float) -> dict | None:
        """
        Find the closest walkable public spot to 210 W 91st St with clear line of sight
        (at least 1.5° clearance above rooftops) to the moon at (az_deg, alt_deg).
        """
        if alt_deg <= 0.5:
            return None

        for c in self.candidates:
            clear, clearance = self.check_visibility(c["x"], c["y"], c["ground_ft"], az_deg, alt_deg)
            if clear:
                res = dict(c)
                res["clearance_deg"] = clearance
                return res

        return None

    def find_nearest_spot_window(self, az_alt_samples: list[tuple[float, float]]) -> dict | None:
        """
        Find the closest walkable public spot that remains clear (>= 1.5° clearance)
        across EVERY (az_deg, alt_deg) sample in the time window (e.g. 0..30 min post-tzeis).
        Returns the candidate dict with `clearance_deg` (at t+0) and `min_clearance_deg` (across window).
        """
        if not az_alt_samples or any(alt <= 0.5 for _, alt in az_alt_samples):
            return None

        # Fast-check endpoints and midpoint first, then verify every sample
        n = len(az_alt_samples)
        fast_indices = sorted({0, n // 2, n - 1})

        for c in self.candidates:
            cx, cy, cg = c["x"], c["y"], c["ground_ft"]
            ok = True
            for i in fast_indices:
                az, alt = az_alt_samples[i]
                clear, _ = self.check_visibility(cx, cy, cg, az, alt)
                if not clear:
                    ok = False
                    break
            if not ok:
                continue

            min_clr = 999.0
            t0_clr = 0.0
            for i, (az, alt) in enumerate(az_alt_samples):
                clear, clr = self.check_visibility(cx, cy, cg, az, alt)
                if i == 0:
                    t0_clr = clr
                if clr < min_clr:
                    min_clr = clr
                if not clear:
                    ok = False
                    break
            if ok:
                res = dict(c)
                res["clearance_deg"] = t0_clr
                res["min_clearance_deg"] = min_clr
                return res

        return None


if __name__ == "__main__":
    vm = VisibilityModel()
    print(f"Loaded {len(vm.buildings)} buildings, {len(vm.streets)} street segments, {len(vm.candidates)} candidate spots.")
    print("First 10 closest candidate spots:")
    for c in vm.candidates[:10]:
        print(f"  {c['walk_ft']:4d} ft | {c['name']} ({c['x']}, {c['y']})")
    # Quick test: Moon in WSW at 25° altitude
    spot = vm.find_nearest_spot(az_deg=240.0, alt_deg=25.0)
    print("\nTest moon at az=240° (WSW), alt=25°:")
    print("  Nearest clear spot:", spot)
    spot_low = vm.find_nearest_spot(az_deg=250.0, alt_deg=12.0)
    print("Test moon at az=250° (WSW), alt=12°:")
    print("  Nearest clear spot:", spot_low)

#!/usr/bin/env python3
"""Fetch and cache NYC 3D Building Footprints, OSM street/intersection data, and JPL ephemeris."""

import json
import os
import urllib.parse
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 210 West 91st Street, New York, NY 10024 (approx center)
SHUL_LAT = 40.79104
SHUL_LON = -73.97330

# Bounding box (~600m radius in every direction: ~W 85th to W 97th, Riverside Dr to Central Park West)
MIN_LAT = 40.7855
MAX_LAT = 40.7965
MIN_LON = -73.9815
MAX_LON = -73.9650


def fetch_json(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "LevanahNYC/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_nyc_buildings():
    out_path = os.path.join(DATA_DIR, "nyc_buildings.geojson")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        print(f"Already have {out_path}")
        return

    print("Fetching NYC Open Data Building Footprints (5zhs-2jue)...")
    # Socrata SoQL within_box(the_geom, max_lat, min_lon, min_lat, max_lon)
    # Note: dataset 5zhs-2jue uses 'the_geom' or 'shape' - let's check schema first
    meta = fetch_json("https://data.cityofnewyork.us/resource/5zhs-2jue.json?$limit=1")
    geom_col = "the_geom" if "the_geom" in meta[0] else ("shape" if "shape" in meta[0] else None)
    print(f"Detected geometry column: {geom_col}, sample keys: {list(meta[0].keys())}")

    where_clause = f"within_box({geom_col}, {MAX_LAT}, {MIN_LON}, {MIN_LAT}, {MAX_LON})"
    params = urllib.parse.urlencode({
        "$where": where_clause,
        "$limit": 10000,
    })
    url = f"https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?{params}"
    geojson = fetch_json(url)
    features = geojson.get("features", [])
    print(f"Fetched {len(features)} building footprints.")
    with open(out_path, "w") as f:
        json.dump(geojson, f)


def fetch_shul_geocode():
    out_path = os.path.join(DATA_DIR, "shul_geocode.json")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
        print(f"Already have {out_path}")
        return
    print("Geocoding 210 West 91st Street via NYC Planning Labs GeoSearch...")
    url = "https://geosearch.planninglabs.nyc/v2/search?" + urllib.parse.urlencode({
        "text": "210 West 91st Street, Manhattan, NY"
    })
    geo = fetch_json(url)
    with open(out_path, "w") as f:
        json.dump(geo, f, indent=2)
    if geo.get("features"):
        coords = geo["features"][0]["geometry"]["coordinates"]
        label = geo["features"][0]["properties"].get("label")
        print(f"Geocoded: {label} -> lon={coords[0]}, lat={coords[1]}")


def fetch_nyc_streets():
    out_path = os.path.join(DATA_DIR, "nyc_streets.geojson")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        print(f"Already have {out_path}")
        return

    print("Fetching NYC Street Centerline (inkn-q76z)...")
    meta = fetch_json("https://data.cityofnewyork.us/resource/inkn-q76z.json?$limit=1")
    geom_col = "the_geom" if "the_geom" in meta[0] else ("shape" if "shape" in meta[0] else None)
    print(f"Detected geometry column: {geom_col}, sample keys: {list(meta[0].keys())}")

    where_clause = f"within_box({geom_col}, {MAX_LAT}, {MIN_LON}, {MIN_LAT}, {MAX_LON})"
    params = urllib.parse.urlencode({
        "$where": where_clause,
        "$limit": 5000,
    })
    url = f"https://data.cityofnewyork.us/resource/inkn-q76z.geojson?{params}"
    geojson = fetch_json(url)
    print(f"Fetched {len(geojson.get('features', []))} street segments.")
    with open(out_path, "w") as f:
        json.dump(geojson, f)


if __name__ == "__main__":
    fetch_nyc_buildings()
    fetch_shul_geocode()
    fetch_nyc_streets()
    print("All data cached in", DATA_DIR)

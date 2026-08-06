"""
routing.py — Real driving distance + route geometry.

Primary: Mapbox Directions (free tier, chỉ cần token).
Fallback: OSRM (free, không cần key) khi thiếu token hoặc Mapbox hỏng.
Returns {distanceKm, durationMin, geometry: [[lat,lng],...]} for Leaflet, or None.
"""
import os

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"


def _mapbox_route(lat1, lng1, lat2, lng2):
    """Mapbox Directions — GeoJSON geometry -> [[lat,lng],...] like OSRM."""
    if not MAPBOX_TOKEN:
        return None
    try:
        r = requests.get(
            f"{MAPBOX_DIRECTIONS_URL}/{lng1},{lat1};{lng2},{lat2}",
            params={"access_token": MAPBOX_TOKEN, "geometries": "geojson", "overview": "full"},
            timeout=12,
        )
        j = r.json()
        routes = j.get("routes") or []
        if not routes:
            return None
        rt = routes[0]
        coords = [[c[1], c[0]] for c in rt["geometry"]["coordinates"]]  # [lng,lat] -> [lat,lng]
        return {
            "distanceKm": round(rt["distance"] / 1000, 1),
            "durationMin": round(rt["duration"] / 60),
            "geometry": coords,
        }
    except Exception:  # noqa: BLE001
        return None



def _osrm_route(lat1, lng1, lat2, lng2):
    try:
        url = (f"{OSRM_URL}/{lng1},{lat1};{lng2},{lat2}"
               "?overview=full&geometries=geojson")
        r = requests.get(url, timeout=12)
        j = r.json()
        if j.get("code") != "Ok" or not j.get("routes"):
            return None
        rt = j["routes"][0]
        coords = [[c[1], c[0]] for c in rt["geometry"]["coordinates"]]  # -> [lat, lng]
        return {
            "distanceKm": round(rt["distance"] / 1000, 1),
            "durationMin": round(rt["duration"] / 60),
            "geometry": coords,
        }
    except Exception:  # noqa: BLE001
        return None


def road_route(lat1, lng1, lat2, lng2):
    """Mapbox → OSRM (nhà cung cấp đầu tiên trả được kết quả)."""
    if MAPBOX_TOKEN:
        m = _mapbox_route(lat1, lng1, lat2, lng2)
        if m:
            return m
    return _osrm_route(lat1, lng1, lat2, lng2)

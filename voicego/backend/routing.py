"""
routing.py — Real driving distance + route geometry.

Primary: Google Routes API (accurate, needs GOOGLE_MAPS_API_KEY).
Fallback: OSRM (free, no key) when no key or Google fails.
Returns {distanceKm, durationMin, geometry: [[lat,lng],...]} for Leaflet, or None.
"""
import os

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
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


def _google_route(lat1, lng1, lat2, lng2):
    """Google Routes API (New). GeoJSON polyline -> [[lat,lng],...] like OSRM."""
    if not GOOGLE_MAPS_API_KEY:
        return None
    body = {
        "origin": {"location": {"latLng": {"latitude": lat1, "longitude": lng1}}},
        "destination": {"location": {"latLng": {"latitude": lat2, "longitude": lng2}}},
        "travelMode": "DRIVE",
        "polylineEncoding": "GEO_JSON_LINESTRING",
    }
    try:
        r = requests.post(
            ROUTES_URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.geoJsonLinestring",
            },
            timeout=12,
        )
        j = r.json()
        routes = j.get("routes") or []
        if not routes:
            return None
        rt = routes[0]
        dist_m = rt.get("distanceMeters")
        dur = str(rt.get("duration", "0s")).rstrip("s")  # "1234s" -> "1234"
        coords_geojson = (((rt.get("polyline") or {}).get("geoJsonLinestring") or {}).get("coordinates")) or []
        coords = [[c[1], c[0]] for c in coords_geojson]  # [lng,lat] -> [lat,lng]
        if dist_m is None:
            return None
        return {
            "distanceKm": round(dist_m / 1000, 1),
            "durationMin": round((float(dur) if dur else 0) / 60),
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
    """Google Routes → Mapbox → OSRM (first configured provider that succeeds)."""
    if GOOGLE_MAPS_API_KEY:
        g = _google_route(lat1, lng1, lat2, lng2)
        if g:
            return g
    if MAPBOX_TOKEN:
        m = _mapbox_route(lat1, lng1, lat2, lng2)
        if m:
            return m
    return _osrm_route(lat1, lng1, lat2, lng2)

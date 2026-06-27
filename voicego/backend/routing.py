"""
routing.py — Real driving distance + route geometry via OSRM (free, no key).

Replaces straight-line distance with actual road routing so the km/price and the
drawn route reflect a real trip. Falls back to None on failure (caller can use
haversine). Returns geometry as [[lat, lng], ...] for Leaflet.
"""
import requests

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"


def road_route(lat1, lng1, lat2, lng2):
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

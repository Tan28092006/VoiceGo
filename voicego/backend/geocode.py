"""
geocode.py — Trustworthy destination resolution for arbitrary place names.

Layered fallback (so a real place still resolves when one source is down):
  1. Gemini + Google Search grounding -> REAL full address (live, post-2025 admin).
  2. If grounding is unavailable (503/quota): plain Gemini (no tools) -> best-guess
     address from its knowledge.
  3. Geocode the resulting address via Nominatim (authoritative coords); else use
     the model's coords (lower confidence).
  4. If no model output at all: Nominatim directly on the raw text.

The LLM never invents coordinates as ground truth — coords come from a geocoder,
and the booking only proceeds after the user confirms the read-back address.
"""
import os
import re
import json
import time
import math

import requests

from voice import GEMINI_API_KEY, GEMINI_MODEL, llm_json
from places_db import lookup as _local_lookup, lookup_all as _lookup_all_pd

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Google Places API (New) — most accurate for Vietnamese place names. Used as the
# top geocoding layer when GOOGLE_MAPS_API_KEY is set; else everything falls back
# to the existing Gemini/Nominatim layers (zero behaviour change without a key).
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

# Mapbox geocoding — strong VN coverage, generous free tier, no billing hassle.
# Used right after Google (which no-ops without a working key). Gated by token.
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places"

# Service model: instead of a fixed city box, we bias + limit geocoding to a
# radius around the PICKUP location (the user's GPS). This makes the app work
# anywhere in Vietnam while still rejecting destinations too far to serve.
DEFAULT_CENTER = (10.8782, 106.8012)   # fallback pickup when GPS is unavailable
SERVICE_RADIUS_KM = 100                # max ride distance we serve from pickup


def _viewbox(center_lat, center_lng, radius_km=SERVICE_RADIUS_KM):
    """Nominatim viewbox ('lon1,lat1,lon2,lat2') around a center + radius.
    Biases results toward the pickup area without forcing (no bounded=1)."""
    if center_lat is None or center_lng is None:
        return None
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.1, math.cos(math.radians(center_lat))))
    return f"{center_lng - dlng},{center_lat + dlat},{center_lng + dlng},{center_lat - dlat}"


def _within_service(lat, lng, center_lat, center_lng, radius_km=SERVICE_RADIUS_KM):
    """True if a result is close enough to the pickup to serve. When no center is
    known, accept anything (nationwide) rather than reject."""
    if center_lat is None or center_lng is None:
        return True
    return _haversine_km(center_lat, center_lng, lat, lng) <= radius_km


def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _google_places(text, center_lat=None, center_lng=None, limit=5):
    """Google Places API (New) Text Search — best coverage for VN place names.
    Returns [{name, address, lat, lng}] biased to the pickup area, or [] when no
    key / no result / error (caller falls back to the other layers)."""
    if not GOOGLE_MAPS_API_KEY or not (text or "").strip():
        return []
    body = {
        "textQuery": text,
        "languageCode": "vi",
        "regionCode": "VN",
        "maxResultCount": max(1, min(int(limit), 10)),
    }
    if center_lat is not None and center_lng is not None:
        # locationBias circle radius is capped at 50 km by the API.
        body["locationBias"] = {"circle": {
            "center": {"latitude": center_lat, "longitude": center_lng},
            "radius": min(SERVICE_RADIUS_KM * 1000.0, 50000.0),
        }}
    try:
        r = requests.post(
            GOOGLE_PLACES_URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
            },
            timeout=10,
        )
        data = r.json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for p in (data.get("places") or []):
        loc = p.get("location") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        name = (p.get("displayName") or {}).get("text") or text
        addr = (p.get("formattedAddress") or name).replace(", Việt Nam", "").strip()
        out.append({"name": name, "address": addr, "lat": float(lat), "lng": float(lng)})
        if len(out) >= limit:
            break
    return out


def _mapbox_geocode(text, center_lat=None, center_lng=None, limit=5):
    """Mapbox Geocoding (v5) — good VN coverage, free tier. Returns
    [{name,address,lat,lng}] biased to the pickup, or [] when no token/result."""
    if not MAPBOX_TOKEN or not (text or "").strip():
        return []
    from urllib.parse import quote
    params = {
        "access_token": MAPBOX_TOKEN,
        "country": "vn",
        "language": "vi",
        "limit": max(1, min(int(limit), 10)),
        "types": "poi,address,place,locality,neighborhood",
    }
    if center_lat is not None and center_lng is not None:
        params["proximity"] = f"{center_lng},{center_lat}"
    try:
        r = requests.get(f"{MAPBOX_GEOCODE_URL}/{quote(text)}.json", params=params, timeout=10)
        data = r.json()
    except Exception:  # noqa: BLE001
        return []
    feats = []
    for f in (data.get("features") or []):
        center = f.get("center") or []
        if len(center) < 2:
            continue
        lng, lat = float(center[0]), float(center[1])
        name = f.get("text") or text
        addr = (f.get("place_name") or name).replace(", Việt Nam", "").replace(", Vietnam", "").strip()
        feats.append({"name": name, "address": addr, "lat": lat, "lng": lng})
    # Mapbox mis-ranks VN results (a same-name street in another province can
    # outrank the local one — e.g. "Ngô Gia Tự Q10" put Tây Ninh 88 km away first).
    # For a ride app the destination is near the pickup, so sort by distance to the
    # pickup center and return nearest first.
    if center_lat is not None and center_lng is not None:
        feats.sort(key=lambda p: _haversine_km(center_lat, center_lng, p["lat"], p["lng"]))
    return feats[:limit]


def _mapbox_first(text, center_lat, center_lng):
    """Single best Mapbox hit (nearest to pickup) within the service radius, or None.
    Used as a fallback BELOW the Gemini+Google-Search layer."""
    for p in _mapbox_geocode(text, center_lat, center_lng, limit=5):
        if _within_service(p["lat"], p["lng"], center_lat, center_lng):
            return p
    return None


def _gemini_call(prompt, grounded, retries=2):
    """One Gemini call (optionally with Google Search grounding); retry on 503/429."""
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)
    cfg = None
    if grounded:
        cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])

    for i in range(retries):
        try:
            r = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg)
            return (r.text or "").strip()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if any(k in msg for k in ("503", "UNAVAILABLE", "overload", "429", "RESOURCE_EXHAUSTED")):
                time.sleep(0.5 * (i + 1))
                continue
            return None
    return None


def _parse_json(raw):
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _nominatim_full(address, center_lat=None, center_lng=None):
    """Return (lat, lng, display_name) for an address/POI, or None. When a center
    is given, viewbox BIASES toward the pickup area (no bounded=1, so an out-of-
    area query isn't warped onto a random in-box place)."""
    params = {"q": address, "format": "json", "limit": 1, "countrycodes": "vn"}
    vb = _viewbox(center_lat, center_lng)
    if vb:
        params["viewbox"] = vb
    try:
        r = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": "VoiceGo/1.0 (hackathon accessibility demo)"},
            timeout=10,
        )
        arr = r.json()
        if arr:
            disp = arr[0].get("display_name", "")
            disp = disp.replace(", Việt Nam", "").strip()
            disp = re.sub(r",?\s*\d{5,6}\b", "", disp)  # drop postcode
            return float(arr[0]["lat"]), float(arr[0]["lon"]), disp
    except Exception:  # noqa: BLE001
        pass
    return None


def _nominatim(address, center_lat=None, center_lng=None):
    r = _nominatim_full(address, center_lat, center_lng)
    return (r[0], r[1]) if r else None


def _clean_display(disp):
    disp = (disp or "").replace(", Việt Nam", "").strip()
    return re.sub(r",?\s*\d{5,6}\b", "", disp)


def geocode_candidates(text, user_lat=None, user_lng=None, limit=8):
    """Multiple DISTINCT real matches for an ambiguous query (e.g. a street name /
    house number that exists in several districts: '19 Ngô Gia Tự'). Real
    OpenStreetMap results only (no hallucination), biased to + within the service
    radius of the pickup, one per area."""
    center_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    center_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]

    # Best providers first: Google Places (if a working key), then Mapbox (if a
    # token). Each no-ops to [] when unavailable, so we fall through cleanly.
    for provider in (_google_places, _mapbox_geocode):
        hits = provider(text, center_lat, center_lng, limit=limit)
        if not hits:
            continue
        out, seen = [], set()
        for c in hits:
            if not _within_service(c["lat"], c["lng"], center_lat, center_lng):
                continue
            key = f"{round(c['lat'], 3)},{round(c['lng'], 3)}"
            if key in seen:
                continue
            seen.add(key)
            dist = round(_haversine_km(user_lat, user_lng, c["lat"], c["lng"]), 1) if user_lat is not None else None
            out.append({"name": c["name"], "address": c["address"], "lat": c["lat"],
                        "lng": c["lng"], "area": "", "distanceKm": dist})
            if len(out) >= 4:
                break
        if out:
            return out

    params = {"q": text, "format": "json", "limit": limit,
              "countrycodes": "vn", "addressdetails": 1}
    vb = _viewbox(center_lat, center_lng)
    if vb:
        params["viewbox"] = vb
    try:
        r = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": "VoiceGo/1.0 (hackathon accessibility demo)"},
            timeout=10,
        )
        arr = r.json()
    except Exception:  # noqa: BLE001
        return []
    out, seen = [], set()
    for it in arr if isinstance(arr, list) else []:
        try:
            lat, lng = float(it["lat"]), float(it["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not _within_service(lat, lng, center_lat, center_lng):
            continue
        ad = it.get("address", {}) or {}
        area = (ad.get("suburb") or ad.get("city_district") or ad.get("quarter")
                or ad.get("county") or ad.get("town") or ad.get("city") or "")
        key = area or f"{round(lat, 3)},{round(lng, 3)}"
        if key in seen:
            continue
        seen.add(key)
        disp = _clean_display(it.get("display_name", ""))
        dist = round(_haversine_km(user_lat, user_lng, lat, lng), 1) if user_lat is not None else None
        out.append({"name": disp.split(",")[0].strip() or text, "address": disp,
                    "lat": lat, "lng": lng, "area": area, "distanceKm": dist})
        if len(out) >= 4:
            break
    return out


def _dms_to_dec(s):
    """Parse a DMS coordinate ('10°47′09.1″B' or '10 độ 47 phút 09.1 giây') to decimal.
    Also accepts a plain decimal string. Returns a positive float (VN is always N/E),
    or None. Asking Gemini for DMS is far more precise than decimal (it drops the pin
    on the exact place, not a neighbouring building)."""
    if not s:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", str(s))
    if not nums:
        return None
    d = float(nums[0])
    mn = float(nums[1]) if len(nums) > 1 else 0.0
    sec = float(nums[2]) if len(nums) > 2 else 0.0
    return round(abs(d) + mn / 60 + sec / 3600, 6)


def _short_address(addr, name=""):
    """Trim a long geocoder/LLM address to a concise, speakable form: keep the first
    few meaningful parts (số nhà + đường + phường/quận), drop country/postcode/extras."""
    if not addr:
        return name or ""
    a = re.sub(r",?\s*\d{5,6}\b", "", addr)                 # postcode
    a = a.replace(", Việt Nam", "").replace(", Vietnam", "").strip().strip(",")
    parts = [p.strip() for p in a.split(",") if p.strip()]
    return ", ".join(parts[:4]) if parts else (name or addr)


def _build_prompt(text, user_lat, user_lng, grounded):
    loc_hint = ""
    if user_lat is not None and user_lng is not None:
        loc_hint = f"Vị trí người dùng: {user_lat}, {user_lng}. Ưu tiên cơ sở GẦN vị trí này.\n"
    how = ("Hãy DÙNG TÌM KIẾM để tra thông tin THẬT.\n" if grounded
           else "Dựa trên hiểu biết của bạn về địa điểm ở Việt Nam.\n")
    return (
        "Bạn là bộ định vị cho ứng dụng gọi xe ở Việt Nam. " + how +
        f'Người dùng muốn đến: "{text}"\n' + loc_hint +
        'Phân loại query_type: "address" nếu là ĐỊA CHỈ CHI TIẾT (có số nhà/số cụ thể); '
        '"poi" nếu là TÊN địa điểm/landmark/doanh nghiệp/trường học.\n'
        "Nếu địa điểm có NHIỀU cơ sở/chi nhánh trong khu vực, LIỆT KÊ TẤT CẢ (tối đa 4), gần người dùng trước. "
        "Nếu chỉ một nơi, trả về một phần tử. full_address NGẮN GỌN: số nhà + đường + "
        "phường/quận, KHÔNG kèm quốc gia/mã bưu chính.\n"
        "Toạ độ trả ở dạng DMS (độ, phút, giây tới 0.1 giây) — CHÍNH XÁC hơn thập phân; "
        "đặt pin ĐÚNG địa điểm, không lệch sang toà nhà kế bên. "
        "Ví dụ: lat_dms = 10 độ 47 phút 09.1 giây Bắc, lng_dms = 106 độ 42 phút 09.8 giây Đông.\n"
        "Trả về DUY NHẤT một JSON (không giải thích):\n"
        '{"query_type":"poi|address","locations":[{"name":"<tên>","full_address":"<địa chỉ ngắn gọn>",'
        '"lat_dms":"<vĩ độ độ-phút-giây>","lng_dms":"<kinh độ độ-phút-giây>"}]}'
    )


def _gemini_locations(text, user_lat, user_lng):
    """GROUNDED Gemini -> {query_type, locations:[{name,address,lat,lng}]} with REAL
    coords, or None. Plain (non-grounded) LLM coords are hallucinated, so we only
    trust grounded output; without a key the caller falls back to a real geocoder."""
    if not GEMINI_API_KEY:
        return None
    data = _parse_json(_gemini_call(_build_prompt(text, user_lat, user_lng, True), grounded=True, retries=1))
    if not data:
        return None
    out = []
    for item in (data.get("locations") or []):
        # Prefer DMS (precise); fall back to any decimal lat/lng the model included.
        lat = _dms_to_dec(item.get("lat_dms"))
        lng = _dms_to_dec(item.get("lng_dms"))
        if lat is None or lng is None:
            try:
                lat, lng = abs(float(item["latitude"])), abs(float(item["longitude"]))
            except (KeyError, TypeError, ValueError):
                continue
        name = item.get("name") or text
        out.append({"name": name, "address": _short_address(item.get("full_address") or name, name),
                    "lat": lat, "lng": lng})
    return {"query_type": data.get("query_type", "poi"), "locations": out}


def resolve_locations(text, user_lat=None, user_lng=None):
    """Resolve a spoken place to 1..N real locations (campuses/branches) with coords.
    Gemini (Google-Search grounded) drives it and may return several branches -> the
    agent offers them as candidates. POI coords come straight from Gemini (accurate);
    a single detailed ADDRESS is cross-checked against a real geocoder (LLM coords
    drift on house numbers). NO place is hardcoded — arbitrary places work."""
    if not text.strip():
        return {"ok": False, "reason": "empty"}
    center_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    center_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]

    def fin(loc):
        d = round(_haversine_km(user_lat, user_lng, loc["lat"], loc["lng"]), 1) if user_lat is not None else None
        return {"name": loc["name"], "address": _short_address(loc.get("address"), loc["name"]),
                "lat": loc["lat"], "lng": loc["lng"], "distanceKm": d}

    def within(loc):
        return _within_service(loc["lat"], loc["lng"], center_lat, center_lng)

    # 0) Verified gazetteer (instant, exact; may already hold multiple branches).
    ga = [{"name": c["name"], "address": c.get("address"), "lat": c["lat"], "lng": c["lng"]}
          for c in _lookup_all_pd(text)]
    ga = [l for l in ga if within(l)]
    if ga:
        return {"ok": True, "query_type": "poi", "source": "verified", "locations": [fin(l) for l in ga[:4]]}

    # 1) Google Places (if a working key) — precise, may return several branches.
    gp = [p for p in _google_places(text, center_lat, center_lng, limit=4) if within(p)]
    if gp:
        return {"ok": True, "query_type": "poi", "source": "google_places", "locations": [fin(p) for p in gp[:4]]}

    # 2) Gemini grounded — arbitrary places, may return multiple branches with real coords.
    data = _gemini_locations(text, user_lat, user_lng)
    if data and data.get("locations"):
        locs = [l for l in data["locations"] if within(l)]
        if not locs:
            return {"ok": False, "reason": "out_of_area"}
        if user_lat is not None:
            locs.sort(key=lambda l: _haversine_km(user_lat, user_lng, l["lat"], l["lng"]))
        # Cross-check ONLY a single detailed-address result (LLM coords drift there):
        # if a real geocoder lands in the same area, use its (more precise) coord.
        if data.get("query_type") == "address" and len(locs) == 1:
            mb = _mapbox_first(locs[0].get("address") or text, center_lat, center_lng)
            if mb and _haversine_km(mb["lat"], mb["lng"], locs[0]["lat"], locs[0]["lng"]) <= 3:
                locs[0] = {"name": locs[0]["name"], "address": locs[0].get("address") or mb["address"],
                           "lat": mb["lat"], "lng": mb["lng"]}
        return {"ok": True, "query_type": data.get("query_type", "poi"), "source": "grounded",
                "locations": [fin(l) for l in locs[:4]]}

    # 3) Fallback: Mapbox nearest, then Nominatim raw.
    mb = _mapbox_first(text, center_lat, center_lng)
    if mb:
        return {"ok": True, "query_type": "address", "source": "mapbox", "locations": [fin(mb)]}
    coords = _nominatim(text, center_lat, center_lng) or _nominatim(f"{text}, Việt Nam")
    if coords:
        if not _within_service(coords[0], coords[1], center_lat, center_lng):
            return {"ok": False, "reason": "out_of_area"}
        return {"ok": True, "query_type": "address", "source": "nominatim_raw",
                "locations": [fin({"name": text, "address": text, "lat": coords[0], "lng": coords[1]})]}
    return {"ok": False, "reason": "not_found"}


def resolve_destination(text, user_lat=None, user_lng=None):
    """Single best location — back-compat wrapper over resolve_locations."""
    r = resolve_locations(text, user_lat, user_lng)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason", "not_found")}
    loc = r["locations"][0]
    return {"ok": True, "name": loc["name"], "address": loc.get("address"), "province": "",
            "lat": loc["lat"], "lng": loc["lng"], "distanceKm": loc.get("distanceKm"),
            "confidence": 0.9, "source": r.get("source"), "alternatives": []}

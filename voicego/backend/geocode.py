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
import re
import json
import time
import math

import requests

from voice import GEMINI_API_KEY, GEMINI_MODEL, groq_json
from places_db import lookup as _local_lookup

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

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


def _build_prompt(text, user_lat, user_lng, grounded):
    loc_hint = ""
    if user_lat is not None and user_lng is not None:
        loc_hint = (
            f"Vị trí người dùng: {user_lat}, {user_lng}. "
            "Nếu địa điểm có NHIỀU chi nhánh/cơ sở, ưu tiên cơ sở GẦN vị trí này nhất, "
            "và liệt kê các cơ sở khác vào 'alternatives'.\n"
        )
    how = ("Hãy DÙNG TÌM KIẾM để tra địa chỉ THẬT.\n" if grounded
           else "Dựa trên hiểu biết của bạn về địa điểm ở Việt Nam, đưa địa chỉ đầy đủ nhất có thể.\n")
    return (
        "Bạn là trợ lý định vị cho ứng dụng gọi xe. " + how +
        f'Người dùng muốn đến: "{text}"\n' + loc_hint +
        "Trả về DUY NHẤT một JSON (không giải thích):\n"
        '{"name":"<tên địa điểm>","full_address":"<địa chỉ đầy đủ kèm phường/quận/tỉnh>",'
        '"province":"<tỉnh/thành>","latitude":<số thập phân hoặc null>,'
        '"longitude":<số thập phân hoặc null>,"confidence":<0..1>,'
        '"alternatives":["<chi nhánh khác nếu có>"]}'
    )


def resolve_destination(text, user_lat=None, user_lng=None):
    """Resolve a spoken place name to a real address + coordinates (layered fallback).
    Results are biased to + limited within the service radius of the pickup
    (user_lat/user_lng), falling back to DEFAULT_CENTER when GPS is unavailable."""
    if not text.strip():
        return {"ok": False, "reason": "empty"}

    center_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    center_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]

    # 0) Local gazetteer FIRST: verified landmarks resolve instantly with trusted
    #    coords — no network call, no rate-limit, and it fixes places public
    #    geocoders get wrong (Landmark 81, Nhà thờ Đức Bà, Bách Khoa, ...).
    hit = _local_lookup(text)
    if hit:
        dist = round(_haversine_km(user_lat, user_lng, hit["lat"], hit["lng"]), 1) if user_lat is not None else None
        return {"ok": True, "name": hit["name"], "address": hit["address"],
                "province": hit.get("province", ""), "lat": hit["lat"], "lng": hit["lng"],
                "distanceKm": dist, "confidence": 1.0, "source": "verified", "alternatives": []}

    # 1) grounded Gemini (best, real search) if available; 2) Groq plain (fast, no limit).
    g = None
    via = "grounded"
    if GEMINI_API_KEY:
        g = _parse_json(_gemini_call(_build_prompt(text, user_lat, user_lng, True), grounded=True, retries=1))
    if not g:
        g = _parse_json(groq_json(_build_prompt(text, user_lat, user_lng, False)))
        via = "groq"

    # 3) No model output at all -> Nominatim directly on the raw text (biased to pickup).
    if not g:
        coords = _nominatim(text, center_lat, center_lng) or _nominatim(f"{text}, Việt Nam")
        if not coords:
            return {"ok": False, "reason": "not_found"}
        lat, lng = coords
        if not _within_service(lat, lng, center_lat, center_lng):
            return {"ok": False, "reason": "out_of_area"}  # too far from pickup
        dist = round(_haversine_km(user_lat, user_lng, lat, lng), 1) if user_lat is not None else None
        return {"ok": True, "name": text, "address": text, "province": "", "lat": lat, "lng": lng,
                "distanceKm": dist, "confidence": 0.4, "source": "nominatim_raw", "alternatives": []}

    address = g.get("full_address") or text
    name = g.get("name") or text
    g_lat, g_lng = g.get("latitude"), g.get("longitude")

    # Coords priority: a real POI lookup by NAME / raw text beats an LLM-guessed
    # address (which can be hallucinated — e.g. 8b put "Vạn Hạnh Mall" in Quận 5).
    # The LLM address is tried only after, and the model's own coords last.
    coords = None
    source = "nominatim"
    for cand in (name, text, address):
        if cand and cand.strip():
            hit = _nominatim_full(cand, center_lat, center_lng)
            if hit:
                coords = (hit[0], hit[1])
                if hit[2]:
                    address = hit[2]  # use Nominatim's REAL address (matches coords)
                    name = hit[2].split(",")[0].strip() or name  # keep name == coords
                break
    # Only trust model coords from GROUNDED search (real). NEVER use plain-Groq
    # coords — they are hallucinated (audit showed 10-21km errors). If Nominatim
    # can't place it, return not_found so the agent asks again (safer than wrong).
    if not coords and via == "grounded" and isinstance(g_lat, (int, float)) and isinstance(g_lng, (int, float)):
        coords = (float(g_lat), float(g_lng))
        source = "grounded"
    if not coords:
        return {"ok": False, "reason": "not_found", "name": name, "address": address}

    lat, lng = coords
    if not _within_service(lat, lng, center_lat, center_lng):   # too far from pickup to serve
        return {"ok": False, "reason": "out_of_area", "name": name, "address": address}
    confidence = float(g.get("confidence", 0.6))
    if source == "nominatim" and isinstance(g_lat, (int, float)) and isinstance(g_lng, (int, float)):
        if _haversine_km(lat, lng, float(g_lat), float(g_lng)) > 8:
            confidence = min(confidence, 0.5)

    distance_km = round(_haversine_km(user_lat, user_lng, lat, lng), 1) if user_lat is not None else None

    return {
        "ok": True, "name": name, "address": address, "province": g.get("province"),
        "lat": lat, "lng": lng, "distanceKm": distance_km, "confidence": confidence,
        "source": source, "alternatives": g.get("alternatives", []),
    }

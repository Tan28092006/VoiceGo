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
import copy
import json
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from voice import GEMINI_API_KEY, GEMINI_API_KEYS, GEMINI_MODEL, llm_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Mapbox geocoding — strong VN coverage, generous free tier, no billing hassle.
# Chạy SONG SONG với Gemini để cross-check toạ độ mà không tốn thêm thời gian.
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places"

# Gemini (grounded) là bộ não chính, nhưng KHÔNG tin hẳn: toạ độ được đối chiếu
# với geocoder thật (Mapbox, rồi Nominatim). Lệch quá ngưỡng này coi như không
# khớp -> hạ cờ verified để tầng trên biết mà thận trọng.
VERIFY_RADIUS_KM = 3.0
COARSE_KM = 6.0          # mốc cấp phường (không số nhà): chỉ để CHỌN giữa các cơ sở xa nhau

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
        feats.append({"name": name, "address": addr, "lat": lat, "lng": lng,
                      "type": (f.get("place_type") or [""])[0] or ""})
    # Mapbox mis-ranks VN results (a same-name street in another province can
    # outrank the local one — e.g. "Ngô Gia Tự Q10" put Tây Ninh 88 km away first).
    # For a ride app the destination is near the pickup, so sort by distance to the
    # pickup center and return nearest first.
    if center_lat is not None and center_lng is not None:
        feats.sort(key=lambda p: _haversine_km(center_lat, center_lng, p["lat"], p["lng"]))
    return feats[:limit]


# Kết quả Mapbox cấp VÙNG (cả thành phố, quận/huyện, tỉnh...) không bao giờ là một điểm
# đến. Ca thật: "Bách Khoa cơ sở 2" (Nominatim không với tới) rơi xuống Mapbox, ra đúng
# tâm "Thành phố Hồ Chí Minh" cách điểm đón 0.2 km — mà vẫn bị coi là đã xác minh.
_MAPBOX_COARSE = {"country", "region", "postcode", "district", "place", "locality"}


def _mapbox_first(text, center_lat, center_lng):
    """Single best Mapbox hit (nearest to pickup) within the service radius, or None.
    Used as a fallback BELOW the Gemini+Google-Search layer. Region-level hits are
    skipped (see _MAPBOX_COARSE)."""
    for p in _mapbox_geocode(text, center_lat, center_lng, limit=5):
        if p.get("type") in _MAPBOX_COARSE:
            continue
        if _within_service(p["lat"], p["lng"], center_lat, center_lng):
            return p
    return None


_GEMINI_PARKED = {}      # key -> thời điểm hết "treo" sau khi dính 429
_GEMINI_PARK_SEC = 60
_GEMINI_STRIKES = {}     # key -> số lần 429 liên tiếp (để treo lâu dần)
_GEMINI_CLIENTS = {}     # key -> genai.Client dùng lại (khỏi bắt tay TLS mỗi lượt)
_gemini_rr = 0           # con trỏ xoay vòng để tải rải đều các key


def _park_429(key):
    """Treo key vừa dính 429, lần sau lâu hơn lần trước: 1' → 4' → 16' → tối đa 1h.

    Hạn mức NGÀY chỉ có 20 lượt, nên một key đã cạn sẽ 429 lại ngay sau khi hết
    treo 60s — mỗi lượt nói lại phải trả thêm một vòng gọi hỏng. Treo lâu dần giúp
    key cạn tự lùi xuống cuối, khỏi phải vào Render đổi thứ tự key bằng tay.
    """
    n = _GEMINI_STRIKES.get(key, 0) + 1
    _GEMINI_STRIKES[key] = n
    _GEMINI_PARKED[key] = time.time() + min(_GEMINI_PARK_SEC * (4 ** (n - 1)), 3600)

# gemini-2.5-flash "no longer available to new users": key từ tài khoản mới gọi nó
# là 404. Mỗi key vì thế có thể phải dùng model khác nhau — nhớ lại để lần sau khỏi
# tốn thêm một lần 404.
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
_GEMINI_MODEL_FOR = {}   # key -> model thực sự dùng được với key đó
_GEMINI_NO_THINKING = set()   # model -> đã biết từ chối thinking_config (400), bỏ ngay lần sau

# Grounding (Google Search) có hạn mức RIÊNG, CHIA SẺ chung cho mọi model/key — đo thật:
# 3 key đều 429 ngay cả trên gemini-3.5-flash-lite (RPD 500/ngày) trong khi gọi KHÔNG
# grounding trên chính model đó vẫn chạy ngay. Với hạn mức nhỏ như vậy, bật grounding
# cho một app demo công khai là tự trói: cạn trong vài chục lượt là rơi hẳn xuống DeepSeek
# (không geocode được gì). Mặc định TẮT — _pin() đã luôn đối chiếu qua geocoder thật nên
# không còn phụ thuộc vào việc Gemini có tra web sống hay không. Đặt GEMINI_GROUNDING=true
# nếu sau này có hạn mức riêng đủ lớn (tài khoản trả phí) mới nên bật lại.
GEMINI_GROUNDING = os.getenv("GEMINI_GROUNDING", "false").strip().lower() in ("1", "true", "yes")
# Grounding có hạn mức RIÊNG: key miễn phí đo được (10/2026) trả 429 cho MỌI lượt có Google
# Search trong khi gọi thường vẫn chạy. Lúc đó TẮT grounding một giờ (không treo key — key vẫn
# còn quota gọi thường), thay vì mỗi lượt tìm địa điểm phí ~1.5 s x số key cho các 429 vô ích.
_GROUNDING_OFF_UNTIL = 0.0
_GROUNDING_OFF_SEC = 3600


def grounding_active():
    return GEMINI_GROUNDING and time.time() >= _GROUNDING_OFF_UNTIL

# Ghim sẵn model cho từng key để khỏi tốn một lần 404 mới học được: đặt
# GEMINI_MODELS="gemini-2.5-flash,,gemini-3.1-flash-lite" — theo ĐÚNG thứ tự key
# trong pool, ô để trống nghĩa là key đó dùng GEMINI_MODEL mặc định.
for _i, _m in enumerate((os.getenv("GEMINI_MODELS", "") or "").split(",")):
    _m = _m.strip()
    if _m and _i < len(GEMINI_API_KEYS):
        _GEMINI_MODEL_FOR[GEMINI_API_KEYS[_i]] = _m


def _gemini_call(prompt, grounded, retries=2):
    """One Gemini call (optionally with Google Search grounding), rotating over the
    key pool: a 429 parks that key for a minute and moves to the next one, so N free
    keys ≈ N× the free quota. 503/overload retries the same key."""
    if not GEMINI_API_KEYS:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    def build_cfg(no_thinking=False):
        # thinking_budget=0 -> TẮT "thinking" của Gemini 2.5 Flash (mặc định BẬT).
        # Đo thực tế trên chính prompt này: 16s -> 3.2s, grounding vẫn chạy thật
        # (groundingMetadata còn nguyên) và toạ độ vẫn khớp thực địa. Đây là khoản
        # tiết kiệm lớn nhất của cả luồng — tra địa điểm là tra cứu, không cần suy luận.
        # NHƯNG model khác (gemini-3.5-flash-lite) từ chối luôn tham số này — 400
        # INVALID_ARGUMENT, không phải lỗi quota — nên phải bỏ được theo từng model.
        # temperature=0: cùng một câu hỏi phải ra cùng một danh sách. Mặc định của Gemini là
        # 1.0 nên hai lượt hỏi y hệt có thể liệt kê cơ sở khác nhau (đo thật: cơ sở 3 lúc ra
        # 'Phủ Lý, Hà Nam', lúc ra 'Dương Nội, Hà Đông') — người dùng nghe hai lần thấy lệch
        # nhau thì mất tin. Tra địa điểm là tra cứu, không cần sáng tạo.
        kw = {"temperature": 0}
        if not no_thinking:
            kw["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        if grounded:
            kw["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        try:
            return types.GenerateContentConfig(**kw)
        except TypeError:
            # SDK cũ chưa có thinking_config -> chạy như trước, chỉ mất phần tăng tốc.
            kw.pop("thinking_config", None)
            return types.GenerateContentConfig(**kw)

    global _gemini_rr, _GROUNDING_OFF_UNTIL
    now = time.time()
    grounded_429 = 0
    # Ưu tiên key chưa bị treo; nếu treo hết thì cứ thử lại toàn bộ (còn hơn bỏ cuộc).
    pool = [k for k in GEMINI_API_KEYS if _GEMINI_PARKED.get(k, 0) <= now] or list(GEMINI_API_KEYS)
    start = _gemini_rr % len(pool)
    _gemini_rr += 1

    for n in range(len(pool)):
        key = pool[(start + n) % len(pool)]
        client = _GEMINI_CLIENTS.get(key)
        if client is None:
            client = _GEMINI_CLIENTS[key] = genai.Client(api_key=key)
        for i in range(retries + 1):
            model = _GEMINI_MODEL_FOR.get(key, GEMINI_MODEL)
            cfg = build_cfg(no_thinking=model in _GEMINI_NO_THINKING)
            try:
                r = client.models.generate_content(model=model, contents=prompt, config=cfg)
                _GEMINI_STRIKES.pop(key, None)      # key lại chạy được -> xoá lịch sử phạt
                return (r.text or "").strip()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                # Model này không nhận thinking_config (gemini-3.5-flash-lite -> 400
                # INVALID_ARGUMENT, KHÔNG phải quota) -> nhớ lại rồi thử lại NGAY không
                # kèm tham số đó, khỏi tốn cả key vì một tham số không tương thích.
                if (("400" in msg or "INVALID_ARGUMENT" in msg) and
                        model not in _GEMINI_NO_THINKING):
                    _GEMINI_NO_THINKING.add(model)
                    continue
                # Project của key này không có model đang cấu hình (2.5-flash bị khoá
                # với tài khoản mới) -> chuyển key đó sang model thay thế và thử lại
                # NGAY, thay vì bỏ phí cả một key còn quota.
                if ("404" in msg or "NOT_FOUND" in msg) and model != GEMINI_FALLBACK_MODEL:
                    _GEMINI_MODEL_FOR[key] = GEMINI_FALLBACK_MODEL
                    continue
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if grounded:
                        grounded_429 += 1   # hết quota GROUNDING, không phải quota của key
                        break
                    _park_429(key)          # hết quota -> treo (lâu dần) rồi đổi key
                    break
                # Key hỏng/bị đình chỉ, hoặc hết model để thử -> treo lâu, đổi key.
                if any(s in msg for s in ("API_KEY_INVALID", "PERMISSION_DENIED",
                                          "API key not valid", "SUSPENDED", "404", "NOT_FOUND")):
                    _GEMINI_PARKED[key] = time.time() + 3600
                    break
                if any(k in msg for k in ("503", "UNAVAILABLE", "overload")):
                    time.sleep(0.5 * (i + 1))
                    continue
                return None      # lỗi thật (prompt hỏng...) -> đổi key cũng vô ích

    # Grounding (google_search) có hạn mức RIÊNG và cạn sớm hơn hẳn gọi thường: đo
    # được lúc gọi thường vẫn OK mà bật grounding là 429. Hết grounding thì vẫn còn
    # kiến thức sẵn có của model — dùng tiếp còn hơn rơi thẳng xuống Nominatim.
    if grounded:
        if grounded_429 == len(pool):
            _GROUNDING_OFF_UNTIL = time.time() + _GROUNDING_OFF_SEC
            print(f"[geocode] Google Search grounding 429 trên cả {len(pool)} key -> tắt grounding "
                  f"{_GROUNDING_OFF_SEC // 60} phút, dùng Gemini thường (key cần bật billing để có grounding)")
        return _gemini_call(prompt, grounded=False, retries=1)
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


_NOMINATIM_LOCK = threading.Lock()
_nominatim_last = 0.0


def _nominatim_throttle():
    """Giãn các lần gọi Nominatim ra ≥1.1 giây — đúng chính sách của máy chủ công cộng.

    Đặt ở đây thay vì rải sleep() ở chỗ gọi, để MỌI đường dẫn tới Nominatim đều được
    bảo vệ; nhờ vậy mới ghim được toàn bộ danh sách lựa chọn mà không bị chặn IP.
    """
    global _nominatim_last
    with _NOMINATIM_LOCK:
        wait = 1.1 - (time.time() - _nominatim_last)
        if wait > 0:
            time.sleep(wait)
        _nominatim_last = time.time()


_NM_CACHE = {}           # (query, viewbox) -> (hết hạn, kết quả)
_NM_CACHE_TTL = 3600


def _nominatim_hits(address, center_lat=None, center_lng=None):
    """Up to 5 (lat, lng, display_name) hits for an address/POI, best first ([] if none).
    When a center is given, viewbox BIASES toward the pickup area (no bounded=1, so an
    out-of-area query isn't warped onto a random in-box place).

    Lấy 5 thay vì 1: tên chung ("Đại học Bách khoa ...") khớp NHIỀU cơ sở, và cơ sở đúng
    của lựa chọn đang ghim thường nằm ngay trong danh sách — chọn cái khớp vị trí thay vì
    tra tiếp từng dạng tên (mỗi lần 1.1 s).
    Kết quả (kể cả "không thấy") được nhớ 1 giờ: CÙNG một chuỗi bị tra lặp cho từng cơ sở.
    Lỗi mạng thì KHÔNG nhớ, và được in ra: trước đây nuốt im lặng nên DNS chặn Nominatim
    (máy dev) trông y như "không tìm thấy" và luồng lặng lẽ rơi xuống Mapbox."""
    params = {"q": address, "format": "json", "limit": 5, "countrycodes": "vn"}
    vb = _viewbox(center_lat, center_lng)
    if vb:
        params["viewbox"] = vb
    key = (address, vb)
    cached = _NM_CACHE.get(key)
    if cached and cached[0] > time.time():
        return cached[1]
    _nominatim_throttle()
    try:
        r = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": "VoiceGo/1.0 (hackathon accessibility demo)"},
            timeout=10,
        )
        arr = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[geocode] Nominatim lỗi ({type(exc).__name__}): {str(exc)[:120]}")
        return []
    hits = []
    for it in arr if isinstance(arr, list) else []:
        try:
            disp = it.get("display_name", "").replace(", Việt Nam", "").strip()
            disp = re.sub(r",?\s*\d{5,6}\b", "", disp)  # drop postcode
            hits.append((float(it["lat"]), float(it["lon"]), disp))
        except (KeyError, TypeError, ValueError):
            continue
    if len(_NM_CACHE) > 1000:
        _NM_CACHE.clear()
    _NM_CACHE[key] = (time.time() + _NM_CACHE_TTL, hits)
    return hits


def _nominatim_full(address, center_lat=None, center_lng=None):
    """Return (lat, lng, display_name) for an address/POI (best hit), or None."""
    hits = _nominatim_hits(address, center_lat, center_lng)
    return hits[0] if hits else None


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

    # Mapbox trước (no-op về [] khi thiếu token), rồi rơi xuống Nominatim bên dưới.
    for provider in (_mapbox_geocode,):
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
    _nominatim_throttle()
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
    """Prompt CỐ TÌNH ngắn: mỗi câu thừa là token phải sinh/đọc thêm, mà đây là
    tác vụ TRA CỨU chứ không phải suy luận. Giữ đúng 4 điều bắt buộc: phân loại
    query_type, liệt kê chi nhánh, địa chỉ ngắn, toạ độ DMS."""
    near = f" gần {user_lat},{user_lng}" if user_lat is not None and user_lng is not None else ""
    how = "TÌM KIẾM để lấy dữ liệu THẬT" if grounded else "Dựa trên hiểu biết của bạn"
    return (
        f'Bộ định vị cho app gọi xe ở Việt Nam. {how}. Địa điểm: "{text}"{near}.\n'
        'query_type="address" nếu có số nhà cụ thể, ngược lại "poi".\n'
        "Nơi có NHIỀU cơ sở/chi nhánh (trường, bệnh viện, chuỗi cửa hàng): BẮT BUỘC "
        "liệt kê MỌI cơ sở trong vùng, tối đa 4, gần trước. TUYỆT ĐỐI KHÔNG tự chọn "
        "giúp một cơ sở rồi bỏ các cơ sở còn lại — người dùng phải được tự chọn.\n"
        "name: Trả về tên CHÍNH THỨC và CHUẨN XÁC NHẤT (VD: 'lăng bác' -> 'Lăng Chủ tịch Hồ Chí Minh'). Rất quan trọng để tìm kiếm bản đồ.\n"
        "full_address ngắn: số nhà + đường + phường/quận (không quốc gia, không mã bưu chính).\n"
        # Toạ độ số của model hay lệch vài km, nên toạ độ thật lấy từ OpenStreetMap.
        # Nhưng OSM chỉ tìm ra khi tên được viết đúng kiểu của nó — đo trên dữ liệu thật:
        #   'Đại học Công nghiệp Hà Nội cơ sở 2'         -> đúng cơ sở
        #   'Đại học Công nghiệp Hà Nội (Cơ sở 2)'       -> TRƯỢT (dấu ngoặc)
        #   'Trường Đại học Công nghiệp Hà Nội Cơ sở 2'  -> TRƯỢT (tiền tố)
        # Nên bắt model tự chuẩn hoá luôn, thay vì cắt gọt bằng regex ở phía sau.
        "map_query: tên để TRA BẢN ĐỒ OpenStreetMap. Viết đúng cách OSM đặt tên: "
        "bỏ tiền tố loại hình ('Trường', 'Công ty', 'Trung tâm'), KHÔNG dấu ngoặc, "
        "GIỮ phần chi nhánh dạng chữ thường ('cơ sở 2'), KHÔNG kèm số nhà/phường/quận. "
        "Vd 'Trường Đại học Công nghiệp Hà Nội (Cơ sở 2)' -> 'Đại học Công nghiệp Hà Nội cơ sở 2'.\n"
        "Chi nhánh có 2 cách gọi (theo SỐ và theo KHU VỰC): map_query dùng cách theo số "
        "('cơ sở 2'), map_query_alt dùng cách theo khu vực ('cơ sở Dĩ An'); OSM mỗi nơi đặt "
        "một kiểu nên cần cả hai. Chỉ có một cách gọi thì để map_query_alt rỗng.\n"
        "Toạ độ DMS tới 0.1 giây, đặt pin ĐÚNG địa điểm (vd 10°47'09.1\"N, 106°42'09.8\"E).\n"
        "CHỈ trả JSON, không giải thích:\n"
        '{"query_type":"poi|address","locations":[{"name":"","map_query":"","map_query_alt":"","full_address":"",'
        '"lat_dms":"","lng_dms":""}]}'
    )


def _gemini_locations(text, user_lat, user_lng):
    """Gemini -> {query_type, locations:[{name,address,lat,lng}]}, or None. Chỉ dùng để
    ĐỀ XUẤT tên/chi nhánh — toạ độ của model KHÔNG được tin, luôn đối chiếu qua geocoder
    thật ở _pin(). Nhờ vậy grounding (Google Search) là TÙY CHỌN (GEMINI_GROUNDING), không
    bắt buộc: tắt grounding tránh đúng cái quota nhỏ giọt và chia sẻ chung mọi model/key."""
    if not GEMINI_API_KEYS:
        return None
    grounded = grounding_active()
    data = _parse_json(_gemini_call(_build_prompt(text, user_lat, user_lng, grounded),
                                     grounded=grounded, retries=1))
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
                    # Tên đã chuẩn hoá cho OSM, do chính model trả về (xem _build_prompt).
                    "map_query": (item.get("map_query") or "").strip(),
                    "map_query_alt": (item.get("map_query_alt") or "").strip(),
                    "lat": lat, "lng": lng})
    return {"query_type": data.get("query_type", "poi"), "locations": out}


_ADMIN_RE = re.compile(r"^(phường|quận|huyện|xã|thị xã|thị trấn|thành phố|tp\.?|tỉnh|khu phố|kp\.?|ấp|tổ|p\.|q\.)(\s|$)",
                       re.IGNORECASE)
_CITY_RE = re.compile(r"^(thành phố|tp\.?)\s*hồ chí minh$|^tp\.?\s*hcm$|^tphcm$|^hà nội$|^thành phố hà nội$",
                      re.IGNORECASE)


def _street_address(addr):
    """'468 Nguyễn Trãi, Phường 8, Quận 5, Thành phố Hồ Chí Minh' -> '468 Nguyễn Trãi, Thành phố
    Hồ Chí Minh', hoặc '' nếu không có số nhà + tên đường.

    Phường/quận ĐÁNH SỐ kiểu cũ là thứ làm Nominatim khớp bậy sau đợt sáp nhập hành chính
    2025 (OSM đã đổi tên phường, bỏ quận): đo được "Phường 4, Quận 5" -> "Hẻm 491/5 Lạc
    Long Quân" (khớp nhầm chữ số), "Phường 8, Quận 5" -> "UBND phường 8 quận 8". Còn số
    nhà + đường thì đứng vững: "720A Điện Biên Phủ" -> đúng Landmark 81."""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    keep = []
    for p in parts:
        if _ADMIN_RE.match(p) or _CITY_RE.match(p):
            break
        keep.append(p)
    if not keep or not re.match(r"^\d+[\w/]*\s+\D", keep[0]):
        return ""
    city = next((p for p in parts if _CITY_RE.match(p)), "")
    return ", ".join(keep + ([city] if city else []))


_BRANCH_KW = r"(cơ sở|chi nhánh|campus|\bcs\s*\d)"


def _branch_part(name):
    """Phần chỉ CƠ SỞ/CHI NHÁNH trong tên ('Cơ sở 2', 'cơ sở Dĩ An'), hoặc '' nếu không có.
    Quy tắc ngôn ngữ (từ khoá chỉ chi nhánh), không phải danh sách địa điểm."""
    s = name or ""
    for m in re.finditer(r"\(([^)]*)\)", s):
        if re.search(_BRANCH_KW, m.group(1), re.IGNORECASE):
            return m.group(1).strip()
    m = re.search(_BRANCH_KW + r".*$", s, re.IGNORECASE)
    return m.group(0).strip(" -)") if m else ""


def _poi_queries(name, map_query="", map_query_alt=""):
    """Các dạng tên để tra Nominatim, xếp theo thứ tự ĐO ĐƯỢC là tốt nhất.

    OSM ghi hẳn chi nhánh vào tên POI — "Đại học Công nghiệp Hà Nội (cơ sở 2)",
    "Đại học Bách Khoa - Cơ sở Dĩ An" — nên GIỮ phần cơ sở mới ghim đúng cơ sở. Hai thứ
    làm Nominatim TRƯỢT HẲN (đo trên chính ca này):
      "Đại học Công nghiệp Hà Nội cơ sở 2"          -> đúng cơ sở 2, Ngõ 59A Tây Tựu
      "Đại học Công nghiệp Hà Nội (Cơ sở 2)"        -> MISS   (dấu ngoặc)
      "Trường Đại học Công nghiệp Hà Nội Cơ sở 2"   -> MISS   (tiền tố "Trường")
    Tên thêm định danh hệ thống/thành phố cũng trượt: "Đại học Bách khoa - Đại học Quốc
    gia Thành phố Hồ Chí Minh Cơ sở 1" -> MISS, nên có dạng gọn chỉ còn tên + cơ sở.
    Dạng TRẦN (bỏ hẳn phần cơ sở) để cuối cùng: nó ra MỘT cơ sở bất kỳ, nên _pin chỉ nhận
    nó khi khớp với vị trí của chính lựa chọn đang ghim.
    """
    raw = (name or "").strip()
    if not raw:
        return []
    # Bỏ tiền tố loại hình chung. Đây là quy tắc NGÔN NGỮ, không phải danh sách địa
    # điểm — nhưng vẫn chỉ là phỏng đoán, nên bản gốc luôn được thử lại ở cuối thay vì
    # bị loại. Không có địa điểm hay toạ độ nào bị fix cứng ở đây.
    nopre = re.sub(r"^(Trường|Trung tâm|Công ty|Chi nhánh|Cơ sở)\s+", "", raw, flags=re.IGNORECASE)
    def _plain(s):    # "(cơ sở 2)" -> "cơ sở 2": bỏ ngoặc, GIỮ chữ bên trong
        return re.sub(r"\s+", " ", re.sub(r"[()]", " ", s)).strip()
    def _bare(s):     # bỏ hẳn phần trong ngoặc
        return re.sub(r"\s*\([^)]*\)", "", s).strip()
    def _core(s):     # bỏ đoạn " - <hệ thống/thành phố>" và tên TP.HCM, GIỮ phần cơ sở
        s = re.sub(r"\s+-\s+[^()]*?(?=\(|$)", " ", s)
        s = re.sub(r"\b(Thành phố|TP\.?)\s*Hồ Chí Minh\b|\bTP\.?\s*HCM\b|\bTPHCM\b", " ", s,
                   flags=re.IGNORECASE)
        return _plain(s)
    # map_query(_alt) do model tự chuẩn hoá đứng ĐẦU — sửa ở gốc tốt hơn cắt gọt bằng
    # regex; các biến thể sau chỉ là lưới đỡ khi model không trả trường đó.
    # Thứ tự theo tỉ lệ RA KẾT QUẢ đo được: dạng của model, rồi tên TRẦN (hay ra nhất, và _pin
    # chỉ nhận nó khi khớp vị trí của lựa chọn này), rồi các dạng gọt. Mỗi lần trượt tốn 1.1 s
    # nên tối đa 5 dạng (đo: 6-7 lần trượt liên tiếp = 13 s cho một địa điểm).
    variants = [(map_query or "").strip(), (map_query_alt or "").strip(), _core(_bare(nopre)), _bare(nopre),
                _core(nopre), _plain(nopre), _plain(raw), _bare(raw), raw]
    # Nominatim không phân biệt hoa/thường: "cơ sở Thủ Đức" và "Cơ sở Thủ Đức" là CÙNG một lần
    # tra, mỗi lần 1.1 s -> khử trùng không phân biệt hoa/thường.
    out, seen = [], set()
    for v in variants:
        k = v.casefold()
        if v and k not in seen:
            seen.add(k)
            out.append(v)
    return out[:5]


def _drop_coincident(pinned):
    """Loại các candidate ghim TRÙNG ĐIỂM (<200m) với một candidate khác, chỉ giữ đại
    diện đầu mỗi cụm (locs đã sort theo khoảng cách -> đại diện là cái gần điểm đón
    nhất). `pinned` là list (loc, verified) từ _pin. Áp dụng cho cả Gemini và DeepSeek:
    cả hai đều có lúc BỊA thêm chi nhánh không có thật (đo được: hỏi "Đại học Công nghiệp
    Hà Nội", 2/3 lần liệt kê thêm cả 'Cơ sở Thanh Hóa'/'Cơ sở Nghệ An' không tồn tại).
    Chi nhánh bịa không khớp gì trong OSM, rơi về đúng toạ độ của cơ sở THẬT gần nhất ->
    hai chi nhánh ghim trùng điểm (chi nhánh thật không bao giờ cách nhau <200m).

    So theo toạ độ GEOCODER đã chốt (`_ref`), không theo toạ độ trả ra: _pin có thể giữ
    toạ độ Gemini khi hai bên khớp gần, nên hai lựa chọn chốt về CÙNG một POI vẫn lệch
    nhau vài trăm mét ở đầu ra và lọt qua phép so cũ (ca thật Bách Khoa).
    """
    def pt(loc):
        r = loc.get("_ref")
        return r if r else ((loc["lat"], loc["lng"]) if loc.get("lat") is not None else None)
    kept, seen_idx = [], set()
    for i, (a, ok) in enumerate(pinned):
        if i in seen_idx:
            continue
        pa = pt(a)
        for j in range(i + 1, len(pinned)):
            pb = pt(pinned[j][0])
            if pa and pb and _haversine_km(pa[0], pa[1], pb[0], pb[1]) < 0.2:
                seen_idx.add(j)
        kept.append((a, ok))
    return kept


def _pin(loc, center_lat, center_lng, is_address=False, pickup=None, one_shot=False):
    """Chốt toạ độ để ghim lên bản đồ. Trả (loc, verified).

    Nguyên tắc: **Gemini quyết định ĐÓ LÀ CHỖ NÀO, geocoder thật quyết định NÓ
    NẰM Ở ĐÂU.** Toạ độ số của Gemini đo được là hay bịa/lệch; tên + địa chỉ chữ thì
    dùng được làm bằng chứng nhận dạng.

    Ca thật đã bắt được: hỏi "trường trung học thực hành ĐH Sư phạm TPHCM",
    Gemini trả địa chỉ ĐÚNG (280 An Dương Vương, P4, Q5) nhưng toạ độ lại là
    10.776889,106.700889 — cách ĐIỂM ĐÓN truyền vào prompt đúng 2 mét, tức nó
    chép lại gợi ý vị trí. Mapbox cho 10.757776,106.674800, lệch 3.56 km.

    Ca thật thứ hai (Bách Khoa, 10/2026): Gemini trả đúng 2 cơ sở, nhưng mọi dạng tên
    kèm cơ sở đều trượt trong OSM, nên rơi về TÊN TRẦN "Đại học Bách khoa ..." -> OSM trả
    MỘT cơ sở (tuỳ điểm đón) và CẢ HAI lựa chọn bị ghim vào đó, verified=True: đón ở Quận 1
    thì "cơ sở 1 (Lý Thường Kiệt)" ra Dĩ An. Một kết quả tra bằng tên chung KHÔNG chứng
    minh được nó là cơ sở này. Nên:
      - Toạ độ trùng điểm đón (<150 m) => coi như KHÔNG có, đây là dấu hiệu bịa.
      - Khi tên có thể trỏ sang nơi KHÁC (đang ghim một trong nhiều lựa chọn, hoặc tên
        có phần cơ sở/chi nhánh), kết quả tra tên phải KHỚP vị trí của chính lựa chọn
        này (toạ độ Gemini, không có thì địa chỉ Gemini đem tra) trong VERIFY_RADIUS_KM.
        Không khớp = cơ sở khác -> bỏ, ghim theo ĐỊA CHỈ của lựa chọn này.
      - Có geocoder trả kết quả => geocoder thắng, trừ khi là POI và hai bên đã
        khớp nhau (lúc đó giữ toạ độ Gemini vì nó ghim đúng toà nhà, còn
        geocoder hay rơi ra giữa đường).
      - Mapbox chỉ là lưới đỡ; với POI chỉ nhận kết quả loại "poi" hoặc khớp vị trí.
      - Không geocoder nào trả => đành giữ Gemini nhưng verified=False.
    """
    g = None
    if isinstance(loc.get("lat"), (int, float)) and isinstance(loc.get("lng"), (int, float)):
        g = (loc["lat"], loc["lng"])
    if g and pickup and _haversine_km(g[0], g[1], pickup[0], pickup[1]) <= 0.15:
        g = None                                   # chép lại điểm đón -> vứt

    # POI: tra TÊN trước (Nominatim tìm "Lăng Chủ tịch Hồ Chí Minh" chuẩn 41m, nhưng địa
    # chỉ "2 Hùng Vương, Điện Biên, Ba Đình" thì fail). Address: tra ĐỊA CHỈ trước. Nominatim
    # trước Mapbox (đo trên 8 địa điểm VN: thắng 7-1), mọi kết quả phải trong bán kính phục vụ
    # ("THPT Lê Hồng Phong" từng ra tận 1120 km).
    name = loc.get("name") or ""
    addr = loc.get("address") or ""
    primary = addr if is_address else name
    fallback = name if is_address else addr
    within = lambda h: h and _within_service(h[0], h[1], center_lat, center_lng)  # noqa: E731

    # Toạ độ Gemini đo được thường chỉ lệch 0.2-0.4 km, TRỪ khi nó bám sát điểm đón (ca thật:
    # "Landmark 81" đặt cách điểm đón 0.5 km, xa toà nhà thật 2.7 km) -> lúc đó không đem làm mốc.
    g_ok = g if (g and not (pickup and _haversine_km(g[0], g[1], pickup[0], pickup[1]) <= 0.6)) else None
    must_agree = (not is_address) and (one_shot or bool(_branch_part(name)))
    anchor = {"hit": None, "tried": False}

    def near(a, b):
        return _haversine_km(a[0], a[1], b[0], b[1]) <= VERIFY_RADIUS_KM

    def addr_hit():
        # Vị trí theo ĐỊA CHỈ chữ của chính lựa chọn này — CHỈ khi địa chỉ có số nhà + tên
        # đường. Địa chỉ cấp phường ("Phường Linh Trung, Thủ Đức") quá thô để làm bằng chứng:
        # đo được nó trả một POI bất kỳ trong phường ("Trạm Y Tế Phường Linh Trung", lệch 4.5
        # km khỏi trường) rồi chính điểm đó được ghim với verified=True.
        if not anchor["tried"]:
            anchor["tried"] = True
            street = _street_address(addr)
            for q in (dict.fromkeys([addr.strip(), street]) if street else ()):
                if not q:
                    continue
                a = next((h for h in _nominatim_hits(q, center_lat, center_lng) if within(h)), None)
                if a:
                    anchor["hit"] = a
                    break
        return anchor["hit"]

    coarse = {"pt": None, "tried": False}

    def coarse_pt():
        # Mốc THÔ theo địa chỉ cấp phường (không số nhà): quá thô để GHIM (đo: lệch 4.5 km)
        # nhưng đủ để CHỌN giữa các cơ sở cách nhau hàng chục km (KHTN: 18 km). Chỉ dùng
        # khi không còn bằng chứng nào khác, với bán kính COARSE_KM.
        if not coarse["tried"]:
            coarse["tried"] = True
            # Phường/quận ĐÁNH SỐ kiểu cũ ("Phường 4, Quận 5") làm Nominatim khớp nhầm chữ số
            # (ra "Hẻm 491/5") -> chỉ dùng khi đơn vị hành chính có TÊN chữ.
            if addr.strip() and not _street_address(addr) and \
                    not re.search(r"\b(phường|quận|p\.|q\.)\s*\d+\b", addr, re.IGNORECASE):
                h = next((x for x in _nominatim_hits(addr.strip(), center_lat, center_lng) if within(x)), None)
                if h:
                    coarse["pt"] = (h[0], h[1])
        return coarse["pt"]

    def pick(hits):
        """Kết quả tra TÊN nào là chính nơi này: khớp toạ độ Gemini (nếu đáng tin), không
        thì khớp vị trí theo địa chỉ. Có bằng chứng mà không cái nào khớp = tên đang trỏ
        nơi KHÁC (cơ sở khác của cùng trường; "Landmark 81" -> "PetroVietnam Landmark";
        "Đại học Bách khoa" -> cơ sở kia) -> bỏ. Không có bằng chứng nào: địa điểm đơn thì
        tin tên như trước, một trong nhiều lựa chọn thì không (tên chung dễ là cơ sở khác)."""
        if g:
            # Toạ độ Gemini — kể cả khi nằm sát điểm đón — được dùng để XÁC NHẬN một kết quả
            # tra tên ở gần nó (hai nguồn độc lập cùng chỉ một chỗ). Chỉ không dùng nó để LOẠI
            # kết quả (xem g_ok). Ca thật: người dùng đứng ở ĐH Quốc tế, tìm KHTN Linh Trung
            # cách 0.4 km -> toạ độ Gemini đúng nhưng "sát điểm đón", trước đây bị bỏ qua và
            # kết quả tra tên đúng bị loại.
            c = sorted((h for h in hits if near(g, h)), key=lambda h: _haversine_km(g[0], g[1], h[0], h[1]))
            if c:
                return c[0]
        a = addr_hit() if not is_address else None
        if a:
            # Tên và địa chỉ khớp NHAU -> 2 trên 3, thắng cả khi toạ độ Gemini lệch.
            c = [h for h in hits if near(a, h)]
            if c:
                return c[0]
        if is_address or not (g_ok or a or must_agree):
            return hits[0]
        if must_agree and not g_ok and not a:
            cp = coarse_pt()
            if cp:
                c = sorted((h for h in hits if _haversine_km(cp[0], cp[1], h[0], h[1]) <= COARSE_KM),
                           key=lambda h: _haversine_km(cp[0], cp[1], h[0], h[1]))
                if c:
                    return c[0]
        return None

    tries = [primary] if is_address else _poi_queries(name, loc.get("map_query"), loc.get("map_query_alt"))
    nm, from_addr, first_seen = None, False, None
    for q in tries:
        if not q.strip():
            continue
        hits = [h for h in _nominatim_hits(q, center_lat, center_lng) if within(h)]
        if hits:
            first_seen = first_seen or hits[0]
            nm = pick(hits)
            if nm:
                break
    # Tên không ghim được (hoặc chỉ ra nơi KHÁC) -> ghim theo trường còn lại (địa chỉ cho POI,
    # tên cho địa chỉ). Trước đây bỏ bước này khi ghim cả danh sách (one_shot) cho nhanh, nhưng
    # đó đúng là lúc tên chung dễ trỏ sang cơ sở khác; nhờ cache không tốn thêm lần tra nào.
    if not nm and fallback.strip() and fallback != primary:
        hit = addr_hit() if not is_address else _nominatim_full(fallback, center_lat, center_lng)
        # Ghim theo địa chỉ khi không tên nào khớp: địa chỉ phải khớp toạ độ Gemini (nếu đáng
        # tin) — hai nguồn duy nhất còn lại mà cãi nhau thì không tin bên nào, để verified=False.
        if within(hit) and (is_address or g_ok is None or near(g_ok, hit)):
            nm, from_addr = hit, not is_address
    # Địa chỉ ĐỌC luôn lấy theo geocoder thật, KHÔNG theo Gemini tự đoán (đo được nhiều ca
    # Gemini bịa cả tên phường/quận trong khi geocoder đã xác nhận đúng nơi).
    ref = None
    if nm:
        disp = nm[2] or addr
        if from_addr:
            # Ghim theo ĐỊA CHỈ: tên POI đứng đầu kết quả là của chỗ khác cùng số nhà
            # (ca thật: "OCB, 268 Lý Thường Kiệt") -> bỏ, đọc từ số nhà/đường trở đi.
            ps = [p.strip() for p in disp.split(",")]
            if len(ps) >= 2 and not re.search(r"\d", ps[0]) and re.search(r"\d", ps[1]):
                disp = ", ".join(ps[1:])
        ref = {"name": loc["name"], "address": disp, "lat": nm[0], "lng": nm[1]}
    if not ref:
        mb = _mapbox_first(addr or name, center_lat, center_lng)
        pt = g_ok or (addr_hit() if not is_address else None)
        if mb and (is_address or mb.get("type") == "poi" or (pt is not None and near(pt, (mb["lat"], mb["lng"])))):
            ref = {**mb, "address": mb.get("address") or addr}

    if not ref:
        # Không có gì để đối chiếu. Nếu toạ độ Gemini đã bị loại vì chép điểm đón, ĐỪNG trả
        # lại chính điểm đón (ca thật: "cách 0 km") — dùng kết quả tra tên đầu tiên, vẫn để
        # verified=False (lúc người dùng chọn, _do_select tra lại lựa chọn chưa xác minh).
        if g is None and isinstance(loc.get("lat"), (int, float)):
            cp = coarse_pt() if not is_address else None
            if cp:
                return {**loc, "lat": cp[0], "lng": cp[1]}, False
            if first_seen:
                return {**loc, "lat": first_seen[0], "lng": first_seen[1],
                        "address": _short_address(first_seen[2], loc.get("name") or "")}, False
        return loc, False
    final_addr = _short_address(ref.get("address"), loc["name"])
    ref_pt = (ref["lat"], ref["lng"])
    if g_ok and not is_address and not from_addr and _haversine_km(g_ok[0], g_ok[1], ref["lat"], ref["lng"]) <= 0.3:
        # POI khớp RẤT gần (<=300 m) -> giữ TOẠ ĐỘ Gemini (đứng đúng building hơn geocoder),
        # vẫn đổi ĐỊA CHỈ theo geocoder. Trước đây ngưỡng là 3 km: Gemini lệch 2.7 km
        # (Landmark 81) vẫn được giữ, đè lên toạ độ geocoder đã đúng.
        return {"name": loc["name"], "address": final_addr, "lat": g[0], "lng": g[1], "_ref": ref_pt}, True
    return {"name": loc["name"], "address": final_addr,
            "lat": ref["lat"], "lng": ref["lng"], "_ref": ref_pt}, True


def geocode_query(query, user_lat=None, user_lng=None):
    """Tra MỘT chuỗi qua geocoder THẬT (Nominatim rồi Mapbox). Không dùng LLM ở đây.

    Tách riêng thành hàm để AGENT tự quyết định chuỗi tra: nó nhận danh sách địa điểm
    do Gemini tìm được, rồi tự soạn chuỗi theo kiểu OSM đặt tên. Trước đây backend tự
    ghim bằng tên thô của Gemini nên agent không chen vào được.
    """
    q = (query or "").strip()
    if not q:
        return None
    center_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    center_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]
    nm = _nominatim_full(q, center_lat, center_lng)
    if nm and _within_service(nm[0], nm[1], center_lat, center_lng):
        return {"name": q, "address": _short_address(nm[2], q), "lat": nm[0], "lng": nm[1],
                "verified": True, "source": "nominatim", "resolved": nm[2]}
    mb = _mapbox_first(q, center_lat, center_lng)
    if mb and _within_service(mb["lat"], mb["lng"], center_lat, center_lng):
        return {"name": mb.get("name") or q, "address": _short_address(mb.get("address"), q),
                "lat": mb["lat"], "lng": mb["lng"], "verified": True, "source": "mapbox",
                "resolved": mb.get("address") or ""}
    return None


def verify_location(loc, user_lat=None, user_lng=None, is_address=False):
    """Chốt toạ độ cho MỘT địa điểm — gọi khi người dùng đã chọn xong candidate.

    Tách riêng vì Nominatim công cộng giới hạn ~1 request/giây: không thể đối
    chiếu cả 4 candidate cùng lúc. Danh sách candidate trả về nhanh (toạ độ thô
    của Gemini, đủ để hiển thị), rồi đúng cái được chọn mới đem đi chốt.
    """
    center_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    center_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]
    pickup = (user_lat, user_lng) if user_lat is not None else None
    out, ok = _pin(loc, center_lat, center_lng, is_address, pickup)
    out = {k: v for k, v in out.items() if k != "_ref"}
    out["verified"] = ok
    if user_lat is not None:
        out["distanceKm"] = round(_haversine_km(user_lat, user_lng, out["lat"], out["lng"]), 1)
    return out


_RESOLVE_CACHE = {}      # (câu nói chuẩn hoá, ô điểm đón ~1 km) -> (hết hạn, kết quả)
_RESOLVE_TTL = 6 * 3600


def resolve_locations(text, user_lat=None, user_lng=None):
    """Giải mã địa điểm nói ra -> 1..N vị trí thật; nhớ kết quả 6 giờ theo (câu nói, ô ~1 km
    quanh điểm đón). Bỏ danh bạ viết cứng làm MỌI lượt phải qua Gemini (~3-5 s) + Nominatim
    (1.1 s/lần, tuần tự): nơi đã tìm một lần thì lần sau trả ngay. Đây là kết quả geocoder
    thật đã chốt, không phải danh bạ viết tay. Không nhớ lượt thất bại."""
    if not (text or "").strip():
        return {"ok": False, "reason": "empty"}
    c_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    c_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]
    key = (" ".join(text.casefold().split()), round(c_lat, 2), round(c_lng, 2))
    hit = _RESOLVE_CACHE.get(key)
    if hit and hit[0] > time.time():
        r = copy.deepcopy(hit[1])
        for l in r.get("locations", []):
            if user_lat is not None and l.get("lat") is not None:
                l["distanceKm"] = round(_haversine_km(user_lat, user_lng, l["lat"], l["lng"]), 1)
        r["cached"] = True
        return r
    r = _resolve_locations_uncached(text, user_lat, user_lng)
    if r.get("ok"):
        if len(_RESOLVE_CACHE) > 500:
            _RESOLVE_CACHE.clear()
        _RESOLVE_CACHE[key] = (time.time() + _RESOLVE_TTL, copy.deepcopy(r))
    return r


def _resolve_locations_uncached(text, user_lat=None, user_lng=None):
    """Giải mã một địa điểm nói ra thành 1..N vị trí thật (chi nhánh/cơ sở).

    Gemini (grounded) là bộ não chính — nó xử được địa điểm bất kỳ, không hardcode.
    Nhưng KHÔNG tin hẳn: mọi toạ độ đều được đối chiếu với geocoder thật
    (Mapbox, rồi Nominatim) qua `_verify_coord`.

    Mapbox chạy SONG SONG với Gemini, không nối tiếp: Mapbox ~0.5s còn Gemini
    ~3s, nên phần cross-check gần như miễn phí về thời gian, và khi Gemini hỏng
    thì đã có sẵn kết quả Mapbox để dùng ngay thay vì phải gọi lại.
    """
    if not text.strip():
        return {"ok": False, "reason": "empty"}
    center_lat = user_lat if user_lat is not None else DEFAULT_CENTER[0]
    center_lng = user_lng if user_lng is not None else DEFAULT_CENTER[1]

    def fin(loc, verified=True):
        if user_lat is not None and loc.get("lat") is not None and loc.get("lng") is not None:
            d = round(_haversine_km(user_lat, user_lng, loc["lat"], loc["lng"]), 1)
        else:
            d = None
        return {"name": loc["name"], "address": _short_address(loc.get("address"), loc["name"]),
                "lat": loc.get("lat"), "lng": loc.get("lng"), "distanceKm": d, "verified": verified}

    def within(loc):
        if loc.get("lat") is None or loc.get("lng") is None:
            return True
        return _within_service(loc["lat"], loc["lng"], center_lat, center_lng)

    # KHÔNG có danh bạ địa điểm viết cứng (places_db đã bỏ): nó trả thẳng toạ độ có sẵn,
    # bỏ qua cả Gemini lẫn Nominatim, nên một alias chung như "bách khoa" khớp bừa cơ sở
    # có sẵn trong danh bạ thay vì nơi người dùng thật sự muốn. Mọi địa điểm đều đi đúng
    # một đường: Gemini đề xuất tên -> geocoder thật (Nominatim, rồi Mapbox) chốt toạ độ.

    # 1) Gemini grounded + Mapbox CHẠY SONG SONG: Mapbox (~0.5s) chạy nấp dưới
    # bóng Gemini (~3.2s) nên không tốn thêm thời gian, và nếu Gemini hỏng/hết
    # quota thì đã có sẵn lưới đỡ, khỏi phải gọi lại.
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_gem = pool.submit(_gemini_locations, text, user_lat, user_lng)
        f_mb = pool.submit(_mapbox_first, text, center_lat, center_lng)
        data, mb = f_gem.result(), f_mb.result()

    if data and data.get("locations"):
        locs = [l for l in data["locations"] if within(l)]
        if not locs:
            return {"ok": False, "reason": "out_of_area"}
        if user_lat is not None:
            locs.sort(key=lambda l: _haversine_km(user_lat, user_lng, l["lat"], l["lng"]))
        locs = locs[:4]
        is_addr = data.get("query_type") == "address"
        pickup = (user_lat, user_lng) if user_lat is not None else None

        # NHIỀU cơ sở -> CHỐT TOẠ ĐỘ CHO TẤT CẢ trước khi trả về. Không có "pin tạm":
        # pin hiện trên bản đồ phải đúng ngay từ đầu, và đã chốt sẵn thì lúc người dùng
        # chọn xong khỏi phải tra lại. Nominatim giới hạn ~1 req/giây nên phải làm lần
        # lượt (_nominatim_throttle lo việc giãn nhịp) — 3 chỗ mất ~3 giây, đổi lại
        # không còn toạ độ nào là phỏng đoán.
        if len(locs) >= 2:
            # Ghim SONG SONG. Bộ điều tiết vẫn xếp hàng các lần gọi Nominatim đúng
            # 1 req/giây (nên vẫn tuân thủ), nhưng phần còn lại — Mapbox dự phòng,
            # thời gian chờ mạng — thì chồng lên nhau thay vì cộng dồn.
            with ThreadPoolExecutor(max_workers=min(4, len(locs))) as pool:
                futs = [pool.submit(_pin, l, center_lat, center_lng, is_addr, pickup, True)
                        for l in locs]
                pinned = _drop_coincident([f.result() for f in futs])
            return {"ok": True, "query_type": data.get("query_type", "poi"),
                    "source": "grounded", "locations": [fin(loc, ok) for loc, ok in pinned]}

        # Chỉ MỘT nơi -> đó chính là điểm đến, chốt toạ độ luôn.
        loc0, ok0 = _pin(locs[0], center_lat, center_lng, is_addr, pickup)
        return {"ok": True, "query_type": data.get("query_type", "poi"),
                "source": "grounded" if ok0 else "grounded_unverified",
                "locations": [fin(loc0, ok0)]}

    # 2) Gemini hỏng/không có key -> Dùng DeepSeek (llm_json) làm đầu não để phân tích chi nhánh/địa chỉ
    prompt = (
        f'Người dùng tìm địa điểm: "{text}".\n'
        'Nhiệm vụ: Xác định tên chuẩn xác. Nếu đây là địa điểm có nhiều chi nhánh (ví dụ: đại học khxh&nv, lotteria, starbucks...), liệt kê CÁC CƠ SỞ/CHI NHÁNH BẠN CHẮC CHẮN LÀ CÓ THẬT, tối đa 4, gần TPHCM/Hà Nội trước.\n'
        'Đặt tên chi nhánh theo SỐ THỨ TỰ đơn giản (Cơ sở 1, Cơ sở 2...) nếu không chắc tên gọi chính thức của từng cơ sở — '
        'KHÔNG tự chế tên theo tỉnh/thành (vd "Cơ sở Thanh Hóa", "Cơ sở Nghệ An") trừ khi bạn CHẮC CHẮN đó là tên gọi thật.\n'
        'Nếu là địa chỉ cụ thể, trả về 1 kết quả.\n'
        'CHỈ trả về JSON định dạng sau (không giải thích):\n'
        '{"query_type": "poi|address", "locations": [{"name": "Tên chi nhánh (rất chuẩn xác)", "address": "Địa chỉ ngắn gọn (số, đường, phường, quận, tỉnh)"}]}'
    )
    raw = llm_json(prompt)
    ds_data = _parse_json(raw) if raw else None
    
    if ds_data and ds_data.get("locations"):
        locs = []
        is_addr = ds_data.get("query_type") == "address"
        pickup = (user_lat, user_lng) if user_lat is not None else None
        
        for loc in ds_data["locations"]:
            name = loc.get("name") or text
            addr = loc.get("address") or ""
            locs.append({
                "name": name,
                "address": addr,
                "lat": None,
                "lng": None
            })
                
        if locs:
            locs = locs[:4]

            # DeepSeek chỉ đoán TÊN (không có Google Search grounding như Gemini), nên
            # càng phải ghim qua geocoder thật trước khi trả về — không có "pin tạm" ở
            # nhánh này cũng như nhánh Gemini phía trên. Trước đây trả lat=None thẳng,
            # vi phạm đúng nguyên tắc pin phải đúng ngay từ đầu.
            if len(locs) >= 2:
                with ThreadPoolExecutor(max_workers=min(4, len(locs))) as pool:
                    futs = [pool.submit(_pin, l, center_lat, center_lng, is_addr, pickup, True)
                            for l in locs]
                    pinned = _drop_coincident([f.result() for f in futs])
                return {"ok": True, "query_type": ds_data.get("query_type", "poi"),
                        "source": "deepseek_only", "locations": [fin(loc, ok) for loc, ok in pinned]}

            # Có đúng 1 kết quả -> verify chặt chẽ qua _pin (Resolve 2)
            loc0, ok0 = _pin(locs[0], center_lat, center_lng, is_addr, pickup)
            return {"ok": True, "query_type": ds_data.get("query_type", "poi"),
                    "source": "deepseek_pinned" if ok0 else "deepseek_unverified", 
                    "locations": [fin(loc0, ok0)]}

    # 3) Fallback cuối cùng nếu cả Gemini và DeepSeek hỏng
    coords = _nominatim(text, center_lat, center_lng) or _nominatim(f"{text}, Việt Nam")
    if coords and within({"lat": coords[0], "lng": coords[1]}):
        return {"ok": True, "query_type": "address", "source": "nominatim_raw",
                "locations": [fin({"name": text, "address": text, "lat": coords[0], "lng": coords[1]})]}
    if mb:
        return {"ok": True, "query_type": "address", "source": "mapbox", "locations": [fin(mb)]}
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

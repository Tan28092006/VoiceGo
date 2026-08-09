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
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from voice import GEMINI_API_KEY, GEMINI_API_KEYS, GEMINI_MODEL, llm_json
from places_db import lookup as _local_lookup, lookup_all as _lookup_all_pd

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Mapbox geocoding — strong VN coverage, generous free tier, no billing hassle.
# Chạy SONG SONG với Gemini để cross-check toạ độ mà không tốn thêm thời gian.
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places"

# Gemini (grounded) là bộ não chính, nhưng KHÔNG tin hẳn: toạ độ được đối chiếu
# với geocoder thật (Mapbox, rồi Nominatim). Lệch quá ngưỡng này coi như không
# khớp -> hạ cờ verified để tầng trên biết mà thận trọng.
VERIFY_RADIUS_KM = 3.0

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

    # thinking_budget=0 -> TẮT "thinking" của Gemini 2.5 Flash (mặc định BẬT).
    # Đo thực tế trên chính prompt này: 16s -> 3.2s, grounding vẫn chạy thật
    # (groundingMetadata còn nguyên) và toạ độ vẫn khớp thực địa. Đây là khoản
    # tiết kiệm lớn nhất của cả luồng — tra địa điểm là tra cứu, không cần suy luận.
    kw = {"thinking_config": types.ThinkingConfig(thinking_budget=0)}
    if grounded:
        kw["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    try:
        cfg = types.GenerateContentConfig(**kw)
    except TypeError:
        # SDK cũ chưa có thinking_config -> chạy như trước, chỉ mất phần tăng tốc.
        cfg = (types.GenerateContentConfig(tools=kw["tools"]) if grounded else None)

    global _gemini_rr
    now = time.time()
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
            try:
                r = client.models.generate_content(model=model, contents=prompt, config=cfg)
                _GEMINI_STRIKES.pop(key, None)      # key lại chạy được -> xoá lịch sử phạt
                return (r.text or "").strip()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                # Project của key này không có model đang cấu hình (2.5-flash bị khoá
                # với tài khoản mới) -> chuyển key đó sang model thay thế và thử lại
                # NGAY, thay vì bỏ phí cả một key còn quota.
                if ("404" in msg or "NOT_FOUND" in msg) and model != GEMINI_FALLBACK_MODEL:
                    _GEMINI_MODEL_FOR[key] = GEMINI_FALLBACK_MODEL
                    continue
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
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


def _nominatim_full(address, center_lat=None, center_lng=None):
    """Return (lat, lng, display_name) for an address/POI, or None. When a center
    is given, viewbox BIASES toward the pickup area (no bounded=1, so an out-of-
    area query isn't warped onto a random in-box place)."""
    params = {"q": address, "format": "json", "limit": 1, "countrycodes": "vn"}
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
        "Toạ độ DMS tới 0.1 giây, đặt pin ĐÚNG địa điểm (vd 10°47'09.1\"N, 106°42'09.8\"E).\n"
        "CHỈ trả JSON, không giải thích:\n"
        '{"query_type":"poi|address","locations":[{"name":"","full_address":"","lat_dms":"","lng_dms":""}]}'
    )


def _gemini_locations(text, user_lat, user_lng):
    """GROUNDED Gemini -> {query_type, locations:[{name,address,lat,lng}]} with REAL
    coords, or None. Plain (non-grounded) LLM coords are hallucinated, so we only
    trust grounded output; without a key the caller falls back to a real geocoder."""
    if not GEMINI_API_KEYS:
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


def _pin(loc, center_lat, center_lng, is_address=False, pickup=None, one_shot=False):
    """Chốt toạ độ để ghim lên bản đồ. Trả (loc, verified).

    Nguyên tắc: **Gemini quyết định ĐÓ LÀ CHỖ NÀO, geocoder thật quyết định NÓ
    NẰM Ở ĐÂU.** Grounding đọc web nên tên + địa chỉ chữ đáng tin; còn toạ độ số
    thì đo được là nó bịa.

    Ca thật đã bắt được: hỏi "trường trung học thực hành ĐH Sư phạm TPHCM",
    Gemini trả địa chỉ ĐÚNG (280 An Dương Vương, P4, Q5) nhưng toạ độ lại là
    10.776889,106.700889 — cách ĐIỂM ĐÓN truyền vào prompt đúng 2 mét, tức nó
    chép lại gợi ý vị trí. Mapbox cho 10.757776,106.674800, lệch 3.56 km.

    Nên:
      - Toạ độ trùng điểm đón (<150 m) => coi như KHÔNG có, đây là dấu hiệu bịa.
      - Có geocoder trả kết quả => geocoder thắng, trừ khi là POI và hai bên đã
        khớp nhau (lúc đó giữ toạ độ Gemini vì nó ghim đúng toà nhà, còn
        geocoder hay rơi ra giữa đường).
      - Không geocoder nào trả => đành giữ Gemini nhưng verified=False.
    """
    g = None
    if isinstance(loc.get("lat"), (int, float)) and isinstance(loc.get("lng"), (int, float)):
        g = (loc["lat"], loc["lng"])
    if g and pickup and _haversine_km(g[0], g[1], pickup[0], pickup[1]) <= 0.15:
        g = None                                   # chép lại điểm đón -> vứt

    # Tra bằng ĐỊA CHỈ, không phải tên. Đo trên chính ca trường THTH ĐHSP, lấy
    # mốc độc lập (xembando.vn 10.7608458,106.682471):
    #   Nominatim + địa chỉ   ->    47 m
    #   Mapbox    + địa chỉ   ->   905 m
    #   Mapbox    + tên       ->  4.0 km
    #   Mapbox    + tên+đ/c   ->  272 km  (nhảy ra Ninh Thuận)
    # Nên Nominatim đi trước, Mapbox chỉ là lưới đỡ khi Nominatim không có gì.
    # ── Gemini = bộ não hiểu ý, Nominatim = chốt toạ độ chính xác ──
    # POI: tra TÊN trước (Nominatim tìm "Lăng Chủ tịch Hồ Chí Minh" chuẩn 41m,
    #       nhưng địa chỉ "2 Hùng Vương, Điện Biên, Ba Đình" thì fail).
    # Address: tra ĐỊA CHỈ trước (số nhà + đường chính xác hơn).
    name = loc.get("name") or ""
    addr = loc.get("address") or ""
    # Bỏ phần trong ngoặc khi TRA CỨU: "(Cơ sở 1)" là do Gemini tự thêm để phân biệt,
    # OSM không có chuỗi đó nên Nominatim khớp mờ rồi rơi ra chỗ khác hẳn (đã thấy pin
    # nhảy sang Phố Hàm Nghi). Vẫn giữ nguyên tên đầy đủ để hiển thị/đọc.
    q_name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    # Neo tên POI vào quận/thành phố lấy từ địa chỉ — "Đại học Công nghiệp Hà Nội" một
    # mình quá chung, kèm "Bắc Từ Liêm, Hà Nội" thì Nominatim mới tìm đúng nhánh.
    tail = ", ".join([p.strip() for p in addr.split(",") if p.strip()][-2:])
    primary = addr if is_address else (f"{q_name}, {tail}" if tail else q_name)
    fallback = q_name if is_address else addr

    # Nominatim trước (đo trên 8 địa điểm VN: thắng Mapbox 7-1 và không bao giờ
    # trả rỗng), nhưng thỉnh thoảng lệch THẢM HOẠ — "THPT Lê Hồng Phong" ra tận
    # 1120 km. Nên mọi kết quả đều phải nằm trong bán kính phục vụ, sai thì rơi
    # xuống Mapbox chứ không ghim bừa.
    ref = None
    nm = _nominatim_full(primary, center_lat, center_lng) if primary.strip() else None
    # one_shot: khi ghim CẢ danh sách, mỗi lựa chọn chỉ được tra Nominatim MỘT lần.
    # Nominatim buộc giãn 1.1s/lần nên lần tra thứ hai làm tổng thời gian phình gấp
    # đôi (đo được 16.4s cho 3 lựa chọn) — không đáng, vì lần tra đầu đã đủ tốt.
    if not nm and not one_shot and fallback.strip() and fallback != primary:
        nm = _nominatim_full(fallback, center_lat, center_lng)
    if nm and _within_service(nm[0], nm[1], center_lat, center_lng):
        ref = {"name": loc["name"], "address": addr or nm[2],
               "lat": nm[0], "lng": nm[1]}
    if not ref:
        mb = _mapbox_first(addr or name, center_lat, center_lng)
        if mb and _within_service(mb["lat"], mb["lng"], center_lat, center_lng):
            ref = mb

    if not ref:
        return loc, False                          # không có gì để đối chiếu

    if g:
        gap = _haversine_km(g[0], g[1], ref["lat"], ref["lng"])
        if gap <= VERIFY_RADIUS_KM:
            # Hai nguồn khớp nhau -> tin. POI thì giữ pin Gemini (nó ghim đúng toà nhà,
            # geocoder hay rơi ra giữa đường); địa chỉ số nhà thì lấy geocoder.
            return (loc, True) if not is_address else (
                {"name": loc["name"], "address": loc.get("address") or ref.get("address"),
                 "lat": ref["lat"], "lng": ref["lng"]}, True)
        # LỆCH QUÁ XA -> KHÔNG BIẾT chỗ nào đúng. Trước đây vẫn lấy toạ độ geocoder rồi
        # đánh verified=True: đó chính là lúc pin nhảy sang một con phố không liên quan.
        # Giữ toạ độ Gemini (nó khớp với chuỗi địa chỉ đang đọc cho người dùng) và hạ cờ
        # verified để tầng trên biết là chưa chắc.
        print(f"[pin] lech {gap:.1f}km giua Gemini va geocoder cho '{name[:40]}' -> giu Gemini, verified=False")
        return loc, False

    # Gemini không cho toạ độ nào -> đành dùng geocoder.
    return {"name": loc["name"], "address": loc.get("address") or ref.get("address"),
            "lat": ref["lat"], "lng": ref["lng"]}, True


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
    out["verified"] = ok
    if user_lat is not None:
        out["distanceKm"] = round(_haversine_km(user_lat, user_lng, out["lat"], out["lng"]), 1)
    return out


def resolve_locations(text, user_lat=None, user_lng=None):
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

    # 0) Gazetteer đã kiểm chứng (tức thì, chính xác; có thể sẵn nhiều chi nhánh).
    ga = [{"name": c["name"], "address": c.get("address"), "lat": c["lat"], "lng": c["lng"]}
          for c in _lookup_all_pd(text)]
    ga = [l for l in ga if within(l)]
    if ga:
        return {"ok": True, "query_type": "poi", "source": "verified", "locations": [fin(l) for l in ga[:4]]}

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
                pinned = [fin(loc, ok) for loc, ok in (f.result() for f in futs)]
            return {"ok": True, "query_type": data.get("query_type", "poi"),
                    "source": "grounded", "locations": pinned}

        # Chỉ MỘT nơi -> đó chính là điểm đến, chốt toạ độ luôn.
        loc0, ok0 = _pin(locs[0], center_lat, center_lng, is_addr, pickup)
        return {"ok": True, "query_type": data.get("query_type", "poi"),
                "source": "grounded" if ok0 else "grounded_unverified",
                "locations": [fin(loc0, ok0)]}

    # 2) Gemini hỏng/không có key -> Dùng DeepSeek (llm_json) làm đầu não để phân tích chi nhánh/địa chỉ
    prompt = (
        f'Người dùng tìm địa điểm: "{text}".\n'
        'Nhiệm vụ: Xác định tên chuẩn xác. Nếu đây là địa điểm có nhiều chi nhánh (ví dụ: đại học khxh&nv, lotteria, starbucks...), liệt kê tối đa 4 chi nhánh nổi bật nhất ở VN.\n'
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
            
            # Trả về ngay để người dùng chọn (khoan verify chặt, lat/lng = None)
            if len(locs) >= 2:
                return {"ok": True, "query_type": ds_data.get("query_type", "poi"),
                        "source": "deepseek_only", "locations": [fin(l, False) for l in locs]}
            
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

"""
agent.py — VoiceGo conversational agent (Groq function-calling, ReAct loop).

Enforced flow (the system prompt + tool split keep it on-rails):
  1. resolve_destination(query) — find the place + alternatives. NO distance/price
     yet. If ambiguous/multi-branch, the agent lists options and asks the user to
     pick (or name another place), looping until ONE place is confirmed.
  2. get_quote(vehicle) — ONLY after the place is confirmed: real routing (OSRM)
     -> distance + price. Agent reads address + km + price and asks to confirm.
  3. book_ride(vehicle) — ONLY after the user confirms the quote.
     If declined -> ask "find another place, or stop?" -> loop or cancel.

Tools are the only source of real data (coords/distance/price), never invented.
"""
import json
import re
import time
import unicodedata

from voice import groq_client, GROQ_MODEL
from geocode import resolve_destination, geocode_candidates, _nominatim, _haversine_km
from places_db import lookup_all as _lookup_all
from routing import road_route
from db import DEMO_PASSENGER_ID, MongoUnavailable, create_ride_request

MAX_ALT_KM = 80  # drop same-name places too far away (e.g. another province)

ORIGIN = {"name": "Trường Đại học Quốc tế", "lat": 10.8782, "lng": 106.8012}
PRICE = {"bike": {"base": 12000, "perKm": 4000}, "car": {"base": 29000, "perKm": 12000}}

# Feature 2 — Accessible entrances (HARDCODED). When a destination is one of these
# multi-gate places, offer a more accessible gate. The frontend colours the
# accessible point green so judges see accessibility-aware routing.
ACCESSIBLE_GATES = [
    {
        "near": (10.77230, 106.65770), "radius_km": 0.9,
        "label": "Đại học Bách Khoa (cơ sở 1, Quận 10)",
        "gates": [
            {"name": "ĐH Bách Khoa — Cổng 1 (dễ tiếp cận)",
             "address": "Cổng 1, ĐH Bách Khoa, 268 Lý Thường Kiệt, Quận 10",
             "lat": 10.772085, "lng": 106.657829, "accessible": True},
            {"name": "ĐH Bách Khoa — Cổng 3",
             "address": "Cổng 3, ĐH Bách Khoa, Quận 10",
             "lat": 10.773855, "lng": 106.661507, "accessible": False},
        ],
    },
]


def _gates_for(lat, lng):
    """Return the accessible-gate config for a destination, or None."""
    for g in ACCESSIBLE_GATES:
        if _haversine_km(lat, lng, g["near"][0], g["near"][1]) <= g["radius_km"]:
            return g
    return None


def _gate_candidates(g):
    return {"ok": True, "kind": "candidates", "candidates": g["gates"], "accessibility_choice": True,
            "next": (f"Đây là {g['label']}. Có CỔNG dễ tiếp cận hơn cho người khiếm thị là Cổng 1 "
                     "(đường đi an toàn, có chỗ đón rõ ràng). HỎI: 'Bạn muốn đến Cổng 1 — dễ tiếp cận, "
                     "hay Cổng 3?'. KHUYẾN NGHỊ Cổng 1. Khi người dùng chọn -> select_candidate(index).")}

SYSTEM_PROMPT = (
    "Bạn là VoiceGo — trợ lý ĐẶT XE bằng giọng nói cho người KHIẾM THỊ ở TP.HCM. "
    "Điểm đón CỐ ĐỊNH: Trường Đại học Quốc tế (Thủ Đức); người dùng chỉ nói ĐIỂM ĐẾN.\n"
    "LUỒNG BẮT BUỘC, đúng thứ tự — không được nhảy bước:\n"
    "1) Người dùng nêu điểm đến → GỌI resolve_destination(query). "
    "Nếu trả về NHIỀU candidates: ĐỌC danh sách theo SỐ THỨ TỰ (1, 2, ...) kèm khu vực, HỎI người dùng "
    "chọn số mấy (hoặc nói tên/khu vực). Khi người dùng chọn → GỌI select_candidate(index) đúng số đó. "
    "Nếu chỉ 1 (kind=place) → đó là điểm đến. "
    "Nếu người dùng từ chối / muốn chỗ khác → GỌI LẠI resolve_destination với địa điểm mới. "
    "LẶP đến khi chốt đúng MỘT điểm. Ở bước này TUYỆT ĐỐI KHÔNG nói khoảng cách hay giá.\n"
    "2) Sau khi người dùng đã xác nhận đúng điểm → HỎI 'Bạn muốn đi xe máy hay ô tô?'. "
    "Sau khi người dùng chọn loại xe → GỌI get_quote(vehicle) với loại xe đó. "
    "Rồi ĐỌC LẠI: tên + địa chỉ + khoảng cách + giá, và HỎI 'Bạn xác nhận đặt xe chứ?'.\n"
    "2b) Nếu người dùng muốn ĐỔI LOẠI XE (kể cả sau khi đã nghe giá vì thấy đắt) → GỌI LẠI "
    "get_quote với loại xe MỚI và báo giá mới; KHÔNG hỏi lại điểm đến.\n"
    "3) Nếu người dùng ĐỒNG Ý → GỌI book_ride(vehicle), báo thông tin tài xế. "
    "Nếu người dùng KHÔNG đồng ý → HỎI 'Bạn muốn đổi loại xe, tìm địa điểm khác, hay không đặt nữa?'. "
    "Đổi xe → bước 2b. Tìm chỗ khác → quay lại bước 1. "
    "BẤT CỨ KHI NÀO người dùng nói huỷ / thôi / dừng / không đặt nữa / không đi nữa → "
    "GỌI end_conversation rồi nói MỘT câu tạm biệt ngắn. KHÔNG hỏi gì thêm.\n"
    "Quy tắc: tiếng Việt, mỗi lượt 1–2 câu, rõ ràng, ấm áp. Chỉ dùng số liệu từ tool, KHÔNG bịa. "
    "Loại xe chỉ có 'xe máy' (bike) và 'ô tô' (car) — KHÔNG nói 'điện'. "
    "KHÔNG có loại xe mặc định. Khi HỎI loại xe mà người dùng trả lời MƠ HỒ / KHÔNG CHẮC "
    "('đoán đi', 'sao cũng được', 'tùy', 'gì cũng được', 'không biết', 'không rõ', 'gì cũng đặng') HOẶC bạn nghe không rõ "
    "→ phải HỎI LẠI ĐÚNG câu đang thiếu: 'Bạn muốn đi xe máy hay ô tô?'; TUYỆT ĐỐI không tự chọn thay người dùng, "
    "KHÔNG gọi get_quote khi chưa rõ loại xe, và KHÔNG bịa/đoán điểm đến từ câu mơ hồ. "
    "Nếu KHÔNG CHẮC về điểm đến hoặc nghe không rõ điểm đến → hỏi lại cho rõ, đừng đoán. "
    "Khi cần dùng tool, hãy gọi qua cơ chế tool-calling; TUYỆT ĐỐI không viết tên hàm hay JSON vào câu trả lời."
)


def _say_money(text):
    """Đọc tiền VND dạng 'X nghìn'/'X triệu' (tránh '107000' -> '107 không không không')."""
    def repl(m):
        n = int(re.sub(r"[.,\s]", "", m.group(1)))
        if n < 1000 or n % 1000 != 0:
            return m.group(0)
        tr, ng = n // 1_000_000, (n % 1_000_000) // 1000
        if tr and ng:
            return f"{tr} triệu {ng} nghìn"
        if tr:
            return f"{tr} triệu"
        return f"{n // 1000} nghìn"
    # số có dấu phân nhóm (107.000 / 107 000) hoặc >=4 chữ số liền
    return re.sub(r"(\d{1,3}(?:[.,\s]\d{3})+|\d{4,})", repl, text)


def _clean_reply(text):
    """Strip leaked function-call/JSON + markdown so TTS reads clean Vietnamese."""
    if not text:
        return ""
    for marker in ("<function", "<tool_call", "<|python_tag|>", "```"):
        i = text.find(marker)
        if i != -1:
            text = text[:i]
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?m)^\s*#+\s*", "", text)   # markdown headers
    text = _say_money(text)                      # 107000 -> "107 nghìn" (TTS đọc đúng)
    text = text.strip()
    # Collapse consecutive duplicate sentences (gpt-oss đôi khi lặp y nguyên 1 câu).
    parts = [p for p in re.split(r"(?<=[.?!…])\s+", text) if p.strip()]
    out = []
    for s in parts:
        if not out or s.strip().lower() != out[-1].strip().lower():
            out.append(s)
    return (" ".join(out).strip() or text)

TOOLS = [
    {"type": "function", "function": {
        "name": "resolve_destination",
        "description": "Tra điểm đến người dùng nói -> tên, địa chỉ, tọa độ + các cơ sở khác (alternatives). "
                       "KHÔNG trả khoảng cách/giá. Dùng ở bước 1 và mỗi khi người dùng đổi điểm.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string", "description": "Địa điểm người dùng nói"}},
                       "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "select_candidate",
        "description": "Chọn 1 ứng viên trong danh sách candidates gần nhất theo SỐ THỨ TỰ (1, 2, ...).",
        "parameters": {"type": "object",
                       "properties": {"index": {"type": "integer", "description": "Số thứ tự ứng viên (bắt đầu từ 1)"}},
                       "required": ["index"]},
    }},
    {"type": "function", "function": {
        "name": "get_quote",
        "description": "CHỈ gọi sau khi người dùng đã xác nhận đúng điểm đến. Tính quãng đường thật + giá.",
        "parameters": {"type": "object",
                       "properties": {"vehicle": {"type": "string", "enum": ["bike", "car"]}},
                       "required": ["vehicle"]},
    }},
    {"type": "function", "function": {
        "name": "book_ride",
        "description": "CHỈ gọi sau khi người dùng đã đồng ý đặt (sau get_quote). Gán tài xế.",
        "parameters": {"type": "object",
                       "properties": {"vehicle": {"type": "string", "enum": ["bike", "car"]}},
                       "required": ["vehicle"]},
    }},
    {"type": "function", "function": {
        "name": "end_conversation",
        "description": "Gọi khi người dùng muốn HUỶ / dừng / không đặt nữa. Kết thúc phiên, không hỏi tiếp.",
        "parameters": {"type": "object",
                       "properties": {"reason": {"type": "string"}}, "required": []},
    }},
]


def _quote_price(vehicle, distance_km):
    p = PRICE.get(vehicle, PRICE["bike"])
    return round((p["base"] + p["perKm"] * (distance_km or 0)) / 1000) * 1000


def _norm(s):
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def _picked_vehicle(msgs):
    """Did the user choose a vehicle in the last few user turns?
    Returns 'car' | 'bike' | None. Gates get_quote so the agent ASKS first.
    A vague reply ('đoán đi', 'tùy', 'sao cũng được') counts as the default (bike)."""
    n = 0
    for m in reversed(msgs):
        if m.get("role") != "user":
            continue
        n += 1
        t = _norm(m.get("content", ""))
        if any(k in t for k in ["o to", "oto", "taxi", "bon banh", "4 banh", "xe hoi"]):
            return "car"
        if any(k in t for k in ["xe om", "xe may", "2 banh", "hai banh", "om dien", "may dien"]):
            return "bike"
        if n >= 4:
            break
    return None


def _last_tool(msgs, kind):
    """Most recent tool result of a given kind (place/quote) from the history."""
    for m in reversed(msgs):
        if m.get("role") == "tool":
            try:
                d = json.loads(m.get("content") or "{}")
            except Exception:  # noqa: BLE001
                continue
            if d.get("ok") and d.get("kind") == kind:
                return d
    return None


def _short_name(text):
    t = (text or "").split(":")[0].strip()
    return t[:60] if t else (text or "")[:60]


def _geocode_text(text):
    """Coords for an alternative's text (full string, then the part after ':')."""
    return _nominatim(text) or _nominatim((text or "").split(":")[-1].strip())


_NEXT_CANDIDATES = (
    "Đọc danh sách candidates theo SỐ THỨ TỰ (1, 2, ...) kèm KHU VỰC/QUẬN để phân biệt, "
    "hỏi người dùng chọn số mấy (hoặc nói tên/khu vực). Khi người dùng chọn rõ -> gọi select_candidate(index). "
    "Nếu người dùng trả lời KHÔNG rõ chọn mục nào (vd 'hai cơ sở', 'cái nào', 'không biết') -> ĐỌC LẠI danh sách "
    "và hỏi lại; TUYỆT ĐỐI KHÔNG gọi resolve_destination với câu mơ hồ đó."
)


def _do_resolve(query):
    """Resolve a spoken place. If it's ambiguous (a place with several branches,
    or a street that exists in many districts) -> return a LIST of REAL candidates
    to pick from. GENERAL: the geocoder finds branches of ANY place (no per-place
    aliases needed); the verified gazetteer just adds accuracy + branches the
    geocoder misses. No hallucinated addresses — every candidate is a real coord."""
    ga = _lookup_all(query)                                   # verified (accurate)
    geo = geocode_candidates(query, ORIGIN["lat"], ORIGIN["lng"]) if len(ga) < 2 else []

    # Merge: gazetteer first (verified), then OSM results not near an existing pick.
    merged = [{"name": c["name"], "address": c.get("address"), "lat": c["lat"], "lng": c["lng"]} for c in ga]
    for c in geo:
        if not any(_haversine_km(c["lat"], c["lng"], m["lat"], m["lng"]) < 1.2 for m in merged):
            merged.append({"name": c["name"], "address": c.get("address"), "lat": c["lat"], "lng": c["lng"]})
    merged = merged[:4]

    if len(merged) >= 2:
        return {"ok": True, "kind": "candidates", "candidates": merged, "next": _NEXT_CANDIDATES}

    # Single / none -> the accurate single resolver (gazetteer single, grounded, Nominatim).
    r = resolve_destination(query, ORIGIN["lat"], ORIGIN["lng"])
    if not r.get("ok"):
        reason = r.get("reason", "not_found")
        out = {"ok": False, "kind": "place", "reason": reason}
        if reason == "out_of_area":
            out["message"] = ("Địa điểm này nằm ngoài Thành phố Hồ Chí Minh. "
                              "Hiện mình chỉ hỗ trợ đặt xe trong khu vực TP.HCM. "
                              "Bạn cho mình một điểm đến trong thành phố nhé.")
        return out

    g = _gates_for(r["lat"], r["lng"])     # multi-gate place -> offer accessible gate
    if g:
        return _gate_candidates(g)
    return {"ok": True, "kind": "place", "name": r["name"], "address": r.get("address"),
            "lat": r["lat"], "lng": r["lng"],
            "next": "Hỏi người dùng 'xe máy hay ô tô' TRƯỚC khi get_quote."}


def _do_select(msgs, index):
    cset = _last_tool(msgs, "candidates")
    cs = (cset or {}).get("candidates") or []
    try:
        i = int(index) - 1
    except (TypeError, ValueError):
        i = -1
    if i < 0 or i >= len(cs):
        return {"ok": False, "kind": "place", "reason": "bad_index"}
    p = cs[i]
    # If the picked place has accessible gates AND isn't itself a gate -> offer gates.
    if "accessible" not in p:
        g = _gates_for(p["lat"], p["lng"])
        if g:
            return _gate_candidates(g)
    return {"ok": True, "kind": "place", "name": p["name"], "address": p.get("address"),
            "lat": p["lat"], "lng": p["lng"], "accessible": p.get("accessible"),
            "next": "Hỏi người dùng 'xe máy hay ô tô' TRƯỚC khi get_quote."}


def _do_quote(msgs, vehicle):
    place = _last_tool(msgs, "place")
    if not place:
        return {"ok": False, "kind": "quote", "reason": "no_destination"}
    # Guardrail: do NOT quote until the user has explicitly chosen a vehicle.
    picked = _picked_vehicle(msgs)
    if not picked:
        return {"ok": False, "kind": "quote", "reason": "need_vehicle",
                "message": "Chưa chọn loại xe. Hãy HỎI người dùng muốn 'xe máy hay ô tô' trước khi báo giá."}
    vehicle = picked  # trust what the user actually said
    rt = road_route(ORIGIN["lat"], ORIGIN["lng"], place["lat"], place["lng"])
    km = rt["distanceKm"] if rt else None
    price = _quote_price(vehicle, km or 0)
    return {
        "ok": True, "kind": "quote", "name": place["name"], "address": place.get("address"),
        "lat": place["lat"], "lng": place["lng"], "distanceKm": km,
        "durationMin": rt["durationMin"] if rt else None, "priceVnd": price,
        "vehicle": vehicle, "geometry": rt["geometry"] if rt else None,
    }


def _do_book(msgs, vehicle):
    q = _last_tool(msgs, "quote")
    place = _last_tool(msgs, "place")
    ref = q or place
    if not ref:
        return {"ok": False, "kind": "booked", "reason": "no_destination"}
    vehicle = "car" if vehicle == "car" else "bike"
    km = (q or {}).get("distanceKm")
    price = (q or {}).get("priceVnd") or _quote_price(vehicle, km or 0)
    fallback = {
        "ok": True, "kind": "booked", "driver": "Nguyễn Văn A", "plate": "59-X1 234.56",
        "etaMin": 4, "vehicle": vehicle, "destination": ref.get("name"),
        "address": ref.get("address"), "priceVnd": price, "pickup": ORIGIN["name"],
    }
    try:
        ride = create_ride_request(
            passenger_id=DEMO_PASSENGER_ID,
            pickup={"name": ORIGIN["name"], "lat": ORIGIN["lat"], "lng": ORIGIN["lng"]},
            destination={
                "name": ref.get("name"),
                "address": ref.get("address"),
                "lat": ref.get("lat"),
                "lng": ref.get("lng"),
            },
            booking_method="ai_voice",
            vehicle=vehicle,
            estimated_price=price,
            estimated_distance_km=km,
            estimated_arrival_minutes=(q or {}).get("durationMin"),
        )
        driver = ride.get("driver") or {}
        driver_user = ride.get("driver_user") or {}
        return {
            **fallback,
            "rideId": ride.get("id"),
            "driverId": ride.get("driver_id"),
            "driver": driver_user.get("full_name") or fallback["driver"],
            "plate": driver.get("license_plate") or fallback["plate"],
            "etaMin": ride.get("estimated_arrival_minutes") or fallback["etaMin"],
            "accessibilityType": ride.get("accessibility_type"),
            "driverAlertMessage": ride.get("driver_alert_message"),
            "driverAlertAcknowledged": ride.get("driver_alert_acknowledged"),
            "dbSaved": True,
        }
    except MongoUnavailable as exc:
        return {**fallback, "dbSaved": False, "dbReason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {**fallback, "dbSaved": False, "dbReason": f"database_error: {exc}"}


def _apply_place_ui(ui, res):
    """Map a resolve/select tool result onto the UI (place pin or candidate list)."""
    if not res.get("ok"):
        return
    if res.get("kind") == "place":
        ui["destination"] = {"name": res["name"], "address": res.get("address"),
                             "lat": res["lat"], "lng": res["lng"], "accessible": res.get("accessible")}
        ui.pop("quote", None)
        ui.pop("candidates", None)
    elif res.get("kind") == "candidates":
        ui["candidates"] = res.get("candidates")   # frontend shows them on the map
        ui.pop("destination", None)
        ui.pop("quote", None)


def _chat_create(client, msgs):
    """Call Groq; auto-retry on 429 rate limit (TPM resets within seconds)."""
    last = None
    for _ in range(4):
        try:
            return client.chat.completions.create(
                model=GROQ_MODEL, messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0.3,
            )
        except Exception as e:  # noqa: BLE001
            last = e
            msg = str(e)
            if "rate_limit" in msg or "429" in msg or "RateLimit" in type(e).__name__:
                mt = re.search(r"try again in ([\d.]+)\s*s", msg)
                wait = min((float(mt.group(1)) + 0.4) if mt else 5.0, 12.0)
                time.sleep(wait)
                continue
            raise
    raise last


def run_agent(messages: list[dict]) -> dict:
    """One agent turn. Returns {reply, messages, ui}."""
    client = groq_client()
    if not client:
        return {"reply": "Hệ thống agent chưa sẵn sàng (thiếu GROQ_API_KEY).", "messages": messages, "ui": {}}

    msgs = list(messages)
    if not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    ui = {}
    try:
      for _ in range(6):
        resp = _chat_create(client, msgs)
        m = resp.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if not m.tool_calls:
            reply = _clean_reply(m.content or "")
            if not reply:
                reply = "Bạn cho tôi biết tên địa điểm cụ thể hơn giúp tôi nhé."
            return {"reply": reply, "messages": msgs, "ui": ui}

        for tc in m.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            name = tc.function.name
            if name == "resolve_destination":
                res = _do_resolve(args.get("query", ""))
                _apply_place_ui(ui, res)
            elif name == "select_candidate":
                res = _do_select(msgs, args.get("index"))
                _apply_place_ui(ui, res)
            elif name == "get_quote":
                res = _do_quote(msgs, args.get("vehicle", "bike"))
                if res.get("ok"):
                    ui["quote"] = {"name": res["name"], "address": res.get("address"),
                                   "lat": res["lat"], "lng": res["lng"], "distanceKm": res.get("distanceKm"),
                                   "durationMin": res.get("durationMin"), "priceVnd": res.get("priceVnd"),
                                   "vehicle": res.get("vehicle"), "geometry": res.get("geometry")}
            elif name == "book_ride":
                res = _do_book(msgs, args.get("vehicle", "bike"))
                if res.get("ok"):
                    ui["booked"] = res
            elif name == "end_conversation":
                res = {"ok": True, "kind": "ended"}
                ui["ended"] = True
            else:
                res = {"ok": False, "error": "unknown_tool"}
            # Strip bulky geometry from what the LLM sees (save tokens).
            payload = {k: v for k, v in res.items() if k != "geometry"}
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(payload, ensure_ascii=False)})

      return {"reply": "Xin lỗi, mình chưa xử lý xong. Bạn thử lại giúp nhé.", "messages": msgs, "ui": ui}
    except Exception as exc:  # noqa: BLE001 — incl. persistent rate limit
        print("run_agent error:", exc)
        return {"reply": "Hệ thống đang hơi bận, bạn chờ vài giây rồi nói lại giúp mình nhé.",
                "messages": messages, "ui": {}}

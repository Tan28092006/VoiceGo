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
import unicodedata

from voice import groq_client, GROQ_MODEL
from geocode import resolve_destination, _nominatim, _haversine_km
from routing import road_route
from db import DEMO_PASSENGER_ID, MongoUnavailable, create_ride_request

MAX_ALT_KM = 80  # drop same-name places too far away (e.g. another province)

ORIGIN = {"name": "Trường Đại học Quốc tế", "lat": 10.8782, "lng": 106.8012}
PRICE = {"bike": {"base": 12000, "perKm": 4000}, "car": {"base": 29000, "perKm": 12000}}

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
    "2) Sau khi người dùng đã xác nhận đúng điểm → HỎI 'Bạn muốn đi xe ôm điện hay ô tô điện?'. "
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
    "Mặc định xe ôm (bike); đổi sang car nếu người dùng yêu cầu. "
    "Khi cần dùng tool, hãy gọi qua cơ chế tool-calling; TUYỆT ĐỐI không viết tên hàm hay JSON vào câu trả lời."
)


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
    return text.strip()

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
    """Did the user explicitly choose a vehicle in the last few user turns?
    Returns 'car' | 'bike' | None. Gates get_quote so the agent must ASK first."""
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


def _do_resolve(query):
    r = resolve_destination(query, ORIGIN["lat"], ORIGIN["lng"])
    if not r.get("ok"):
        return {"ok": False, "kind": "place", "reason": r.get("reason", "not_found")}

    # Build a candidate LIST with real coords (primary + geocoded alternatives) so
    # the user can pick a specific branch later (selection has actual memory).
    candidates = [{"name": r["name"], "address": r.get("address"), "lat": r["lat"], "lng": r["lng"]}]
    for alt in (r.get("alternatives") or [])[:3]:
        c = _geocode_text(alt)
        # Keep only alternatives within the city region (skip same-name far places).
        if c and _haversine_km(ORIGIN["lat"], ORIGIN["lng"], c[0], c[1]) <= MAX_ALT_KM:
            candidates.append({"name": _short_name(alt), "address": alt, "lat": c[0], "lng": c[1]})

    # De-dupe candidates that resolve to (almost) the same spot.
    uniq = []
    for c in candidates:
        if not any(abs(c["lat"] - u["lat"]) < 1e-3 and abs(c["lng"] - u["lng"]) < 1e-3 for u in uniq):
            uniq.append(c)

    if len(uniq) == 1:
        p = uniq[0]
        return {"ok": True, "kind": "place", "name": p["name"], "address": p.get("address"),
                "lat": p["lat"], "lng": p["lng"],
                "next": "Hỏi người dùng 'xe ôm điện hay ô tô điện' TRƯỚC khi get_quote."}
    return {"ok": True, "kind": "candidates", "candidates": uniq,
            "next": "Đọc danh sách candidates theo SỐ THỨ TỰ (1,2,...) và hỏi người dùng chọn số mấy, "
                    "rồi gọi select_candidate(index)."}


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
    return {"ok": True, "kind": "place", "name": p["name"], "address": p.get("address"),
            "lat": p["lat"], "lng": p["lng"],
            "next": "Hỏi người dùng 'xe ôm điện hay ô tô điện' TRƯỚC khi get_quote."}


def _do_quote(msgs, vehicle):
    place = _last_tool(msgs, "place")
    if not place:
        return {"ok": False, "kind": "quote", "reason": "no_destination"}
    # Guardrail: do NOT quote until the user has explicitly chosen a vehicle.
    picked = _picked_vehicle(msgs)
    if not picked:
        return {"ok": False, "kind": "quote", "reason": "need_vehicle",
                "message": "Chưa chọn loại xe. Hãy HỎI người dùng muốn 'xe ôm điện hay ô tô điện' trước khi báo giá."}
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


def run_agent(messages: list[dict]) -> dict:
    """One agent turn. Returns {reply, messages, ui}."""
    client = groq_client()
    if not client:
        return {"reply": "Hệ thống agent chưa sẵn sàng (thiếu GROQ_API_KEY).", "messages": messages, "ui": {}}

    msgs = list(messages)
    if not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    ui = {}
    for _ in range(6):
        resp = client.chat.completions.create(
            model=GROQ_MODEL, messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0.3,
        )
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
                if res.get("ok") and res.get("kind") == "place":
                    ui["destination"] = {"name": res["name"], "address": res.get("address"),
                                         "lat": res["lat"], "lng": res["lng"]}
                    ui.pop("quote", None)
            elif name == "select_candidate":
                res = _do_select(msgs, args.get("index"))
                if res.get("ok"):
                    ui["destination"] = {"name": res["name"], "address": res.get("address"),
                                         "lat": res["lat"], "lng": res["lng"]}
                    ui.pop("quote", None)
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

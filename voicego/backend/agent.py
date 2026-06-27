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

from voice import groq_client, GROQ_MODEL
from geocode import resolve_destination
from routing import road_route

ORIGIN = {"name": "Trường Đại học Quốc tế", "lat": 10.8782, "lng": 106.8012}
PRICE = {"bike": {"base": 12000, "perKm": 4000}, "car": {"base": 29000, "perKm": 12000}}

SYSTEM_PROMPT = (
    "Bạn là VoiceGo — trợ lý ĐẶT XE bằng giọng nói cho người KHIẾM THỊ ở TP.HCM. "
    "Điểm đón CỐ ĐỊNH: Trường Đại học Quốc tế (Thủ Đức); người dùng chỉ nói ĐIỂM ĐẾN.\n"
    "LUỒNG BẮT BUỘC, đúng thứ tự — không được nhảy bước:\n"
    "1) Người dùng nêu điểm đến → GỌI resolve_destination(query). "
    "Nếu có nhiều cơ sở (alternatives) hoặc chưa chắc: ĐỌC RÕ các lựa chọn và HỎI người dùng chọn "
    "cái nào, hoặc nói địa điểm khác. LẶP LẠI resolve cho đến khi người dùng XÁC NHẬN đúng MỘT điểm. "
    "Ở bước này TUYỆT ĐỐI KHÔNG nói khoảng cách hay giá.\n"
    "2) Sau khi người dùng đã xác nhận đúng điểm → GỌI get_quote(vehicle). "
    "Rồi ĐỌC LẠI: tên + địa chỉ + khoảng cách + giá, và HỎI 'Bạn xác nhận đặt xe chứ?'.\n"
    "3) Nếu người dùng ĐỒNG Ý → GỌI book_ride(vehicle), báo thông tin tài xế. "
    "Nếu người dùng KHÔNG đồng ý → HỎI 'Bạn muốn tìm địa điểm khác, hay không đặt nữa?'. "
    "Muốn tìm khác → quay lại bước 1. Không đặt nữa → nói lời tạm biệt lịch sự và DỪNG (đừng gọi tool nữa).\n"
    "Quy tắc: tiếng Việt, mỗi lượt 1–2 câu, rõ ràng, ấm áp. Chỉ dùng số liệu từ tool, KHÔNG bịa. "
    "Mặc định xe ôm điện (bike); đổi sang car nếu người dùng yêu cầu."
)

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
]


def _quote_price(vehicle, distance_km):
    p = PRICE.get(vehicle, PRICE["bike"])
    return round((p["base"] + p["perKm"] * (distance_km or 0)) / 1000) * 1000


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


def _do_resolve(query):
    r = resolve_destination(query, ORIGIN["lat"], ORIGIN["lng"])
    if not r.get("ok"):
        return {"ok": False, "kind": "place", "reason": r.get("reason", "not_found")}
    return {
        "ok": True, "kind": "place", "name": r["name"], "address": r.get("address"),
        "lat": r["lat"], "lng": r["lng"], "alternatives": r.get("alternatives", []),
    }


def _do_quote(msgs, vehicle):
    place = _last_tool(msgs, "place")
    if not place:
        return {"ok": False, "kind": "quote", "reason": "no_destination"}
    vehicle = "car" if vehicle == "car" else "bike"
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
    return {
        "ok": True, "kind": "booked", "driver": "Nguyễn Văn A", "plate": "59-X1 234.56",
        "etaMin": 4, "vehicle": vehicle, "destination": ref.get("name"),
        "address": ref.get("address"), "priceVnd": price, "pickup": ORIGIN["name"],
    }


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
            return {"reply": m.content or "", "messages": msgs, "ui": ui}

        for tc in m.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            name = tc.function.name
            if name == "resolve_destination":
                res = _do_resolve(args.get("query", ""))
                if res.get("ok"):
                    ui["destination"] = {"name": res["name"], "address": res.get("address"),
                                         "lat": res["lat"], "lng": res["lng"]}
                    ui.pop("quote", None)  # new place -> drop any old quote/route
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
            else:
                res = {"ok": False, "error": "unknown_tool"}
            # Strip bulky geometry from what the LLM sees (save tokens).
            payload = {k: v for k, v in res.items() if k != "geometry"}
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(payload, ensure_ascii=False)})

    return {"reply": "Xin lỗi, mình chưa xử lý xong. Bạn thử lại giúp nhé.", "messages": msgs, "ui": ui}

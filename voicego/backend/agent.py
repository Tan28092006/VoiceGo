"""
agent.py — VoiceGo conversational agent (Groq function-calling).

The LLM drives the whole interaction: it decides when to look up a destination,
when to ask the user to clarify (ambiguous / multi-branch places), and when to
actually book — by calling tools. Tools are the only source of real data
(addresses/coords from the geocoder, never invented by the model).
"""
import json

from voice import groq_client, GROQ_MODEL
from geocode import resolve_destination
from routing import road_route

# Fixed pickup (demo has no live GPS): International University, Thủ Đức.
ORIGIN = {"name": "Trường Đại học Quốc tế", "lat": 10.8782, "lng": 106.8012}

PRICE = {"bike": {"base": 12000, "perKm": 4000}, "car": {"base": 29000, "perKm": 12000}}

SYSTEM_PROMPT = (
    "Bạn là VoiceGo — trợ lý ĐẶT XE bằng giọng nói cho người KHIẾM THỊ ở TP.HCM. "
    "Điểm đón CỐ ĐỊNH: Trường Đại học Quốc tế (Thủ Đức); người dùng chỉ cần nói ĐIỂM ĐẾN.\n"
    "Quy tắc:\n"
    "- Nói tiếng Việt, NGẮN GỌN, ấm áp; mỗi lượt 1–2 câu.\n"
    "- Khi người dùng nêu điểm đến: GỌI tool resolve_destination để tra địa chỉ thật.\n"
    "- Nếu kết quả mơ hồ hoặc có NHIỀU cơ sở (alternatives): HỎI LẠI, nêu rõ các lựa chọn để người dùng chọn.\n"
    "- Nếu rõ ràng: ĐỌC LẠI tên + địa chỉ + khoảng cách + GIÁ ƯỚC TÍNH, rồi HỎI XÁC NHẬN.\n"
    "- CHỈ gọi tool book_ride SAU KHI người dùng đã ĐỒNG Ý.\n"
    "- Loại xe mặc định là xe ôm điện (bike); chỉ đổi sang ô tô (car) nếu người dùng yêu cầu.\n"
    "- TUYỆT ĐỐI không bịa địa chỉ/tọa độ/giá — chỉ dùng số liệu từ tool.\n"
    "- Giá: bike = 12.000 + 4.000/km; car = 29.000 + 12.000/km (tool tự tính)."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_destination",
            "description": "Tra địa chỉ thật + tọa độ của điểm đến người dùng nói. "
                           "Trả về tên, địa chỉ, khoảng cách (km) từ điểm đón, và các cơ sở khác nếu có.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Tên/địa điểm người dùng nói"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_ride",
            "description": "Đặt xe sau khi người dùng đã đồng ý. Tính giá và gán tài xế.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "vehicle": {"type": "string", "enum": ["bike", "car"]},
                    "distance_km": {"type": "number", "description": "Khoảng cách từ resolve_destination"},
                },
                "required": ["destination", "vehicle", "distance_km"],
            },
        },
    },
]


def _quote(vehicle, distance_km):
    p = PRICE.get(vehicle, PRICE["bike"])
    return round((p["base"] + p["perKm"] * distance_km) / 1000) * 1000


def _tool_resolve(query):
    r = resolve_destination(query, ORIGIN["lat"], ORIGIN["lng"])
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason", "not_found")}
    # Real driving distance + road geometry (OSRM); fall back to straight-line.
    rt = road_route(ORIGIN["lat"], ORIGIN["lng"], r["lat"], r["lng"])
    km = rt["distanceKm"] if rt else r.get("distanceKm")
    return {
        "ok": True, "name": r["name"], "address": r.get("address"),
        "lat": r["lat"], "lng": r["lng"], "distanceKm": km,
        "durationMin": rt["durationMin"] if rt else None,
        "alternatives": r.get("alternatives", []),
        "geometry": rt["geometry"] if rt else None,
    }


def _tool_book(destination, vehicle, distance_km):
    vehicle = "car" if vehicle == "car" else "bike"
    price = _quote(vehicle, float(distance_km or 0))
    return {
        "ok": True, "driver": "Nguyễn Văn A", "plate": "59-X1 234.56", "etaMin": 4,
        "vehicle": vehicle, "destination": destination, "priceVnd": price,
        "pickup": ORIGIN["name"],
    }


def run_agent(messages: list[dict]) -> dict:
    """
    One agent turn. `messages` = full conversation so far (client-maintained).
    Returns {reply, messages, ui}. `ui` carries side-effects for the frontend
    (destination to pin on the map, booking result).
    """
    client = groq_client()
    if not client:
        return {"reply": "Hệ thống agent chưa sẵn sàng (thiếu GROQ_API_KEY).", "messages": messages, "ui": {}}

    msgs = list(messages)
    if not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    ui = {}
    for _ in range(5):  # allow a few tool round-trips
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
            if tc.function.name == "resolve_destination":
                res = _tool_resolve(args.get("query", ""))
                if res.get("ok"):
                    ui["destination"] = {
                        "name": res["name"], "address": res.get("address"),
                        "lat": res["lat"], "lng": res["lng"], "distanceKm": res.get("distanceKm"),
                        "durationMin": res.get("durationMin"), "geometry": res.get("geometry"),
                    }
            elif tc.function.name == "book_ride":
                res = _tool_book(args.get("destination", ""), args.get("vehicle", "bike"), args.get("distance_km", 0))
                ui["booked"] = res
            else:
                res = {"error": "unknown_tool"}
            # Strip bulky geometry from the message handed back to the LLM (tokens).
            tool_payload = {k: v for k, v in res.items() if k != "geometry"}
            msgs.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(tool_payload, ensure_ascii=False),
            })

    return {"reply": "Xin lỗi, mình chưa xử lý xong. Bạn thử lại giúp nhé.", "messages": msgs, "ui": ui}

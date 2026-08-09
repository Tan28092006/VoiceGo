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

from voice import llm_client, LLM_MODEL
from geocode import (resolve_locations, verify_location, geocode_query,
                     _nominatim, _haversine_km)
from places_db import lookup_all as _lookup_all
from routing import road_route
from db import DEMO_PASSENGER_ID, MongoUnavailable, create_ride_request, find_gate_group

MAX_ALT_KM = 80  # drop same-name places too far away (e.g. another province)

# Fallback pickup when the rider's GPS is unavailable (Trường Đại học Quốc tế).
# Real bookings use the GPS coords the client sends with each turn.
# Toạ độ bộ tra bản đồ trả về mà cách toạ độ Gemini ước lượng xa hơn mức này thì coi như
# tra trượt sang nơi khác, không phải sai số. Nới rộng hơn sai số thật của Gemini (~2.5km).
PIN_SANITY_KM = 5.0

# Ghi chú kỹ thuật trả kèm cho agent. Phải nói rõ là nội bộ: có lượt nó đọc thẳng
# "hệ thống vẫn báo cảnh báo nhưng toạ độ đã được chốt, cách 9.6km" ra cho người dùng.
INTERNAL = (" ĐÂY LÀ GHI CHÚ NỘI BỘ, KHÔNG PHẢI NỘI DUNG ĐỂ ĐỌC. Câu nói ra phải BẮT ĐẦU "
            "NGAY bằng nội dung dành cho người dùng, KHÔNG mở đầu bằng việc mình vừa làm "
            "('đã chốt toạ độ', 'giờ tôi đọc danh sách'...), KHÔNG nhắc toạ độ, cảnh báo, "
            "ki-lô-mét hay chuyện tra bản đồ.")

DEFAULT_PICKUP = {"name": "Trường Đại học Quốc tế", "lat": 10.8782, "lng": 106.8012}
PRICE = {"bike": {"base": 12000, "perKm": 4000}, "car": {"base": 29000, "perKm": 12000}}


def _pickup(pickup):
    """Normalize the client-sent pickup to {name,lat,lng}; fall back to DEFAULT_PICKUP
    when GPS is missing/invalid so quoting + routing always have an origin."""
    p = pickup or {}
    lat, lng = p.get("lat"), p.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return {"name": p.get("name") or "Vị trí của bạn", "lat": float(lat), "lng": float(lng)}
    return dict(DEFAULT_PICKUP)


# Feature 2 — Accessible entrances. Multi-gate places (with a more accessible
# gate for visually-impaired riders) live in the DB (accessible_gates), so more
# places can be added without code changes. The frontend colours the accessible
# point green so judges see accessibility-aware routing.
def _gates_for(lat, lng):
    """Return the accessible-gate group for a destination (from DB), or None."""
    return find_gate_group(lat, lng)


def _gate_candidates(g):
    """Offer a multi-entrance place's gates, recommending the accessible one.
    The prompt text is derived from the data — no hardcoded gate names."""
    gates = g.get("gates") or []
    accessible = next((x for x in gates if x.get("accessible")), None)
    acc_name = (accessible or (gates[0] if gates else {})).get("name", "cổng dễ tiếp cận")
    return {"ok": True, "kind": "candidates", "candidates": gates, "accessibility_choice": True,
            "next": (f"Đây là {g.get('label', 'địa điểm này')}. Có lối vào dễ tiếp cận hơn cho người "
                     f"khiếm thị: {acc_name}. ĐỌC danh sách các cổng theo SỐ THỨ TỰ kèm mô tả, HỎI người "
                     "dùng chọn cổng nào và KHUYẾN NGHỊ cổng dễ tiếp cận. "
                     "Khi người dùng chọn -> select_candidate(index).")}

SYSTEM_PROMPT = (
    "Bạn là VoiceGo — trợ lý ĐẶT XE bằng giọng nói cho người KHIẾM THỊ. "
    "Điểm đón là VỊ TRÍ HIỆN TẠI của người dùng (lấy từ GPS); người dùng chỉ nói ĐIỂM ĐẾN.\n"
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
    "ĐỘ DÀI: mỗi lượt 2–3 câu, khoảng 30–45 TỪ. Đủ dài để nghe tự nhiên và lịch sự, "
    "nhưng KHÔNG lan man — người khiếm thị phải ngồi nghe hết, và câu càng dài thì càng "
    "lâu mới ra tiếng.\n"
    "Cách nói vừa đủ:\n"
    "- Địa chỉ: đọc TÊN + ĐƯỜNG + QUẬN/HUYỆN (và tỉnh/thành nếu khác nơi người dùng "
    "đang đứng) — đủ để người khiếm thị nhận ra đó là chỗ nào. Chỉ BỎ 'Việt Nam' và mã "
    "bưu chính. Vd 'Đại học Công nghiệp Hà Nội, 298 Cầu Diễn, Bắc Từ Liêm'.\n"
    "- Nhiều cơ sở: nêu tên địa điểm MỘT lần rồi liệt kê theo label, ĐỌC ĐỦ label — "
    "nghe 'Phủ Lý' không thôi thì không biết đó là tỉnh khác. Vd 'Đại học Công nghiệp "
    "Hà Nội có 3 cơ sở: một, 298 Cầu Diễn, Bắc Từ Liêm; hai, Tây Tựu, Bắc Từ Liêm; ba, "
    "Lê Hồng Phong, Phủ Lý, Hà Nam. Bạn muốn đến cơ sở số mấy?'\n"
    "- Báo giá: nói đủ quãng đường + giá + loại xe rồi mới hỏi xác nhận. Vd 'Từ chỗ bạn "
    "tới Chợ Bến Thành khoảng 8 ki-lô-mét, giá 44 nghìn đồng bằng xe máy. Bạn xác nhận "
    "đặt xe nhé?'\n"
    "- Được phép mở đầu ẤM ÁP bằng một cụm ngắn ('Mình tìm được rồi', 'Được rồi'), "
    "nhưng KHÔNG kể lại việc mình vừa làm và KHÔNG tóm tắt lại lượt trước.\n"
    "Quy tắc: tiếng Việt, rõ ràng, ấm áp. Chỉ dùng số liệu từ tool, KHÔNG bịa. "
    "Loại xe chỉ có 'xe máy' (bike) và 'ô tô' (car) — KHÔNG nói 'điện'. "
    "KHÔNG có loại xe mặc định. Khi HỎI loại xe mà người dùng trả lời MƠ HỒ / KHÔNG CHẮC "
    "('đoán đi', 'sao cũng được', 'tùy', 'gì cũng được', 'không biết', 'không rõ', 'gì cũng đặng') HOẶC bạn nghe không rõ "
    "→ phải HỎI LẠI ĐÚNG câu đang thiếu: 'Bạn muốn đi xe máy hay ô tô?'; TUYỆT ĐỐI không tự chọn thay người dùng, "
    "KHÔNG gọi get_quote khi chưa rõ loại xe, và KHÔNG bịa/đoán điểm đến từ câu mơ hồ. "
    "Nếu KHÔNG CHẮC về điểm đến hoặc nghe không rõ điểm đến → hỏi lại cho rõ, đừng đoán. Bổ sung thêm thông tin người dùng thêm vào nếu có như Quận, thành phố, cơ sở... vào khi gọi GỌI resolve_destination(query) lại để có được điểm đến chính xác hơn"
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
                       "properties": {"query": {"type": "string", "description":
                           "Địa điểm cần tra, do BẠN soạn — không cần bê nguyên câu người dùng nói. "
                           "Cách soạn cho bộ tra bản đồ dễ tìm nhất (đo trên dữ liệu thật): "
                           "(1) GIỮ phần chi nhánh dạng chữ thường, KHÔNG dấu ngoặc — "
                           "'Đại học Công nghiệp Hà Nội cơ sở 2' tìm ra đúng cơ sở, "
                           "còn '(Cơ sở 2)' thì TRƯỢT; "
                           "(2) BỎ tiền tố loại hình ('Trường', 'Công ty', 'Trung tâm') — "
                           "'Trường Đại học ... Cơ sở 2' cũng TRƯỢT; "
                           "(3) KHÔNG nhồi số nhà/phường/quận vào cùng tên riêng — địa chỉ hành chính "
                           "làm bộ tra trượt hẳn, cứ để tên riêng đứng một mình; "
                           "(4) người dùng nói thêm chi tiết (quận, cơ sở, thành phố) thì ghép vào để tra lại "
                           "cho đúng nhánh."}},
                       "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "pin_location",
        "description": "Chốt TOẠ ĐỘ THẬT cho MỘT ứng viên trong danh sách candidates, bằng cách tra "
                       "bản đồ OpenStreetMap với chuỗi DO BẠN SOẠN. Gọi cho TỪNG ứng viên (có thể "
                       "gọi song song nhiều lần trong cùng một lượt) NGAY sau resolve_destination, "
                       "TRƯỚC khi đọc danh sách cho người dùng — toạ độ trong candidates lúc đó chỉ "
                       "là phỏng đoán, chưa được tra bản đồ.",
        "parameters": {"type": "object",
                       "properties": {
                           "index": {"type": "integer", "description": "Số thứ tự ứng viên (bắt đầu từ 1)"},
                           "query": {"type": "string", "description":
                               "Chuỗi tra bản đồ do BẠN soạn cho ứng viên đó. Ứng viên có sẵn trường "
                               "'map_query' đã chuẩn hoá — dùng nó, chỉ sửa nếu bạn thấy sai. "
                               "Với địa chỉ nhà thì truyền số nhà + tên đường + quận. "
                               "Với địa điểm có tên riêng: BỎ tiền tố ('Trường', 'Công ty'), "
                               "KHÔNG dấu ngoặc, GIỮ chi nhánh chữ thường ('cơ sở 2'), "
                               "KHÔNG kèm số nhà/phường/quận."}},
                       "required": ["index", "query"]},
    }},
    {"type": "function", "function": {
        "name": "select_candidate",
        "description": "Chốt điểm đến là ứng viên số N sau khi người dùng đã chọn. "
                       "Nên gọi pin_location cho ứng viên đó TRƯỚC.",
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
    "Mỗi candidate có trường 'label' đã được tính sẵn để PHÂN BIỆT các lựa chọn — "
    "ĐỌC ĐÚNG label đó, KHÔNG tự chọn phần khác của địa chỉ (địa chỉ các cơ sở có thể "
    "trùng nhau, tự chọn sẽ ra 'một, Xuân Thủy; hai, Xuân Thủy; ba, Xuân Thủy' và người "
    "dùng không thể chọn được). ĐỌC NGUYÊN VĂN label, KHÔNG cắt bớt — label đã được "
    "gọt sẵn nên số nhà, tên đường, quận, tỉnh trong đó đều là thứ CẦN đọc. "
    "Mẫu: 'Có 3 cơ sở: một, Cầu Diễn, Bắc Từ Liêm; hai, Tây Tựu, Bắc Từ Liêm; ba, Phủ Lý, Hà Nam. Bạn chọn số mấy?' — "
    "Nêu tên địa điểm MỘT lần rồi liệt kê, tổng 2 câu là đủ. Người dùng chỉ cần đủ để chọn, địa chỉ đầy đủ "
    "sẽ đọc sau khi chốt. TRƯỚC KHI ĐỌC danh sách: gọi pin_location(index, query) cho TỪNG ứng viên để chốt toạ độ thật (dùng trường 'map_query' của ứng viên làm query). Khi người dùng chọn rõ -> gọi select_candidate(index). "
    "Nếu trả lời KHÔNG rõ chọn mục nào (vd 'hai cơ sở', 'cái nào', 'không biết') -> đọc "
    "lại danh sách NGẮN như trên rồi hỏi lại; TUYỆT ĐỐI KHÔNG gọi resolve_destination "
    "với câu mơ hồ đó."
)


def _label_candidates(locs):
    """Gán cho mỗi lựa chọn một nhãn NGẮN nhưng KHÁC NHAU, rồi để agent đọc đúng nhãn đó.

    Không thể giao việc này cho LLM tự quyết: khi các cơ sở có địa chỉ trùng nhau, nó
    đọc ra "một, Xuân Thủy Cầu Giấy; hai, Xuân Thủy Cầu Giấy; ba, Xuân Thủy Cầu Giấy"
    — người dùng không có cách nào chọn. Nhãn phải được đảm bảo phân biệt bằng code:
    thử tên đường, rồi phần trong ngoặc của tên (Cơ sở 1/2/3), cuối cùng là khoảng cách.
    """
    def parts(loc):
        return [p.strip() for p in (loc.get("address") or "").split(",") if p.strip()]

    def street(loc):
        # ĐƯỜNG + PHƯỜNG/QUẬN, không chỉ một từ: nghe "Phủ Lý" thì không biết đó là
        # tỉnh khác, phải nghe "Phủ Lý, Hà Nam" mới nhận ra được.
        return ", ".join(parts(loc)[:2])

    def paren(loc):
        m = re.search(r"\(([^)]+)\)", loc.get("name") or "")
        return m.group(1).strip() if m else ""

    for pick in (street, paren):
        labels = [pick(l) for l in locs]
        if all(labels) and len(set(labels)) == len(labels):
            break
    else:
        labels = [""] * len(locs)

    # Tỉnh/thành khác nhau là thông tin QUAN TRỌNG NHẤT để chọn (một cơ sở ở Hà Nội,
    # một ở Hà Nam) — luôn ghép vào nhãn khi chúng không giống nhau.
    tails = [(parts(l) or [""])[-1] for l in locs]
    if len(set(tails)) > 1 and all(labels):
        labels = [lb if (t and t in lb) or not t else f"{lb}, {t}"
                  for lb, t in zip(labels, tails)]

    if not (all(labels) and len(set(labels)) == len(labels)):
        # Vẫn trùng -> phân biệt bằng khoảng cách, thứ luôn khác nhau và người dùng
        # thật sự cần biết để chọn.
        labels = [
            f"cách {l['distanceKm']} ki-lô-mét" if l.get("distanceKm") is not None
            else f"lựa chọn {i + 1}"
            for i, l in enumerate(locs)
        ]
    for loc, lb in zip(locs, labels):
        loc["label"] = lb
    return locs


def _do_resolve(query, pk):
    """Resolve a spoken place via the Gemini-driven resolver. When it returns MULTIPLE
    locations (a place with several campuses/branches), offer them as a candidate LIST;
    otherwise return the single place. No place is hardcoded — arbitrary places work."""
    # pin=False: Gemini CHỈ làm việc của nó — tìm ra các địa điểm liên quan. Việc chốt
    # toạ độ là của agent: nó tự soạn chuỗi rồi gọi pin_location cho TỪNG chỗ. Trước đây
    # backend tự nhét tên thô của Gemini vào geocoder, agent không chen vào được.
    r = resolve_locations(query, pk["lat"], pk["lng"], pin=False)
    if not r.get("ok"):
        reason = r.get("reason", "not_found")
        out = {"ok": False, "kind": "place", "reason": reason}
        if reason == "out_of_area":
            out["message"] = ("Địa điểm này nằm quá xa điểm đón hiện tại của bạn nên mình "
                              "chưa hỗ trợ đặt xe tới đó. Bạn cho mình một điểm đến gần hơn nhé.")
        return out

    locs = r["locations"]
    if len(locs) >= 2:                       # several campuses/branches -> let user pick
        locs = _label_candidates(locs[:4])
        merged = [{"name": l["name"], "address": l.get("address"), "label": l.get("label"),
                   "lat": l["lat"], "lng": l["lng"], "verified": l.get("verified"),
                   "map_query": l.get("map_query"),
                   # Ước lượng GỐC của Gemini, giữ nguyên cả phiên để làm mốc kiểm tra pin.
                   # Không dùng lat/lng vì pin_location ghi đè chúng.
                   "est_lat": l["lat"], "est_lng": l["lng"]} for l in locs]
        return {"ok": True, "kind": "candidates", "candidates": merged, "next": _NEXT_CANDIDATES}

    loc = locs[0]
    g = _gates_for(loc["lat"], loc["lng"])   # multi-gate place -> offer accessible gate
    if g:
        return _gate_candidates(g)
    return {"ok": True, "kind": "place", "name": loc["name"], "address": loc.get("address"),
            "lat": loc["lat"], "lng": loc["lng"],
            "next": "Hỏi người dùng 'xe máy hay ô tô' TRƯỚC khi get_quote."}


def _do_pin(msgs, index, query, pk):
    """Tra chuỗi AGENT soạn qua geocoder thật, rồi gắn toạ độ đó vào ứng viên số `index`.

    Đây là chỗ duy nhất toạ độ hiển thị được sinh ra: agent nhận danh sách Gemini tìm
    được, tự soạn chuỗi theo kiểu OSM đặt tên, rồi gọi hàm này cho từng chỗ. Toạ độ của
    Gemini chỉ còn là lưới đỡ khi geocoder không tìm ra gì.
    """
    cset = _last_tool(msgs, "candidates")
    cs = [dict(c) for c in ((cset or {}).get("candidates") or [])]
    try:
        i = int(index) - 1
    except (TypeError, ValueError):
        i = -1
    if i < 0 or i >= len(cs):
        return {"ok": False, "kind": "candidates", "reason": "bad_index"}

    c = cs[i]
    # Cổng tiếp cận lấy từ DB nên toạ độ đã kiểm chứng — tra lại chỉ làm lệch đi.
    if "accessible" in c:
        return {"ok": True, "kind": "candidates", "candidates": cs}

    hit = geocode_query(query, pk["lat"], pk["lng"])
    if not hit:                                    # chuỗi agent soạn trượt -> thử tên chuẩn hoá
        alt = c.get("map_query") or c.get("name")
        if alt and alt.strip() != (query or "").strip():
            hit = geocode_query(alt, pk["lat"], pk["lng"])
    if hit:
        c["lat"], c["lng"] = hit["lat"], hit["lng"]
        c["verified"] = True
        if pk.get("lat") is not None:
            c["distanceKm"] = round(_haversine_km(pk["lat"], pk["lng"], hit["lat"], hit["lng"]), 1)
    cs[i] = c
    out = {"ok": True, "kind": "candidates", "candidates": cs,
           "pinned": bool(hit), "index": i + 1,
           "next": ("Đã chốt toạ độ. Còn ứng viên nào chưa có verified=true thì gọi pin_location "
                    "tiếp; xong hết mới đọc danh sách cho người dùng chọn." + INTERNAL)}
    if not hit:
        out["next"] = ("Không tra được chuỗi này. Gọi lại pin_location cho ứng viên đó với "
                       "ĐỊA CHỈ ĐẦY ĐỦ (số nhà, đường, phường, quận) thay vì tên riêng." + INTERNAL)
        return out
    # Bộ tra bản đồ LUÔN trả về một kết quả gần nhất, kể cả khi cái tên mình hỏi không
    # tồn tại (OSM không đánh số cơ sở chính, nên 'cơ sở 1' từng khớp bừa vào 'Ngõ số 1
    # Xóm Đình' cách 13km). Kết quả sai đó vẫn nằm trong vùng phục vụ nên trông như hợp lệ.
    #
    # So bằng CHỮ (địa chỉ trả về vs địa chỉ đã biết) thì quá mong manh: chuỗi Nominatim
    # có 'Hà Nội' nên khớp bừa với 'Dương Nội', tên vùng 'Đồng bằng...' khớp với 'Hà Đông'.
    # So bằng TOẠ ĐỘ thì không lừa được: toạ độ Gemini lệch cỡ vài trăm mét đến ~2.5km,
    # nên cách nhau quá NGƯỠNG này nghĩa là hai bên đang nói về hai nơi khác nhau.
    # Mốc so sánh là ước lượng GỐC của Gemini (est_*), không phải lat/lng — lat/lng đã bị
    # chính lần pin này ghi đè, lấy pin sai làm mốc thì lần tra lại nào cũng bị báo lệch.
    gl, gn = c.get("est_lat"), c.get("est_lng")
    if gl is not None and gn is not None and not c.get("retried"):
        off = _haversine_km(gl, gn, hit["lat"], hit["lng"])
        if off > PIN_SANITY_KM:
            out["resolved_address"] = hit.get("resolved")
            out["address_mismatch"] = True
            out["offsetKm"] = round(off, 1)
            # Lần tra lại dùng địa chỉ đầy đủ, đáng tin hơn tên riêng -> nhận luôn kết quả
            # lần đó, khỏi cảnh báo vòng hai rồi lặp mãi không dừng.
            cs[i] = {**c, "retried": True}
            out["candidates"] = cs
            out["next"] = (f"CẢNH BÁO: chuỗi {query!r} tra ra {hit.get('resolved')!r}, cách nơi cần "
                           f"tìm tới {round(off)} ki-lô-mét -> SAI CHỖ. Gọi lại pin_location cho "
                           f"đúng ứng viên này, lần này dùng ĐỊA CHỈ ĐẦY ĐỦ của nó "
                           f"({c.get('address')!r}) làm query." + INTERNAL)
    return out


def _do_select(msgs, index, pk):
    cset = _last_tool(msgs, "candidates")
    cs = (cset or {}).get("candidates") or []
    try:
        i = int(index) - 1
    except (TypeError, ValueError):
        i = -1
    if i < 0 or i >= len(cs):
        return {"ok": False, "kind": "place", "reason": "bad_index"}
    p = cs[i]
    # Danh sách candidate trả về với toạ độ THÔ của Gemini (chưa đối chiếu) để
    # người dùng chọn cho nhanh. Giờ đã biết chọn cái nào -> chốt toạ độ đúng
    # cái đó bằng geocoder thật, để pin trên bản đồ không lệch.
    # Chỉ chốt cho candidate từ Gemini; cổng (gate) đã là toạ độ đã kiểm chứng sẵn.
    # Bình thường agent đã pin_location cho ứng viên này rồi. Nếu nó bỏ sót thì chốt ở
    # đây bằng chuỗi đã chuẩn hoá, chứ không để pin sai đi vào đơn xe.
    if p.get("verified") is False:
        hit = geocode_query(p.get("map_query") or p["name"], pk["lat"], pk["lng"])
        p = {**p, "lat": hit["lat"], "lng": hit["lng"], "verified": True} if hit else             verify_location(p, pk["lat"], pk["lng"])
    # If the picked place has accessible gates AND isn't itself a gate -> offer gates.
    if "accessible" not in p:
        g = _gates_for(p["lat"], p["lng"])
        if g:
            return _gate_candidates(g)
    return {"ok": True, "kind": "place", "name": p["name"], "address": p.get("address"),
            "lat": p["lat"], "lng": p["lng"], "accessible": p.get("accessible"),
            "next": "Hỏi người dùng 'xe máy hay ô tô' TRƯỚC khi get_quote."}


def _do_quote(msgs, vehicle, pk):
    place = _last_tool(msgs, "place")
    if not place:
        return {"ok": False, "kind": "quote", "reason": "no_destination"}
    # Guardrail: do NOT quote until the user has explicitly chosen a vehicle.
    picked = _picked_vehicle(msgs)
    if not picked:
        return {"ok": False, "kind": "quote", "reason": "need_vehicle",
                "message": "Chưa chọn loại xe. Hãy HỎI người dùng muốn 'xe máy hay ô tô' trước khi báo giá."}
    vehicle = picked  # trust what the user actually said
    rt = road_route(pk["lat"], pk["lng"], place["lat"], place["lng"])
    km = rt["distanceKm"] if rt else None
    price = _quote_price(vehicle, km or 0)
    return {
        "ok": True, "kind": "quote", "name": place["name"], "address": place.get("address"),
        "lat": place["lat"], "lng": place["lng"], "distanceKm": km,
        "durationMin": rt["durationMin"] if rt else None, "priceVnd": price,
        "vehicle": vehicle, "geometry": rt["geometry"] if rt else None,
    }


def _do_book(msgs, vehicle, pk):
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
        "address": ref.get("address"), "priceVnd": price, "pickup": pk["name"],
    }
    try:
        ride = create_ride_request(
            passenger_id=DEMO_PASSENGER_ID,
            pickup={"name": pk["name"], "lat": pk["lat"], "lng": pk["lng"]},
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
    """Gọi LLM; auto-retry khi bị 429 rate limit (reset sau vài giây)."""
    last = None
    for _ in range(4):
        try:
            return client.chat.completions.create(
                model=LLM_MODEL, messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0.3,
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


def run_agent(messages: list[dict], pickup: dict | None = None) -> dict:
    """One agent turn. Returns {reply, messages, ui}. `pickup` is the rider's live
    GPS ({lat,lng[,name]}); falls back to DEFAULT_PICKUP when unavailable."""
    client = llm_client()
    if not client:
        return {"reply": "Hệ thống agent chưa sẵn sàng (thiếu DEEPSEEK_API_KEY).", "messages": messages, "ui": {}}

    pk = _pickup(pickup)
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
                res = _do_resolve(args.get("query", ""), pk)
                _apply_place_ui(ui, res)
            elif name == "pin_location":
                res = _do_pin(msgs, args.get("index"), args.get("query", ""), pk)
                _apply_place_ui(ui, res)
            elif name == "select_candidate":
                res = _do_select(msgs, args.get("index"), pk)
                _apply_place_ui(ui, res)
            elif name == "get_quote":
                res = _do_quote(msgs, args.get("vehicle", "bike"), pk)
                if res.get("ok"):
                    ui["quote"] = {"name": res["name"], "address": res.get("address"),
                                   "lat": res["lat"], "lng": res["lng"], "distanceKm": res.get("distanceKm"),
                                   "durationMin": res.get("durationMin"), "priceVnd": res.get("priceVnd"),
                                   "vehicle": res.get("vehicle"), "geometry": res.get("geometry")}
            elif name == "book_ride":
                res = _do_book(msgs, args.get("vehicle", "bike"), pk)
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

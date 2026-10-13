"""
agent.py — VoiceGo conversational agent (DeepSeek function-calling qua SDK tương thích
OpenAI — xem voice.llm_client; ReAct loop). Hai lối vào: run_agent (/api/agent/chat, trả
một lần) và run_agent_stream (/api/agent/chat_stream, stream từng câu).

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
import hashlib
import json
import re
import threading
import time
import unicodedata

from voice import llm_client, LLM_MODEL
from geocode import (resolve_locations, verify_location, geocode_query,
                     _nominatim, _haversine_km)
from routing import road_route
from db import DEMO_PASSENGER_ID, MongoUnavailable, create_ride_request, find_gate_group

MAX_ALT_KM = 80  # drop same-name places too far away (e.g. another province)

# Fallback pickup when the rider's GPS is unavailable (Trường Đại học Quốc tế).
# Real bookings use the GPS coords the client sends with each turn.

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


_SENT_SPLIT = re.compile(r"(?<=[.?!…])\s+")   # ranh giới câu: dấu câu + khoảng trắng


def _pre_clean(text):
    """Phần 'gọt' của _clean_reply (cắt function-call/JSON lọt ra, bỏ markdown, đọc tiền),
    CHƯA tách câu. Tách riêng để bản stream (ReplySentenceStream) dùng đúng cùng luật."""
    for marker in ("<function", "<tool_call", "<|python_tag|>", "```"):
        i = text.find(marker)
        if i != -1:
            text = text[:i]
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?m)^\s*#+\s*", "", text)   # markdown headers
    return _say_money(text)                      # 107000 -> "107 nghìn" (TTS đọc đúng)


def _dedupe_sentences(parts):
    """Bỏ câu lặp liền nhau (gpt-oss đôi khi lặp y nguyên 1 câu)."""
    out = []
    for s in parts:
        if not s.strip():
            continue
        if not out or s.strip().lower() != out[-1].strip().lower():
            out.append(s)
    return out


def _clean_reply(text):
    """Strip leaked function-call/JSON + markdown so TTS reads clean Vietnamese."""
    if not text:
        return ""
    text = _pre_clean(text).strip()
    out = _dedupe_sentences(_SENT_SPLIT.split(text))
    return (" ".join(out).strip() or text)


class ReplySentenceStream:
    """Tách câu trả lời đang stream thành từng CÂU TRỌN, nhả ra ngay khi câu xong.

    Một câu chỉ được coi là xong khi đã thấy dấu câu + khoảng trắng phía sau (cần ký tự
    kế tiếp mới biết "8." là hết câu hay là "8.5"). Mỗi lần nhận thêm chữ thì gọt LẠI
    toàn bộ văn bản bằng đúng _pre_clean/_dedupe_sentences của _clean_reply, nên ghép
    các câu đã nhả bằng " " luôn ra ĐÚNG chuỗi _clean_reply(toàn văn) — tức đúng câu trả
    lời mà /api/agent/chat cũ sẽ trả (có test: test_agent_stream.py).
    """

    def __init__(self):
        self.raw = ""
        self.emitted = []

    def _take(self, parts):
        parts = _dedupe_sentences(parts)
        n = len(self.emitted)
        if parts[:n] != self.emitted:
            # Không bao giờ nên xảy ra (luật gọt chỉ đổi phần đuôi). Có thì thôi không
            # nhả thêm giữa chừng nữa, để finish() quyết bằng toàn văn.
            return []
        new = parts[n:]
        self.emitted.extend(new)
        return new

    def feed(self, delta):
        """Thêm một mẩu chữ từ LLM -> danh sách câu MỚI vừa trọn (có thể rỗng)."""
        if not delta:
            return []
        self.raw += delta
        parts = _SENT_SPLIT.split(_pre_clean(self.raw).lstrip())
        return self._take(parts[:-1])          # mẩu cuối có thể chưa hết câu -> giữ lại

    def finish(self):
        """Hết stream -> (các câu còn lại chưa nhả, reply hoàn chỉnh = _clean_reply)."""
        reply = _clean_reply(self.raw)
        rest = self._take(_SENT_SPLIT.split(reply)) if reply else []
        return rest, reply

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
        "name": "select_candidate",
        "description": "Chốt điểm đến là ứng viên số N sau khi người dùng đã chọn.",
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
    "sẽ đọc sau khi chốt. Khi người dùng chọn rõ -> gọi select_candidate(index). "
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
    r = resolve_locations(query, pk["lat"], pk["lng"])
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
                   "lat": l["lat"], "lng": l["lng"], "verified": l.get("verified")} for l in locs]
        return {"ok": True, "kind": "candidates", "candidates": merged, "next": _NEXT_CANDIDATES}

    loc = locs[0]
    g = _gates_for(loc["lat"], loc["lng"])   # multi-gate place -> offer accessible gate
    if g:
        return _gate_candidates(g)
    return {"ok": True, "kind": "place", "name": loc["name"], "address": loc.get("address"),
            "lat": loc["lat"], "lng": loc["lng"],
            "next": "Hỏi người dùng 'xe máy hay ô tô' TRƯỚC khi get_quote."}


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
    # resolve_locations đã ghim toạ độ thật cho mọi candidate rồi (verified=True bình
    # thường). Chỉ khi geocoder không tìm được gì lúc đó (verified=False) mới cần chốt
    # lại ở đây, để pin sai không đi vào đơn xe.
    if p.get("verified") is False:
        hit = geocode_query(p["name"], pk["lat"], pk["lng"])
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


def _chat_create(client, msgs, **extra):
    """Gọi LLM; auto-retry khi bị 429 rate limit (reset sau vài giây).
    `extra` chuyển thẳng cho SDK (vd stream=True của /api/agent/chat_stream); 429 bị ném
    ngay lúc tạo request nên retry vẫn đúng cho cả chế độ stream."""
    last = None
    for _ in range(4):
        try:
            return client.chat.completions.create(
                model=LLM_MODEL, messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0.3,
                **extra,
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


# ── book_ride idempotent theo LƯỢT ──────────────────────────────────────────────
# Đặt xe là thao tác GHI duy nhất (tạo ride_request + gán tài xế). Một lượt có thể bị
# chạy lại: stream đứt -> frontend gửi lại cùng lượt sang /api/agent/chat; mất response
# sau khi server đã đặt xong không có nghĩa là chưa đặt. Chạy lại cùng một lượt phải trả
# lại ĐÚNG chuyến đã đặt, không tạo chuyến thứ hai. Khoá = lịch sử tới hết tin nhắn user
# cuối (bỏ system): lượt chạy lại gửi y nguyên phần này, còn một lượt MỚI thì luôn có
# thêm tin nhắn user mới nên ra khoá khác -> người dùng đặt chuyến mới vẫn bình thường.
# Bộ nhớ trong process: Render chạy 1 worker (WEB_CONCURRENCY=1); nhiều worker thì cần
# chuyển sang Mongo (unique index theo khoá này).
_BOOK_TTL_S = 15 * 60
_BOOKED = {}               # khoá lượt -> (thời điểm, kết quả book_ride)
_BOOK_LOCK = threading.Lock()


def _turn_key(msgs, vehicle):
    last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
    core = [m for m in msgs[:last_user + 1] if m.get("role") != "system"]
    raw = json.dumps([core, vehicle], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _book_once(msgs, vehicle, pk):
    key = _turn_key(msgs, "car" if vehicle == "car" else "bike")
    with _BOOK_LOCK:                      # giữ khoá cả lúc đặt: 2 lần chạy song song cũng chỉ 1 chuyến
        now = time.time()
        for k in [k for k, (t, _) in _BOOKED.items() if now - t > _BOOK_TTL_S]:
            _BOOKED.pop(k, None)
        hit = _BOOKED.get(key)
        if hit:
            print(f"[book_ride] lượt chạy lại -> trả chuyến đã đặt (rideId={hit[1].get('rideId')})")
            return dict(hit[1])
        res = _do_book(msgs, vehicle, pk)
        if res.get("ok"):
            _BOOKED[key] = (now, dict(res))
        return res


def _run_tool(call_id, name, arguments, msgs, pk, ui):
    """Chạy MỘT tool call, cập nhật `ui`, rồi ghi kết quả THẬT vào `msgs` (role=tool,
    đúng tool_call_id). Dùng chung cho run_agent và run_agent_stream để hai endpoint
    chạy cùng một bộ tool, cùng guardrail."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    if name == "resolve_destination":
        res = _do_resolve(args.get("query", ""), pk)
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
        res = _book_once(msgs, args.get("vehicle", "bike"), pk)
        if res.get("ok"):
            ui["booked"] = res
    elif name == "end_conversation":
        res = {"ok": True, "kind": "ended"}
        ui["ended"] = True
    else:
        res = {"ok": False, "error": "unknown_tool"}
    # Strip bulky geometry from what the LLM sees (save tokens).
    payload = {k: v for k, v in res.items() if k != "geometry"}
    msgs.append({"role": "tool", "tool_call_id": call_id,
                 "content": json.dumps(payload, ensure_ascii=False)})
    return res


# ── Lời đáp MẪU cho kết quả tool "sạch" (bỏ vòng LLM thứ 2) ─────────────────────
# Báo giá và xác nhận đặt xe phải đọc ĐÚNG con số của tool, nên câu mẫu vừa nhanh hơn
# (đo thật: vòng LLM viết lời tốn ~0.8-1.5s/lượt) vừa an toàn hơn để LLM tự viết.
# Chỉ dùng khi kết quả chắc chắn sạch (xem _template_reply); mọi trường hợp khác (nhiều
# lựa chọn, lỗi, thiếu số liệu, nhiều tool một vòng, tool khác) vẫn để LLM viết như cũ.
# Người dùng đổi ý ở lượt SAU thì lượt đó vẫn đi qua LLM bình thường.
# Sửa câu chữ ở ĐÂY. Luật theo SYSTEM_PROMPT: tiền đọc "X nghìn đồng" (_say_money), địa
# chỉ bỏ "Việt Nam"/mã bưu chính, đủ quãng đường + giá + loại xe rồi mới hỏi xác nhận.
REPLY_TEMPLATES = {
    "quote": ("Từ chỗ bạn tới {dest} khoảng {dist}, đi mất chừng {mins} phút, "
              "giá {price} bằng {vehicle}. Bạn xác nhận đặt xe nhé?"),
    # Trùng NGUYÊN VĂN câu frontend tự đọc khi có ui.booked (useVoiceApp._send), để lịch
    # sử ghi đúng điều người dùng đã nghe.
    "booked": "Đã đặt xe. Đang tìm tài xế cho bạn, vui lòng chờ trong giây lát.",
}
_VEHICLE_VI = {"bike": "xe máy", "car": "ô tô"}


def _say_km(km):
    """20.1 -> '20 phẩy 1 ki-lô-mét' (như LLM đang đọc); dưới 1 km -> 'N mét'."""
    if km < 1:
        return f"{max(50, int(round(km * 1000 / 50.0)) * 50)} mét"
    v = round(float(km), 1)
    whole, tenth = int(v), int(round((v - int(v)) * 10))
    return f"{whole} ki-lô-mét" if tenth == 0 else f"{whole} phẩy {tenth} ki-lô-mét"


def _say_dest(name, address):
    """TÊN + phần địa chỉ đủ nhận ra (bỏ 'Việt Nam', mã bưu chính, phần trùng tên)."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    parts = [p for p in parts if p.lower() not in ("việt nam", "vietnam") and not re.fullmatch(r"\d{5,6}", p)]
    if parts and name and parts[0].lower() == name.strip().lower():
        parts = parts[1:]
    return ", ".join([name.strip()] + parts[:3]) if name else ", ".join(parts[:4])


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _quote_is_clean(res, msgs):
    """Báo giá thành công, đủ số liệu, cho đúng MỘT điểm đã chốt: sau kết quả 'place'
    gần nhất không có danh sách 'candidates' nào mới hơn (nếu có, quote đang dựa trên
    điểm cũ -> để LLM xử lý)."""
    if not (res.get("ok") and res.get("kind") == "quote" and res.get("name")):
        return False
    if res.get("vehicle") not in _VEHICLE_VI:
        return False
    if not all(_is_num(res.get(k)) for k in ("distanceKm", "durationMin", "priceVnd")):
        return False
    for m in reversed(msgs[:-1]):                 # msgs[-1] chính là kết quả quote này
        if m.get("role") != "tool":
            continue
        try:
            d = json.loads(m.get("content") or "{}")
        except Exception:  # noqa: BLE001
            continue
        if d.get("ok") and d.get("kind") == "candidates":
            return False
        if d.get("ok") and d.get("kind") == "place":
            return True
    return False


def _template_reply(round_calls, msgs):
    """Lời đáp mẫu cho vòng tool vừa chạy, hoặc None = để LLM viết như cũ.

    `round_calls` = [(tên tool, kết quả)] của ĐÚNG vòng này. Sạch khi vòng chỉ có MỘT
    tool call và:
      - get_quote ok, đủ quãng đường/thời gian/giá, một điểm đã chốt;
      - book_ride ok VÀ đã lưu DB (dbSaved=True). dbSaved=False (Mongo hỏng -> tài xế
        giả "Nguyễn Văn A") thì KHÔNG dùng mẫu: câu mẫu không được khẳng định nhiều hơn
        kết quả tool; để LLM đọc dbReason như hôm nay.
    """
    if len(round_calls) != 1:
        return None
    name, res = round_calls[0]
    if name == "get_quote" and _quote_is_clean(res, msgs):
        return REPLY_TEMPLATES["quote"].format(
            dest=_say_dest(res["name"], res.get("address")), dist=_say_km(res["distanceKm"]),
            mins=int(round(res["durationMin"])), price=f"{_say_money(str(int(res['priceVnd'])))} đồng",
            vehicle=_VEHICLE_VI[res["vehicle"]])
    if name == "book_ride" and res.get("ok") and res.get("kind") == "booked" and res.get("dbSaved") is True:
        return REPLY_TEMPLATES["booked"]
    return None


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

        calls = [(tc.function.name, _run_tool(tc.id, tc.function.name, tc.function.arguments, msgs, pk, ui))
                 for tc in m.tool_calls]
        reply = _template_reply(calls, msgs)
        if reply:      # kết quả sạch -> lời mẫu, khỏi chờ vòng LLM viết lời
            msgs.append({"role": "assistant", "content": reply})
            return {"reply": reply, "messages": msgs, "ui": ui}

      return {"reply": "Xin lỗi, mình chưa xử lý xong. Bạn thử lại giúp nhé.", "messages": msgs, "ui": ui}
    except Exception as exc:  # noqa: BLE001 — incl. persistent rate limit
        print("run_agent error:", exc)
        return {"reply": "Hệ thống đang hơi bận, bạn chờ vài giây rồi nói lại giúp mình nhé.",
                "messages": messages, "ui": {}}


# ── Bản STREAM của một lượt agent (/api/agent/chat_stream) ──────────────────────
# Cùng vòng tool như run_agent, nhưng vòng LLM CUỐI (vòng sinh lời nói) được stream:
# mỗi câu trọn được nhả ra ngay để frontend đọc câu 1 trong lúc LLM còn viết câu 2.
# Đo trên DeepSeek thật: một lượt điển hình = 2 vòng LLM (chọn tool ~0.9s, viết lời
# ~0.8-1.1s) + tool; chỉ vòng viết lời là có chữ để stream.

_FALLBACK_EMPTY = "Bạn cho tôi biết tên địa điểm cụ thể hơn giúp tôi nhé."
_WRITE_TOOLS = {"book_ride"}   # tool có tác dụng phụ ngoài hệ thống (tạo chuyến xe)
# Câu "báo đã đặt xe" — chỉ được nói khi book_ride đã trả kết quả thật trong lượt này.
_BOOK_CLAIM = re.compile(r"đã đặt|đặt xong|đặt thành công|tài xế", re.IGNORECASE)
_FALLBACK_ROUNDS = "Xin lỗi, mình chưa xử lý xong. Bạn thử lại giúp nhé."
_FALLBACK_BUSY = "Hệ thống đang hơi bận, bạn chờ vài giây rồi nói lại giúp mình nhé."


def _stream_llm_round(client, msgs):
    """Một vòng LLM ở chế độ stream. YIELD từng mẩu content (chỉ khi vòng này chưa lộ
    tool call nào); RETURN (assistant_msg, tool_calls) khi hết stream. assistant_msg có
    cùng dạng với model_dump() của bản không stream để lịch sử hai endpoint như nhau."""
    stream = _chat_create(client, msgs, stream=True)
    content, calls = [], {}
    try:
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices or choices[0].delta is None:
                continue
            d = choices[0].delta
            for tc in (getattr(d, "tool_calls", None) or []):
                idx = tc.index if getattr(tc, "index", None) is not None else len(calls)
                c = calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                if getattr(tc, "id", None):
                    c["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    c["name"] += getattr(fn, "name", None) or ""
                    c["arguments"] += getattr(fn, "arguments", None) or ""
            if getattr(d, "content", None):
                content.append(d.content)
                if not calls:
                    yield d.content
    finally:
        close = getattr(stream, "close", None)   # client ngắt giữa chừng -> thôi nhận token
        if close:
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
    tool_calls = [{"id": c["id"], "type": "function",
                   "function": {"name": c["name"], "arguments": c["arguments"]}}
                  for _, c in sorted(calls.items())]
    msg = {"role": "assistant", "content": "".join(content)}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg, tool_calls


def run_agent_stream(messages: list[dict], pickup: dict | None = None, client=None):
    """Generator các sự kiện (tên, dữ liệu) của MỘT lượt agent:

      ("tools",    {"messages", "ui", "ms"})  sau MỖI vòng tool — mốc lịch sử hợp lệ
                   (tool_calls đã có kết quả THẬT). Lượt bị ngắt thì frontend dựng lại
                   lịch sử từ mốc này, không mất kết quả tool đã chạy (vd đã đặt xe).
      ("sentence", {"i", "text", "ms"})       từng câu trọn của lời đáp, theo thứ tự.
      ("done",     {"reply", "messages", "ui", "ms", "first_sentence_ms"})
                   cùng payload với /api/agent/chat (+ số đo).

    Ghép các "sentence" bằng " " = "reply" (khi vòng cuối không có lời dẫn trước tool).
    `client` chỉ để test truyền LLM giả vào."""
    t0 = time.perf_counter()
    ms = lambda: int((time.perf_counter() - t0) * 1000)  # noqa: E731
    client = client or llm_client()
    if not client:
        reply = "Hệ thống agent chưa sẵn sàng (thiếu DEEPSEEK_API_KEY)."
        yield "sentence", {"i": 0, "text": reply, "ms": ms()}
        yield "done", {"reply": reply, "messages": messages, "ui": {}, "ms": ms(), "first_sentence_ms": ms()}
        return

    pk = _pickup(pickup)
    msgs = list(messages)
    if not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    ui = {}
    ckpt_msgs, ckpt_ui = list(messages), {}   # mốc hợp lệ gần nhất (dùng khi lỗi)
    sent_at_ckpt = 0                          # số câu đã nhả tính tới mốc đó
    sent = []                                 # các câu đã nhả cho frontend
    first_ms = None
    rounds = 0

    def sentence(text):
        nonlocal first_ms
        if first_ms is None:
            first_ms = ms()
        sent.append(text)
        return "sentence", {"i": len(sent) - 1, "text": text, "ms": ms()}

    try:
        for _ in range(6):
            rounds += 1
            splitter = ReplySentenceStream()
            held = []          # câu bị GIỮ LẠI tới hết vòng (xem _BOOK_CLAIM)
            gen = _stream_llm_round(client, msgs)
            try:
                while True:
                    try:
                        delta = next(gen)
                    except StopIteration as stop:
                        msg, tool_calls = stop.value
                        break
                    for s in splitter.feed(delta):
                        # Chưa có ui.booked (tool đặt xe chưa chạy xong) mà câu đã nói kiểu
                        # "đã đặt xe / tài xế..." -> chưa được nói ra: vòng này còn có thể
                        # kết thúc bằng tool call (hoặc tool hỏng), không được báo "đã xong"
                        # trước khi có kết quả thật. Giữ lại, kể cả các câu sau (giữ thứ tự).
                        if held or (not ui.get("booked") and _BOOK_CLAIM.search(s)):
                            held.append(s)
                        else:
                            yield sentence(s)
            finally:
                gen.close()
            msgs.append(msg)

            if not tool_calls:
                rest, reply = splitter.finish()
                if not reply:
                    reply, rest = _FALLBACK_EMPTY, ([] if splitter.emitted else [_FALLBACK_EMPTY])
                for s in held + rest:          # vòng cuối không gọi tool -> nhả các câu đã giữ
                    yield sentence(s)
                print(f"[timing] agent_stream first_sentence={first_ms}ms total={ms()}ms "
                      f"rounds={rounds} ui={list(ui.keys())}")
                yield "done", {"reply": reply, "messages": msgs, "ui": ui,
                               "ms": ms(), "first_sentence_ms": first_ms}
                return

            if splitter.emitted:
                # LLM nói một câu dẫn rồi mới gọi tool (DeepSeek đo thật không làm vậy,
                # vòng gọi tool có content rỗng). Câu đã nhả thì người dùng đã nghe -> giữ
                # nguyên trong lịch sử (content của assistant message). Câu bị giữ thì bỏ,
                # như endpoint cũ vốn bỏ content của vòng gọi tool.
                print(f"[agent_stream] loi dan truoc tool call: {splitter.emitted!r} (bo {len(held)} cau giu)")
            calls = []
            for tc in tool_calls:
                if tc["function"]["name"] in _WRITE_TOOLS:
                    # Báo TRƯỚC khi chạy thao tác ghi: từ đây stream có đứt thì client biết
                    # thao tác có thể đã commit (kết quả "unknown"), không coi là chưa làm.
                    yield "action", {"name": tc["function"]["name"], "phase": "start", "ms": ms()}
                calls.append((tc["function"]["name"],
                              _run_tool(tc["id"], tc["function"]["name"], tc["function"]["arguments"], msgs, pk, ui)))
            ckpt_msgs, ckpt_ui, sent_at_ckpt = list(msgs), dict(ui), len(sent)
            yield "tools", {"messages": ckpt_msgs, "ui": ckpt_ui, "ms": ms()}

            reply = _template_reply(calls, msgs)
            if reply:
                # Kết quả sạch -> lời mẫu (đúng số của tool), khỏi chờ vòng LLM viết lời.
                # Gửi như các câu bình thường; lịch sử: tool_calls -> kết quả -> lời mẫu.
                for s in _SENT_SPLIT.split(reply):
                    if s.strip():
                        yield sentence(s.strip())
                msgs.append({"role": "assistant", "content": reply})
                print(f"[timing] agent_stream first_sentence={first_ms}ms total={ms()}ms "
                      f"rounds={rounds} template={calls[0][0]} ui={list(ui.keys())}")
                yield "done", {"reply": reply, "messages": msgs, "ui": ui,
                               "ms": ms(), "first_sentence_ms": first_ms}
                return

        yield sentence(_FALLBACK_ROUNDS)
        yield "done", {"reply": _FALLBACK_ROUNDS, "messages": msgs, "ui": ui,
                       "ms": ms(), "first_sentence_ms": first_ms}
    except Exception as exc:  # noqa: BLE001 — incl. persistent rate limit
        print("run_agent_stream error:", exc)
        # Lịch sử trả về = mốc hợp lệ gần nhất (không bao giờ để tool_call thiếu kết quả)
        # + đúng những gì người dùng ĐÃ NGHE. Chưa nghe gì -> câu "hệ thống bận".
        heard = sent[sent_at_ckpt:]
        out_msgs = list(ckpt_msgs)
        if heard:
            reply = " ".join(heard)
            out_msgs.append({"role": "assistant", "content": reply})
        else:
            reply = _FALLBACK_BUSY
            yield sentence(reply)
            if out_msgs and out_msgs[-1].get("role") == "tool":
                # Mốc kết thúc bằng kết quả tool -> thêm lời assistant cho chuỗi hợp lệ.
                out_msgs.append({"role": "assistant", "content": reply})
        yield "done", {"reply": reply, "messages": out_msgs, "ui": ckpt_ui,
                       "ms": ms(), "first_sentence_ms": first_ms}

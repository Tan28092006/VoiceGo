"""
places_db.py — Gazetteer (danh bạ) các địa điểm nổi tiếng ở TP.HCM đã kiểm chứng.

Tra CỤC BỘ trước khi gọi geocoding mạng: nếu địa điểm người dùng nói khớp một
landmark đã biết thì trả ngay tọa độ đã xác minh — nhanh hơn, không tốn rate-limit,
và CHÍNH XÁC hơn. Nó cũng SỬA những ca mà geocoder công cộng trả sai, ví dụ:
  - "Landmark 81" bị Nominatim khớp nhầm "PetroVietnam Landmark" (lệch ~3 km),
  - "Nhà thờ Đức Bà" / "SVĐ Thống Nhất" thỉnh thoảng rơi về tâm thành phố,
  - "Đại học Bách Khoa cơ sở Lý Thường Kiệt" trả "không tìm thấy".

Tọa độ ở đây đã được audit so với ground-truth (đa số sai < 150 m). Khi cần thêm
địa điểm, chỉ việc thêm 1 dòng vào PLACES (tên + địa chỉ gọn + lat/lng + aliases).
"""
import re
import unicodedata

# name      : tên đọc lại cho người dùng (TTS)
# address   : địa chỉ gọn, đã xác minh
# lat,lng   : tọa độ đã kiểm chứng (ưu tiên giá trị Nominatim trả khớp ground-truth)
# aliases   : các cách NÓI khác (không dấu cũng được — matcher tự bỏ dấu)
PLACES = [
    # ---- TIER S: audit sai < 50 m ----
    {"name": "Chợ Bến Thành", "address": "Chợ Bến Thành, Công trường Quách Thị Trang, Quận 1",
     "lat": 10.77253, "lng": 106.69804, "aliases": ["ben thanh", "cho ben thanh"]},
    {"name": "Bến Nhà Rồng", "address": "Bến Nhà Rồng, Phường Xóm Chiếu, Quận 4",
     "lat": 10.76821, "lng": 106.70667, "aliases": ["ben nha rong", "bao tang ho chi minh ben nha rong"]},
    {"name": "Crescent Mall", "address": "Crescent Mall, 101 Tôn Dật Tiên, Phú Mỹ Hưng, Quận 7",
     "lat": 10.72900, "lng": 106.71892, "aliases": ["crescent", "crescent mall", "cresent mall", "cret xen mo"]},
    {"name": "Bitexco Financial Tower", "address": "Bitexco Financial Tower, 2 Hải Triều, Quận 1",
     "lat": 10.77186, "lng": 106.70446, "aliases": ["bitexco", "thap bitexco", "toa nha bitexco", "bi tec xco"]},
    {"name": "Hồ Con Rùa", "address": "Hồ Con Rùa, Công trường Quốc tế, Quận 3",
     "lat": 10.78264, "lng": 106.69595, "aliases": ["ho con rua", "cong truong quoc te"]},
    {"name": "Dinh Độc Lập", "address": "Dinh Độc Lập, 135 Nam Kỳ Khởi Nghĩa, Quận 1",
     "lat": 10.77703, "lng": 106.69549, "aliases": ["dinh doc lap", "dinh thong nhat", "hoi truong thong nhat"]},
    {"name": "Bảo tàng Chứng tích Chiến tranh", "address": "Bảo tàng Chứng tích Chiến tranh, 28 Võ Văn Tần, Quận 3",
     "lat": 10.77936, "lng": 106.69228, "aliases": ["bao tang chung tich chien tranh", "chung tich chien tranh"]},
    {"name": "Bưu điện Trung tâm Sài Gòn", "address": "Bưu điện Trung tâm Sài Gòn, 2 Công xã Paris, Quận 1",
     "lat": 10.77996, "lng": 106.69999, "aliases": ["buu dien trung tam", "buu dien thanh pho", "buu dien sai gon", "buu dien trung tam sai gon"]},
    {"name": "Nhà hát Thành phố", "address": "Nhà hát Thành phố, 7 Công trường Lam Sơn, Quận 1",
     "lat": 10.77674, "lng": 106.70325, "aliases": ["nha hat thanh pho", "nha hat lon", "nha hat tp"]},
    {"name": "Vincom Center Đồng Khởi", "address": "Vincom Center Đồng Khởi, 72 Lê Thánh Tôn, Quận 1",
     "lat": 10.77816, "lng": 106.70189, "aliases": ["vincom dong khoi", "vincom center", "vincom center dong khoi", "vincom le thanh ton"]},
    {"name": "Chợ Bình Tây", "address": "Chợ Bình Tây (Chợ Lớn), 57A Tháp Mười, Quận 6",
     "lat": 10.74930, "lng": 106.65073, "aliases": ["cho binh tay", "cho lon"]},

    # ---- TIER A: audit sai < 150 m ----
    {"name": "Chợ Tân Định", "address": "Chợ Tân Định, Nguyễn Hữu Cầu, Quận 1",
     "lat": 10.78990, "lng": 106.69005, "aliases": ["cho tan dinh"]},
    {"name": "Bệnh viện Chợ Rẫy", "address": "Bệnh viện Chợ Rẫy, 201B Nguyễn Chí Thanh, Quận 5",
     "lat": 10.75670, "lng": 106.65973, "aliases": ["cho ray", "benh vien cho ray", "bv cho ray"]},
    {"name": "Thảo Cầm Viên Sài Gòn", "address": "Thảo Cầm Viên Sài Gòn, 2 Nguyễn Bỉnh Khiêm, Quận 1",
     "lat": 10.78784, "lng": 106.70634, "aliases": ["thao cam vien", "so thu", "vuon bach thao"]},

    # ---- Landmark phổ biến + SỬA các ca geocoder hay trả sai ----
    {"name": "Landmark 81", "address": "Vinhomes Central Park, 720A Điện Biên Phủ, Bình Thạnh",
     "lat": 10.79480, "lng": 106.72191,
     "aliases": ["landmark", "landmark 81", "land mark", "vinhomes central park", "vincom landmark 81", "lanmark"]},
    {"name": "Nhà thờ Đức Bà", "address": "Nhà thờ Đức Bà, 1 Công xã Paris, Quận 1",
     "lat": 10.77973, "lng": 106.69910, "aliases": ["nha tho duc ba", "duc ba", "nha tho chinh toa duc ba"]},
    {"name": "Sân vận động Thống Nhất", "address": "Sân vận động Thống Nhất, 138 Đào Duy Từ, Quận 10",
     "lat": 10.77258, "lng": 106.66724, "aliases": ["san van dong thong nhat", "svd thong nhat", "san van dong"]},
    {"name": "Đại học Bách Khoa (cơ sở 1 - Quận 10)",
     "address": "Đại học Bách Khoa, 268 Lý Thường Kiệt, Phường 14, Quận 10",
     "lat": 10.77230, "lng": 106.65770,
     "aliases": ["bach khoa", "dai hoc bach khoa", "dhbk", "bach khoa ly thuong kiet",
                 "truong bach khoa", "bach khoa quan 10", "bach khoa co so 1"]},
    {"name": "Đại học Bách Khoa (cơ sở 2 - Dĩ An)",
     "address": "Đại học Bách Khoa cơ sở 2, Khu ĐHQG, Dĩ An, Bình Dương",
     "lat": 10.88030, "lng": 106.80500,
     "aliases": ["bach khoa", "dai hoc bach khoa", "dhbk", "bach khoa di an",
                 "bach khoa co so 2", "bach khoa thu duc"]},
    {"name": "Đại học Công nghệ Thông tin (UIT)",
     "address": "Đại học Công nghệ Thông tin, Khu phố 6, Linh Trung, TP. Thủ Đức",
     "lat": 10.87004, "lng": 106.80299,
     "aliases": ["dai hoc cong nghe thong tin", "cong nghe thong tin", "dai hoc cntt", "dhcntt", "cntt", "uit", "truong cong nghe thong tin"]},
    {"name": "Đại học Quốc tế (IU)",
     "address": "Đại học Quốc tế - ĐHQG, Khu phố 6, Linh Trung, TP. Thủ Đức",
     "lat": 10.87820, "lng": 106.80120,
     "aliases": ["dai hoc quoc te", "truong quoc te", "iu", "dhqt", "dai hoc quoc te dhqg"]},
    {"name": "Đại học Khoa học Tự nhiên (Quận 5)",
     "address": "Đại học Khoa học Tự nhiên, 227 Nguyễn Văn Cừ, Phường 4, Quận 5",
     "lat": 10.76265, "lng": 106.68220,
     "aliases": ["dai hoc khoa hoc tu nhien", "khoa hoc tu nhien", "dhkhtn", "khtn",
                 "tu nhien nguyen van cu", "khoa hoc tu nhien quan 5", "khtn quan 5"]},
    {"name": "Đại học Khoa học Tự nhiên (cơ sở Thủ Đức)",
     "address": "Đại học Khoa học Tự nhiên cơ sở 2, Khu phố 6, Linh Trung, TP. Thủ Đức",
     "lat": 10.87490, "lng": 106.80050,
     "aliases": ["khoa hoc tu nhien", "dai hoc khoa hoc tu nhien", "dhkhtn", "khtn",
                 "khoa hoc tu nhien thu duc", "khtn thu duc", "tu nhien thu duc", "tu nhien linh trung"]},
    {"name": "Đại học Sư phạm Kỹ thuật TP.HCM",
     "address": "Đại học Sư phạm Kỹ thuật, 1 Võ Văn Ngân, TP. Thủ Đức",
     "lat": 10.85072, "lng": 106.77179,
     "aliases": ["su pham ky thuat", "dai hoc su pham ky thuat", "spkt", "ute"]},

    # ---- TIER B: sai < 600 m (vẫn tốt; chốt cứng để khỏi phụ thuộc geocoder) ----
    {"name": "Công viên Đầm Sen", "address": "Công viên Văn hóa Đầm Sen, 3 Hòa Bình, Quận 11",
     "lat": 10.76720, "lng": 106.63570, "aliases": ["dam sen", "cong vien dam sen", "khu du lich dam sen"]},
    {"name": "Chợ An Đông", "address": "Chợ An Đông, 34-36 An Dương Vương, Quận 5",
     "lat": 10.75530, "lng": 106.67010, "aliases": ["cho an dong", "an dong plaza"]},
    {"name": "Phố đi bộ Nguyễn Huệ", "address": "Phố đi bộ Nguyễn Huệ, Quận 1",
     "lat": 10.77400, "lng": 106.70410, "aliases": ["pho di bo nguyen hue", "duong nguyen hue", "nguyen hue", "pho di bo"]},
    {"name": "Khu du lịch Suối Tiên", "address": "Khu du lịch Suối Tiên, 120 Xa lộ Hà Nội, TP. Thủ Đức",
     "lat": 10.86620, "lng": 106.80300, "aliases": ["suoi tien", "khu du lich suoi tien", "cong vien suoi tien"]},
    {"name": "Sân bay Tân Sơn Nhất", "address": "Sân bay quốc tế Tân Sơn Nhất, Quận Tân Bình",
     "lat": 10.81880, "lng": 106.65190,
     "aliases": ["san bay", "tan son nhat", "san bay tan son nhat", "phi truong", "san bay quoc te", "ga quoc noi", "ga quoc te"]},
    {"name": "Bệnh viện Hùng Vương", "address": "Bệnh viện Hùng Vương, 128 Hồng Bàng, Quận 5",
     "lat": 10.75590, "lng": 106.66630, "aliases": ["benh vien hung vuong", "bv hung vuong", "hung vuong"]},
    {"name": "Chùa Vĩnh Nghiêm", "address": "Chùa Vĩnh Nghiêm, 339 Nam Kỳ Khởi Nghĩa, Quận 3",
     "lat": 10.79020, "lng": 106.68790, "aliases": ["chua vinh nghiem", "vinh nghiem"]},
    {"name": "Vạn Hạnh Mall", "address": "Vạn Hạnh Mall, 11 Sư Vạn Hạnh, Phường 12, Quận 10",
     "lat": 10.77076, "lng": 106.66990, "aliases": ["van hanh mall", "van hanh", "su van hanh mall"]},
]

# Token "loại địa điểm" chung chung — KHÔNG đủ để xác định 1 nơi cụ thể. Một khớp
# phải có ít nhất một token NGOÀI tập này (vd 'bệnh viện' không khớp, 'chợ rẫy' khớp).
_GENERIC = {
    "benh", "vien", "cho", "san", "truong", "dai", "hoc", "cong", "duong", "pho",
    "quan", "chua", "nha", "tho", "toa", "thap", "ga", "khu", "du", "lich",
    "trung", "tam", "ben", "vuon", "cua", "hang", "sieu", "thi", "cau", "mall", "plaza",
}

# Cụm từ dẫn thường bám quanh điểm đến khi người dùng nói (matcher sẽ bỏ đi).
_FILLER = [
    "thanh pho ho chi minh", "tp ho chi minh", "tphcm", "tp hcm", "ho chi minh", "sai gon", "viet nam",
    "cho toi den", "cho minh den", "toi muon den", "minh muon den", "toi muon di", "minh muon di",
    "dua toi den", "dua toi", "di den", "den", "toi", "minh", "muon di", "muon den", "di toi",
    "dia chi", "o tai", "tai", "khu vuc", "gan",
]


def _fold(s):
    """Lowercase, bỏ dấu tiếng Việt, bỏ ký tự lạ -> chuỗi token sạch."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _toks(s):
    return [t for t in _fold(s).split(" ") if t]


def _build_index():
    idx = []
    for p in PLACES:
        keys = [p["name"]] + list(p.get("aliases", []))
        tokenized = []
        for k in keys:
            kt = _toks(k)
            if kt:
                tokenized.append(set(kt))
        idx.append((p, tokenized))
    return idx


_INDEX = _build_index()


def _strip_filler(q):
    for f in _FILLER:
        q = re.sub(rf"(^|\s){re.escape(f)}(\s|$)", " ", q)
    return re.sub(r"\s+", " ", q).strip()


_AREA_NAMES = [
    "thu duc", "binh thanh", "go vap", "tan binh", "tan phu", "phu nhuan",
    "binh tan", "nha be", "hoc mon", "cu chi", "binh chanh", "can gio", "di an",
]


def _areas_in(folded):
    """Quận/khu vực xuất hiện trong chuỗi (đã fold). 'quan 5'/'q5' -> 'q5'."""
    found = set()
    for m in re.finditer(r"\bquan\s*0*(\d{1,2})\b", folded):
        found.add("q" + m.group(1))
    for m in re.finditer(r"\bq\s*0*(\d{1,2})\b", folded):
        found.add("q" + m.group(1))
    for name in _AREA_NAMES:
        if re.search(rf"\b{name}\b", folded):
            found.add(name)
    return found


# Tokens that are location qualifiers (quận/tỉnh/thành), not distinguishing place
# words — ignored when checking for "leftover" significant tokens.
_QUALIFIER = set("quan q tp tphcm hcm sai gon ho chi minh tinh thanh pho phuong p".split())
for _n in _AREA_NAMES:
    _QUALIFIER.update(_n.split())


def _is_qualifier(t):
    return t in _QUALIFIER or (t.isdigit() and len(t) <= 2)


def _match_entry(tokenized, qt, folded, entry):
    """Điểm khớp tốt nhất của 1 entry với qt, sau khi qua guard độ chính xác +
    quận/khu vực. Trả tuple điểm (n, sig) hoặc None."""
    best_kt, best_score = None, (0, 0)
    for kt in tokenized:
        inter = kt & qt
        if not inter:
            continue
        if not (inter - _GENERIC):           # chỉ trùng token chung chung -> bỏ
            continue
        contained = kt <= qt or qt <= kt
        if not contained and len(inter) / len(kt) < 0.75:
            continue
        sig = sum(len(t) for t in inter)
        if sig < 4:
            continue
        score = (len(inter), sig)
        if score > best_score:
            best_kt, best_score = kt, score
    if best_kt is None:
        return None
    # Precision: câu còn TỪ ĐẶC TRƯNG thừa (>=3 ký tự, không phải qualifier) mà
    # alias không có -> có thể là nơi KHÁC ('quốc gia HÀ NỘI', 'sân bay NỘI BÀI').
    leftover = {t for t in (qt - best_kt - _GENERIC) if len(t) >= 3 and not _is_qualifier(t)}
    if leftover:
        return None
    # District: câu nêu quận/khu vực mà địa chỉ entry khác quận -> bỏ.
    said = _areas_in(folded)
    if said:
        addr_areas = _areas_in(_fold(entry["address"]))
        if addr_areas and not (said & addr_areas):
            return None
    return best_score


def _prep(text):
    folded = _fold(text)
    q = _strip_filler(folded)
    return folded, (set(q.split(" ")) if q else set())


def _as_place(p):
    return {"name": p["name"], "address": p["address"], "lat": p["lat"], "lng": p["lng"]}


def lookup(text):
    """Khớp text với gazetteer -> 1 địa điểm tốt nhất (dict) hoặc None."""
    if not text or not text.strip():
        return None
    folded, qt = _prep(text)
    if not qt:
        return None
    best, best_score = None, (0, 0)
    for p, tokenized in _INDEX:
        s = _match_entry(tokenized, qt, folded, p)
        if s and s > best_score:
            best, best_score = p, s
    return _as_place(best) if best else None


def lookup_all(text):
    """TẤT CẢ địa điểm đã xác minh khớp text (cho nơi NHIỀU cơ sở: Bách Khoa, KHTN…),
    xếp theo độ khớp giảm dần, đã khử trùng toạ độ. KHÔNG bịa — chỉ trả entry thật."""
    if not text or not text.strip():
        return []
    folded, qt = _prep(text)
    if not qt:
        return []
    scored = [(s, p) for p, tokenized in _INDEX
              if (s := _match_entry(tokenized, qt, folded, p))]
    scored.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], []
    for _, p in scored:
        if any(abs(p["lat"] - u[0]) < 1e-3 and abs(p["lng"] - u[1]) < 1e-3 for u in seen):
            continue
        seen.append((p["lat"], p["lng"]))
        out.append(_as_place(p))
    return out

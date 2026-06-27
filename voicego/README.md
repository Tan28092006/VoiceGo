# VoiceGo — Đặt xe bằng giọng nói cho người khiếm thị / khuyết tật tay

Ứng dụng gọi xe **giọng-nói-trước**, thiết kế theo chuẩn tiếp cận (WCAG 2.2), cho
người khiếm thị và người khó thao tác tay. Cho Grab the Future Hackathon (HCMC).

> **Định vị khác biệt:** Grab vừa *pilot* trợ lý giọng nói đặt xe ở **Singapore, tiếng Anh**
> (dùng GPT‑4.1). VoiceGo mang hướng này **về Việt Nam** và đi xa hơn:
> | Grab (SG pilot) | VoiceGo |
> |---|---|
> | Tiếng Anh | **Tiếng Việt** + chuẩn hóa/khớp địa điểm chịu lỗi giọng nói |
> | Chỉ người khiếm thị | **Khiếm thị + khuyết tật tay** (cử chỉ giữ/chạm‑2‑lần/vuốt) |
> | Cần cloud + talkback | **Fallback gõ chữ + NLU on‑device + giọng trình duyệt** (chạy khi ồn/mất mạng) |
> | GPT‑4.1 | **FPT STT/TTS (chuyên tiếng Việt) + Gemini (Search grounding)** |

## Luồng sử dụng (3 cử chỉ)
1. **Chạm & giữ** nửa dưới màn hình → nói điểm đến (*"cho tôi đi Bến Thành"*, *"đặt ô tô đi Đại học Bách Khoa"*).
2. App đọc xác nhận: *"Đi … , khoảng X km, giá Y nghìn, chạm hai lần để đồng ý."*
3. **Chạm 2 lần** = đồng ý · **vuốt ngang** = đổi xe ôm↔ô tô · **vuốt xuống** = hủy.
- **Dự phòng** (ồn / không backend): gõ lệnh vào ô dưới cùng.

## Cách hiểu địa điểm (đáng tin, không bịa)
- **Điểm trong danh sách** (gazetteer demo): chuẩn hóa tiếng Việt + khớp fuzzy → chịu lỗi STT
  (vd *"crescen mon"* → Crescent Mall). Chạy on‑device, không cần mạng.
- **Điểm bất kỳ** (kể cả khác tỉnh): **Gemini + Google Search grounding** tra địa chỉ THẬT →
  **Nominatim** ra tọa độ → **cross‑validate** + đọc lại địa chỉ & khoảng cách để người dùng
  bắt lỗi (vd Hạ Long → "cách 1132 km"). Đa cơ sở (vd "Bách Khoa") → ưu tiên gần GPS + nêu cơ sở khác.
- Nguyên tắc: **LLM lo ngôn ngữ, không bao giờ là nguồn tọa độ**; tọa độ luôn từ geocoder; đặt xe chỉ sau khi người dùng xác nhận.

## Chạy

### Backend (bắt buộc cho STT/TTS/geocode — dùng Python có pip, vd `py`)
```bash
cd voicego/backend
cp .env.example .env      # rồi điền FPT_API_KEY, GEMINI_API_KEY
py -m pip install -r requirements.txt
py -m uvicorn main:app --port 8000
```

### MongoDB (lưu profile, chuyến đi, báo cáo accessibility)
```bash
cd voicego/backend
mkdir -p mongo-data
mongod --dbpath ./mongo-data
```
Trong terminal khác:
```bash
cd voicego/backend
cp .env.example .env
# MONGODB_URI=mongodb://localhost:27017
py -m uvicorn main:app --port 8000
```
Seed dữ liệu demo:
```bash
curl -X POST http://localhost:8000/api/db/seed
```

Các endpoint chính:
- `GET /api/db/status` — kiểm tra MongoDB + số lượng collection.
- `GET/PUT /api/me/accessibility-profile` — profile khuyết tật của hành khách demo.
- `GET /api/places/accessibility?lat=10.7769&lng=106.7009` — điểm đến gần đó kèm accessibility score.
- `POST /api/reports` — báo cáo lối vào/điểm đến accessible và cộng điểm thưởng.
- `POST /api/rides` — tạo ride request thủ công.
- Agent `book_ride` tự tạo `ride_requests` khi người dùng xác nhận đặt xe bằng giọng nói.

### Frontend
```bash
cd voicego
python -m http.server 5500
# mở http://localhost:5500
```
Không có backend, app vẫn chạy ở chế độ gõ‑chữ + giọng trình duyệt với các điểm trong gazetteer.

## Kiểm thử
- Frontend: mở `tests/tests.html` (13 test: định tuyến + NLU tiếng Việt).
- Backend: các endpoint `/api/voice/{stt,tts,nlu,geocode}` + `/api/health`.

## Bảo mật
Khóa API **chỉ** nằm trong `backend/.env` (đã gitignore). Không commit khóa.

## Kiến trúc
| Lớp | File |
|---|---|
| Giao diện tiếp cận | `index.html`, `css/voice.css`, `css/tokens.css` |
| Cử chỉ + điều phối + a11y | `js/voice-app.js` |
| Ghi âm WAV 16k | `js/voice-recorder.js` |
| NLU tiếng Việt on‑device | `js/voice-nlu.js` |
| Định tuyến/giá (demo) | `js/local-engine.js`, `js/graph.js`, `js/seed-data.js` |
| Bản đồ lộ trình | `js/map-view.js` (Leaflet) |
| Backend proxy FPT + Gemini | `backend/main.py`, `voice.py`, `geocode.py` |

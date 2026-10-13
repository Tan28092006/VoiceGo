# VoiceGo — Setup & Run

> README có problem statement / solution / features. File này: **cài đặt, chạy, reproducibility**.

## 1. Prerequisites
| Thành phần | Phiên bản | Ghi chú |
|---|---|---|
| Python | 3.11+ (đang dùng 3.13, qua `py` launcher trên Windows) | backend FastAPI |
| Node.js + npm | Node 18+ | frontend React/Vite |
| MongoDB | Atlas (mặc định) hoặc `mongod` local | lưu user / chuyến / report |
| API keys | DeepSeek (agent), Gemini (STT mặc định Gemini Live + geocode), Groq (Whisper fallback) | xem `backend/.env.example`, `AGENTS.md` mục 3 |

## 2. Cài đặt
### Backend (FastAPI — Python)
```bash
cd voicego/backend
py -m pip install -r requirements.txt        # hoặc: pip install -r requirements.txt
cp .env.example .env                          # rồi điền key thật (xem mục 4)
```
### Frontend (React — Vite)
```bash
cd voicego/frontend
npm install
```

## 3. Chạy
### A. Chạy nhanh (1 server) — Python phục vụ cả API lẫn web đã build
```bash
cd voicego/frontend && npm run build          # tạo frontend/dist
cd ../backend && py -m uvicorn main:socket_app --host 0.0.0.0 --port 8000   # socket_app = API + Socket.IO
# Mở http://localhost:8000
```
### B. Chế độ phát triển (HMR, HTTPS cho mic trên điện thoại)
```bash
# Terminal 1 — backend API
cd voicego/backend && py -m uvicorn main:socket_app --port 8000
# Terminal 2 — frontend (Vite, HTTPS tự ký, cổng 5173)
cd voicego/frontend && npm run dev
# Máy tính: https://localhost:5173   |  Điện thoại cùng WiFi: https://<IP-máy>:5173
```
> **HTTPS bắt buộc cho mic trên điện thoại**: trình duyệt chỉ cho dùng micro ở “secure context” (https hoặc localhost). Vite dev đã bật HTTPS tự ký (qua cảnh báo chứng chỉ 1 lần).
>
> 🔗 **Production** hiện tại: https://voicego-9k11.onrender.com (Render free). Demo qua LAN: `https://<IP-máy>:5173/`. Hướng dẫn vào web qua cảnh báo chứng chỉ (chế độ nâng cao) + yêu cầu **cùng WiFi** cho luồng tài xế nhận cuốc: xem [DEMO.md](DEMO.md).

### C. Realtime tài xế (tuỳ chọn — màn tài xế/PIN/chuyến đi)
Phần ghép tài xế ↔ khách dùng **Socket.IO nhúng trong backend** (`backend/realtime.py`, chạy bằng `main:socket_app`; không còn server Node :3001) — xem hợp đồng sự kiện ở [REALTIME_INTEGRATION.md](REALTIME_INTEGRATION.md). App kết nối qua proxy `/socket.io` (dev) hoặc `?realtime=<url>` khi relay ở host khác.

### Tài khoản demo (đã seed trong MongoDB)
- Khách: `minhanh.voicego@example.com` / `password123`
- Tài xế: `driver.a@example.com` / `password123`
- (Seed lại nếu cần: `POST /api/db/seed` hoặc `py seed_from_csv.py`)

## 4. Reproducibility & cấu hình
- **Dependency files** đã kèm: `backend/requirements.txt`, `frontend/package.json` + `frontend/package-lock.json`.
- **Env template**: `backend/.env.example` (sao chép thành `.env` và điền key). `.env` **không** được commit (đã gitignore).
- Biến môi trường (kèm default): xem `AGENTS.md` mục 3. Chính: `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`/`GEMINI_API_KEYS`, `GROQ_WHISPER_KEY`, `STT_ENGINE`, `TTS_ENGINE`, `MONGODB_URI`, `MONGODB_DB`. (`FPT_API_KEY`, `GROQ_API_KEY`, `GROQ_MODEL` không còn được code đọc.)
- **Test:** `cd frontend && npm test` · `cd backend && py -m pytest -q`.

## 5. Triển khai cloud (tóm tắt)
Production = 1 service Docker trên Render free (https://voicego-9k11.onrender.com) từ `render.yaml` ở gốc repo; push lên `main` là tự deploy. Chi tiết và bẫy: `AGENTS.md` mục 4; khôi phục: `RECOVERY.md`.

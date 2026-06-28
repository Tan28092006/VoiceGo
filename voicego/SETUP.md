# VoiceGo — Setup & Run

> README có problem statement / solution / features. File này: **cài đặt, chạy, reproducibility**.

## 1. Prerequisites
| Thành phần | Phiên bản | Ghi chú |
|---|---|---|
| Python | 3.11+ (đang dùng 3.13, qua `py` launcher trên Windows) | backend FastAPI |
| Node.js + npm | Node 18+ | frontend React/Vite |
| MongoDB | Atlas (mặc định) hoặc `mongod` local | lưu user / chuyến / report |
| API keys | Groq, FPT.AI, (tuỳ chọn Gemini) | xem `backend/.env.example` |

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
cd ../backend && py -m uvicorn main:app --host 0.0.0.0 --port 8000
# Mở http://localhost:8000
```
### B. Chế độ phát triển (HMR, HTTPS cho mic trên điện thoại)
```bash
# Terminal 1 — backend API
cd voicego/backend && py -m uvicorn main:app --port 8000
# Terminal 2 — frontend (Vite, HTTPS tự ký, cổng 5173)
cd voicego/frontend && npm run dev
# Máy tính: https://localhost:5173   |  Điện thoại cùng WiFi: https://<IP-máy>:5173
```
> **HTTPS bắt buộc cho mic trên điện thoại**: trình duyệt chỉ cho dùng micro ở “secure context” (https hoặc localhost). Vite dev đã bật HTTPS tự ký (qua cảnh báo chứng chỉ 1 lần).
>
> 🔗 **Demo hiện tại** (chưa deploy) dùng đúng link local này: **https://10.236.55.216:5173/**. Hướng dẫn vào web qua cảnh báo chứng chỉ (chế độ nâng cao) + yêu cầu **cùng WiFi** cho luồng tài xế nhận cuốc: xem [DEMO.md](DEMO.md).

### C. Realtime tài xế (tuỳ chọn — màn tài xế/PIN/chuyến đi)
Phần ghép tài xế ↔ khách dùng **Socket.IO server (cổng 3001)** — xem hợp đồng sự kiện ở [REALTIME_INTEGRATION.md](REALTIME_INTEGRATION.md). App kết nối qua proxy `/socket.io` (dev) hoặc `?realtime=http://<host>:3001`. Luồng đặt xe + agent + geocode chạy **không cần** server này.

### Tài khoản demo (đã seed trong MongoDB)
- Khách: `minhanh.voicego@example.com` / `password123`
- Tài xế: `driver.a@example.com` / `password123`
- (Seed lại nếu cần: `POST /api/db/seed` hoặc `py seed_from_csv.py`)

## 4. Reproducibility & cấu hình
- **Dependency files** đã kèm: `backend/requirements.txt`, `frontend/package.json` + `frontend/package-lock.json`.
- **Env template**: `backend/.env.example` (sao chép thành `.env` và điền key). `.env` **không** được commit (đã gitignore).
- Biến môi trường: `FPT_API_KEY`, `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_GEOCODE_MODEL`, `GROQ_WHISPER_KEY`, `GROQ_WHISPER_MODEL`, `GEMINI_API_KEY` (tuỳ chọn), `MONGODB_URI`, `MONGODB_DB`, `DEMO_PASSENGER_ID`.

## 5. Triển khai cloud (tóm tắt)
1. MongoDB Atlas (đặt `MONGODB_URI`).
2. Build frontend (`npm run build`) → backend phục vụ `frontend/dist`.
3. Chạy `uvicorn main:app` sau reverse proxy có HTTPS (để mic hoạt động).
4. Đặt các biến môi trường ở mục 4.

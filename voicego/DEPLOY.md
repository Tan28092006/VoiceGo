# 🚀 Deploy VoiceGo (FREE) — Vercel (frontend) + Render (backend) + MongoDB Atlas

Kiến trúc cho CV: frontend load tức thì qua **CDN Vercel**, backend FastAPI (kèm
Socket.IO realtime) trên **Render free**, dữ liệu trên **MongoDB Atlas free**.

```
Người xem ──▶ Vercel (CDN, React)  ──HTTPS──▶  Render (FastAPI + Socket.IO)  ──▶  MongoDB Atlas
                  load ~tức thì                 /api/*  +  /socket.io  (wss)        users, rides, reports
```

> **Cold-start?** Render free ngủ sau 15' không dùng → request đầu ~50s. Khắc phục ở
> **Bước 3 (keep-alive)**: ping `/api/health` mỗi 5' → máy chủ luôn thức → người xem
> vào là chạy ngay. Frontend cũng đã có warm-up ping + thông báo "đang khởi động" để
> không bao giờ trông như bị lỗi.

---

## Bước 1 — MongoDB Atlas (free)
1. https://www.mongodb.com/cloud/atlas → tạo cluster **M0 (Free)**.
2. **Database Access** → tạo user + password.
3. **Network Access** → Add IP → `0.0.0.0/0` (IP Render không cố định).
4. **Connect → Drivers** → copy chuỗi: `mongodb+srv://user:pass@cluster.xxx.mongodb.net/`

## Bước 2 — Backend lên Render (free, Docker)
1. Push code lên GitHub (đã có sẵn `voicego/Dockerfile`).
2. https://render.com → **New → Web Service** → chọn repo.
   - Runtime: **Docker**
   - **Dockerfile Path:** `voicego/Dockerfile`
   - **Docker Build Context Directory:** `voicego`
   - Region: **Singapore** (gần VN nhất), Instance: **Free**
3. **Environment Variables** (lấy từ `voicego/backend/.env`):

   | Key | Value |
   |---|---|
   | `MONGODB_URI` | chuỗi Atlas ở Bước 1 |
   | `MONGODB_DB` | `voicego` |
   | `GROQ_API_KEY` | key Groq |
   | `GROQ_WHISPER_KEY` | key Groq Whisper |
   | `FPT_API_KEY` | key FPT.AI |
   | `GROQ_MODEL` | `openai/gpt-oss-120b` |
   | `GROQ_GEOCODE_MODEL` | `llama-3.1-8b-instant` |
   | `GROQ_WHISPER_MODEL` | `whisper-large-v3-turbo` |

4. Create → đợi build → được URL, ví dụ `https://voicego-api.onrender.com`.
5. **Seed dữ liệu demo** (1 lần):
   ```
   curl -X POST https://voicego-api.onrender.com/api/db/seed
   ```

## Bước 3 — Giữ backend luôn thức (chống cold-start) ⭐
1. https://uptimerobot.com (free) → **Add New Monitor**.
   - Type: **HTTP(s)**
   - URL: `https://voicego-api.onrender.com/api/health`
   - Interval: **5 minutes**
2. Xong. Render free có 750 giờ/tháng ≈ đủ để 1 service chạy 24/7 → không còn ngủ.

## Bước 4 — Frontend lên Vercel (free)
1. https://vercel.com → **Add New → Project** → chọn repo.
2. Cấu hình:
   - **Root Directory:** `voicego/frontend`
   - Framework Preset: **Vite** (tự nhận), Build: `npm run build`, Output: `dist`
3. **Environment Variables:**
   - `VITE_BACKEND_URL` = `https://voicego-api.onrender.com`  *(URL Render ở Bước 2, KHÔNG có dấu `/` cuối)*
4. Deploy → được URL `https://voicego.vercel.app` → **đây là link bỏ vào CV**.

> Đổi env trên Vercel thì phải **Redeploy** để build lại (Vite nhúng biến lúc build).

---

## 🎬 Demo (kể cả luồng PIN realtime)
Mở **2 tab** cùng link Vercel:

| Tab | Đăng nhập | Thao tác |
|---|---|---|
| **Khách** | `minhanh.voicego@example.com` / `password123` | Nói điểm đến → xác nhận đặt xe → "Đang tìm tài xế…" |
| **Tài xế** | `driver.a@example.com` / `password123` | Bấm **Nhận cuốc** → **Tôi đã đến nơi** → nhập **PIN** khách đọc |

Luồng: khách đặt → tài xế nhận → đến nơi → app **đọc PIN** cho khách → tài xế gõ PIN
→ cả hai nghe "đã xác nhận / lên xe an toàn" → hoàn tất. *(Realtime đã test PASS.)*

## Ghi chú
- CORS backend đã mở `*` nên FE ở domain Vercel gọi sang Render không vướng.
- Socket.IO realtime nhúng chung backend (`main:socket_app`) → cùng 1 URL Render, chạy `wss://`.
- URL Render cũng tự phục vụ 1 bản frontend (fallback) nếu cần.
- **Bảo mật:** chỉ đặt API key trong dashboard Render/Vercel; `.env` đã gitignore — đừng commit.

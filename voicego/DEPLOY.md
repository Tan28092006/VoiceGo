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

## Bước 3 — Giữ backend thức ĐÚNG LÚC CẦN (chống cold-start) ⭐

> ⚠️ **ĐỌC KỸ TRƯỚC KHI DỰNG MONITOR — đây là chỗ đã làm sập service ngày 19/7/2026.**
>
> Render free cho **750 giờ instance/tháng, tính chung cả tài khoản**, và reset theo
> **chu kỳ thanh toán của tài khoản** (không phải ngày 1 hàng tháng).
> Một service chạy 24/7 suốt tháng 31 ngày tốn **744 giờ** → biên an toàn chỉ **6 giờ**.
> Mỗi lần deploy lại đều tốn thêm giờ (instance mới chạy song song lúc chuyển giao).
> Ping 5 phút/lần = service **không bao giờ ngủ** = chắc chắn cháy quota, chỉ là sớm hay muộn.
> Khi cháy: Render treo service (`Suspended by Free Tier Usage Exceeded`), trả **503**
> với header `x-render-routing: suspend`, và **không tự bật lại cho tới đầu chu kỳ sau**.

Chọn 1 trong 3 cách, theo thứ tự khuyến nghị:

**Cách A — Ping có lịch (free, an toàn, khuyến nghị).**
Dựng monitor như dưới nhưng **chỉ bật trong khung giờ cần demo** (UptimeRobot cho phép
tạm dừng monitor; cron-job.org cho phép đặt lịch theo giờ). Ping 12 giờ/ngày ≈ **372 giờ/tháng**
→ dư gấp đôi quota. Ngoài khung giờ đó service ngủ, người xem chịu cold-start ~50s
(frontend đã có warm-up ping + thông báo "đang khởi động" nên không trông như lỗi).
   - Type: **HTTP(s)** · URL: `https://voicego-api.onrender.com/api/health` · Interval: **5 minutes**

**Cách B — Không ping gì cả.** Service ngủ sau 15' không dùng, quota gần như không bao giờ
chạm trần. Đổi lại request đầu tiên mất ~50s. Phù hợp giai đoạn không có deadline.

**Cách C — Nâng gói Starter (~7 USD/tháng).** Không giới hạn giờ, không ngủ, **giữ nguyên URL**.
Đây là lựa chọn rẻ nhất về công sức nếu đang sát hạn nộp bài — không phải đổi link,
không phải khai báo lại biến môi trường, không phải test lại.

**Tuyệt đối tránh:** ping 24/7 trên gói free. Nó chỉ hoạt động cho tới khi hết quota rồi
sập đúng lúc không ai ngờ.

---

## 🚨 Khi service đã bị suspend — làm gì

1. **Xác nhận đúng bệnh:** `curl -sI https://<url> | grep x-render-routing`
   → ra `suspend` nghĩa là Render chặn từ tầng định tuyến, app không hề crash.
   Dashboard → tab **Events** sẽ ghi rõ lý do (vd `Suspended by Free Tier Usage Exceeded`).
2. **Nếu do hết quota:** nút Resume sẽ không ăn cho tới khi sang chu kỳ mới.
   Muốn có link chạy ngay thì phải nâng gói (Cách C) hoặc deploy sang nơi khác (mục dưới).
3. **Sau khi khôi phục, đổi ngay monitor sang Cách A** — nếu không sẽ lặp lại y hệt sau ~1 tháng.
4. **Kiểm tra lại bằng giọng nói thật, đừng chỉ xem trang chủ có lên không.** Toàn bộ biến
   môi trường đều có mặc định rỗng (`voice.py`, `db.py`), nên thiếu key thì app vẫn khởi động
   bình thường nhưng **câm** — mở được trang mà nói không ra gì.

### Phương án dự phòng: deploy nơi khác trong ~10 phút
`voicego/Dockerfile` đã gói sẵn cả frontend lẫn backend và chỉ phụ thuộc biến `$PORT`,
nên bê nguyên sang chỗ khác được, không sửa code:

| Nền tảng | Cách làm | Lưu ý |
|---|---|---|
| **Railway** | New Project → Deploy from GitHub → tự nhận Dockerfile | Nhanh nhất, free tier tính theo mức dùng |
| **Google Cloud Run** | `gcloud run deploy --source voicego` | Free tier rộng, không ngủ đông, cần tài khoản GCP |
| **Fly.io** | `fly launch --dockerfile voicego/Dockerfile` | Cần thẻ để xác minh |

Nhớ khai báo lại **toàn bộ** biến môi trường ở Bước 2, chạy lại lệnh seed ở Bước 2.5,
rồi cập nhật `VITE_BACKEND_URL` trên Vercel (**phải Redeploy** vì Vite nhúng biến lúc build)
và sửa link trong `DEMO.md`.

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

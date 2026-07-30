# 🌐 Deploy VoiceGo lên `voicego.res3pl.com` (Cloudflare)

Hướng dẫn end-to-end để app chạy tại **https://voicego.res3pl.com** — link ổn định,
do bạn sở hữu, đổi nhà cung cấp bao nhiêu lần cũng **không phải đổi link nộp BTC**.

```
Người xem ──▶ voicego.res3pl.com (DNS Cloudflare) ──▶ Backend (Render / HF Spaces)
                                                       FastAPI + Socket.IO + React build
                                                              │
                                        ┌─────────────────────┼─────────────────────┐
                                     DeepSeek (LLM)      Groq Whisper (STT)     MongoDB Atlas
                                     agent + geocode        nhận giọng nói        dữ liệu
```

> **Nguyên tắc vàng:** tên miền là **của bạn** trên Cloudflare. Backend bên dưới chạy ở
> đâu cũng được — đổi host thì chỉ sửa 1 bản ghi DNS, người xem không hề hay biết.

---

## Phần A — Deploy backend (chọn 1 host)

Cả hai đều dùng chung `voicego/Dockerfile` (đóng gói sẵn frontend + backend, chỉ cần `$PORT`).

### Lựa chọn 1 — Render (custom domain sạch nhất, khuyến nghị nếu chịu chi $7)

1. Dashboard Render → **New → Web Service** (hoặc **Blueprint** trỏ `render.yaml`).
   - Runtime **Docker** · Dockerfile Path `./voicego/Dockerfile` · Context `./voicego`
   - Health Check Path: `/api/health`
2. Điền biến môi trường (xem **Phần B**).
3. ⚠️ **Gói Free bị treo khi hết 750 giờ/tháng** (đã dính 2 lần). Muốn link luôn sống cho
   BTC chấm → nâng **Starter (~7 USD/tháng)**. Nếu giữ Free thì **đừng ping 24/7** (xem Phần E).

### Lựa chọn 2 — Hugging Face Spaces (free, không cần thẻ)

Xem chi tiết trong [README.md](README.md) (đã có metadata `sdk: docker`, `app_port: 8000`).
Tóm tắt: tạo Space Docker → `git subtree split --prefix voicego -b hf-deploy` →
`git push --force <hf-remote> hf-deploy:main` → khai secret ở Settings.
URL app: `https://<user>-voicego.hf.space`.

> HF **không hỗ trợ custom domain trực tiếp** → phải dùng Cloudflare proxy + Origin Rule
> (Phần C, mục C2). Fiddly hơn Render nhưng miễn phí.

---

## Phần B — Biến môi trường (cập nhật cho DeepSeek)

Đặt ở **Render → Environment** hoặc **HF Space → Settings → Variables and secrets**:

| Key | Bắt buộc | Giá trị / ghi chú |
|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | Key DeepSeek — **LLM cho agent + geocode** |
| `GROQ_WHISPER_KEY` | ✅ | Key Groq — **Whisper STT** (DeepSeek không nhận giọng nói) |
| `MONGODB_URI` | ✅ | Chuỗi kết nối MongoDB Atlas |
| `MONGODB_DB` | ⬜ | mặc định `voicego` |
| `FPT_API_KEY` | ⬜ | TTS tiếng Việt (hết quota vẫn chạy nhờ edge-tts) |
| `TTS_PRIMARY` | ⬜ | Đặt `edge` để dùng thẳng edge-tts miễn phí (khuyến nghị khi FPT hết quota) |
| `GEMINI_API_KEY` | ⬜ | Tuỳ chọn grounding geocode |

> **Đổi LLM:** mặc định đã trỏ DeepSeek (`deepseek-chat`). Muốn quay lại Groq thì set
> `LLM_API_KEY=<groq key>`, `LLM_BASE_URL=https://api.groq.com/openai/v1`,
> `LLM_MODEL=openai/gpt-oss-120b`. `GROQ_API_KEY` cũ **không còn dùng cho agent** nữa
> (chỉ `GROQ_WHISPER_KEY` cho STT).

**Bẫy chết người:** mọi key đều có mặc định rỗng → thiếu `DEEPSEEK_API_KEY` thì app
**vẫn lên xanh nhưng agent câm** (trả "Hệ thống agent chưa sẵn sàng"). Luôn test bằng
giọng nói/agent thật, đừng chỉ xem trang chủ (xem Phần D).

---

## Phần C — Trỏ `voicego.res3pl.com` trên Cloudflare

### C1 — Nếu host là Render (DNS only, SSL tự động)

1. **Render** → service → **Settings → Custom Domains → Add** → gõ `voicego.res3pl.com`.
   Render hiện đích CNAME, dạng `voicego-xxxx.onrender.com`. Ghi lại.
2. **Cloudflare** → DNS → **Add record**:
   | Trường | Giá trị |
   |---|---|
   | Type | `CNAME` |
   | Name | `voicego` |
   | Target | `voicego-xxxx.onrender.com` (đích Render ở bước 1) |
   | Proxy status | **DNS only** (đám mây **XÁM**) |
3. Quay lại Render, đợi tab Custom Domains chuyển **"Certificate Issued"** (vài phút).
   Render tự cấp SSL Let's Encrypt cho `voicego.res3pl.com`. Xong.

> Để **xám** cho đơn giản: Render tự lo chứng chỉ, WebSocket (Socket.IO) chạy thẳng.
> Nếu muốn bật proxy Cloudflare (cam) để có CDN thì **bắt buộc** đổi
> **SSL/TLS → Overview → Full (strict)**, không được để **Flexible** (sẽ lặp redirect vô tận).

### C2 — Nếu host là HF Spaces (proxy + Origin Rule ghi đè Host)

HF chỉ cấp cert cho `*.hf.space`, nên **phải** proxy qua Cloudflare:

1. **Cloudflare** → DNS → **Add record**:
   | Trường | Giá trị |
   |---|---|
   | Type | `CNAME` |
   | Name | `voicego` |
   | Target | `<user>-voicego.hf.space` |
   | Proxy status | **Proxied** (đám mây **CAM**) |
2. **Cloudflare** → **SSL/TLS → Overview → Full** (không phải Flexible).
3. **Cloudflare** → **Rules → Origin Rules → Create rule** (free có sẵn):
   - Điều kiện: Hostname = `voicego.res3pl.com`
   - **Host Header** → Rewrite to `<user>-voicego.hf.space`
   - **DNS/SNI (Resolve Override)** → `<user>-voicego.hf.space`
   Bước này để HF nhận đúng Space (nếu không, HF không biết route request về đâu).
4. Lưu. WebSocket đi qua proxy Cloudflare vẫn chạy (free hỗ trợ WS).

> Không có Origin Rule ghi đè Host → HF trả lỗi routing / cert mismatch. Đây là chỗ
> hay vấp nhất khi đặt tên miền trước HF Spaces.

---

## Phần D — Xác minh (đừng bỏ qua)

```bash
# 1. Còn bị Render treo không? (chỉ áp dụng host Render)
curl -sI https://voicego.res3pl.com | grep -i x-render-routing   # KHÔNG được ra "suspend"

# 2. Trang + API + giọng nói + agent — dùng smoke test có sẵn
bash voicego/smoke_test.sh https://voicego.res3pl.com
```

`smoke_test.sh` kiểm tra: `/` (200), `/api/health` (200), TTS (ra audio), agent (nhận
ra điểm đến). **Phải đủ 4 OK** mới gửi link cho BTC.

Kiểm tra thêm bằng tay:
- Mở `https://voicego.res3pl.com` → khoá HTTPS xanh, không cảnh báo chứng chỉ.
- Bấm "Dùng thử ngay" → nói "Chợ Bến Thành" → nghe agent trả lời (xác nhận DeepSeek chạy).

---

## Phần E — Bẫy thường gặp (đã dính, ghi lại kẻo lặp)

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `This service has been suspended` / 503 `x-render-routing: suspend` | Render Free hết 750h — thường do **uptime monitor ping 24/7** đốt sạch quota | Đừng ping 24/7; chỉ ping trong khung giờ demo, hoặc nâng Starter |
| `ERR_TOO_MANY_REDIRECTS` | Cloudflare proxy (cam) + SSL mode **Flexible** | Đổi SSL/TLS sang **Full (strict)** |
| Trang lên nhưng **bấm nói không ra gì** | Thiếu `DEEPSEEK_API_KEY` / `GROQ_WHISPER_KEY` — app vẫn khởi động | Khai đủ secret; chạy `smoke_test.sh` |
| Giọng đọc bằng giọng Tây / câm | FPT hết quota, chưa bật edge-tts | Đặt `TTS_PRIMARY=edge` |
| HF trả lỗi routing khi vào qua res3pl.com | Thiếu Origin Rule ghi đè Host | Làm bước C2.3 |
| Cert mismatch trên res3pl.com (host HF, DNS only) | HF không cấp cert cho domain riêng | Phải **Proxied (cam)** + SSL Full, không để xám |

---

## Ghi nhớ 1 dòng

> Deploy backend (Render/HF) → khai `DEEPSEEK_API_KEY` + `GROQ_WHISPER_KEY` + `MONGODB_URI` →
> CNAME `voicego` trên Cloudflare (Render: xám; HF: cam + Origin Rule) → `smoke_test.sh` 4/4 → gửi BTC.

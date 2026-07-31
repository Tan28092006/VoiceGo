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

> **Chốt (7/2026): Render Free.** HF Spaces đã hết miễn phí (xem Lựa chọn 2), các host free
> khác đều đòi thẻ hoặc không cho custom domain. Đọc kỹ mục quota bên dưới — đó là thứ đã
> làm treo service 2 lần.

Dùng `voicego/Dockerfile` (đóng gói sẵn frontend + backend, chỉ cần `$PORT`).

### Lựa chọn 1 — Render ✅ ĐANG DÙNG

1. Dashboard Render → **New → Web Service** (hoặc **Blueprint** trỏ `render.yaml`).
   - Runtime **Docker** · Dockerfile Path `./voicego/Dockerfile` · Context `./voicego`
   - Health Check Path: `/api/health`
2. Điền biến môi trường (xem **Phần B**).
3. Custom domain + TLS quản lý sẵn **có ở cả gói Free** → làm Phần C1 là xong.

**Chuyện quota, tính cho đúng:**

- Free được **750 giờ/tháng**, tháng 31 ngày có **744 giờ** → **một** service thức 24/7 cả
  tháng vẫn **vừa đủ trong quota**, dư 6 giờ. Mỏng, nhưng không phải "chắc chắn vượt".
- **750 giờ tính cho CẢ WORKSPACE, không phải từng service.** Đây mới là gốc của 2 lần bị
  treo: **2 service free thức 24/7 = 1488 giờ → cháy quota giữa tháng.** Trước khi nghi ngờ
  uptime monitor, hãy vào **Billing → Usage** đếm xem có bao nhiêu service free đang chạy,
  rồi xoá/pause hết những cái không dùng.
- Suy ra: chỉ cần đúng **1 service free** thì ping làm nóng **không** làm cháy quota. Cứ ping
  trong giai đoạn chấm cho an toàn (ví dụ 1/8→11/8 = 11 ngày = **264/750 giờ**, dư xa).
- Quota **reset theo tháng dương lịch**, ngày 1. Hết quota giữa tháng thì ở gói Free không có
  cách gỡ — chờ mùng 1, nâng Starter, hoặc dựng ở workspace khác.
- Service ngủ sau 15 phút không traffic → request đầu tiên **chờ ~1 phút**. Chạy
  `warmup.sh` trước buổi demo để mình chịu cái chờ đó thay ban giám khảo.
- Xong đợt demo thì **pause service** để dành quota cho lần demo lại.

Muốn khỏi ngủ và khỏi lo quota → **Starter (~7 USD/tháng)**.

### Lựa chọn 2 — Hugging Face Spaces — ❌ KHÔNG CÒN MIỄN PHÍ (7/2026)

**Docker Spaces giờ cần gói trả phí** (PRO **9 USD/tháng** cho tài khoản cá nhân). Trang
tạo Space hiện nhãn 🔒 *Paid* trên SDK Docker: *"Add billing to your account (credits or
subscribe to PRO) to unlock Docker Spaces"*. Đây là chính sách chung, không phải lỗi tài khoản.

**Đã thử, đừng thử lại:** gắn payment method vào Settings → Billing → Payment information
**KHÔNG mở khoá** Docker (thẻ vào rồi mà nhãn 🔒 *Paid* vẫn còn). Cửa này xét **có PRO hoặc
có số dư credits**, không xét có thẻ. Cũng **đừng nạp credits để thử**: popover credits liệt kê
6 thứ nó dùng được (Jobs, Inference Providers, Inference Endpoints, GPU Spaces, ZeroGPU,
Private Storage) mà **không có Docker Spaces** → nạp xong vẫn có thể khoá, tiền thì đã đi.
Hardware **CPU Basic vẫn là $0/giờ**, nên nếu có PRO thì Space không phát sinh phí giờ máy.

> **Nếu vẫn định chi tiền thì chọn Render Starter (7 USD) chứ đừng HF PRO (9 USD):** đắt hơn
> mà lại nhận đúng phần fiddly — HF không cấp cert cho domain riêng nên buộc phải proxy
> Cloudflare + Origin Rule (C2), còn Render chỉ cần CNAME xám (C1).

Repo vẫn giữ metadata `sdk: docker` trong [README.md](README.md) và branch deploy tạo bằng
`git subtree split --prefix voicego -b hf-deploy` → `git push --force <hf-remote> hf-deploy:main`,
để dùng lại ngay nếu sau này có PRO.

**Đừng lách bằng Space Gradio SDK** (tier này chưa khoá, và về lý thuyết `app.py` chạy uvicorn
serve `socket_app` trên cổng 7860 là được): Space Gradio **không có Node** nên phải commit sẵn
`frontend/dist`, cách dùng này HF không hỗ trợ chính thức, và bản chất là lách đúng cái paywall
họ vừa dựng → Space có thể bị gỡ ngay giữa lúc chấm. Không đáng.

### Các host free khác — đã khảo sát, đều loại

| Host | Vướng ở đâu |
|---|---|
| Koyeb | FAQ giá của chính Koyeb: free tier **vẫn đòi thẻ**; custom domain chỉ từ gói **Pro** |
| Fly.io / Google Cloud Run / Oracle Cloud | đều bắt buộc thẻ |
| GitHub Pages | **chỉ phục vụ file tĩnh, không có runtime** — không chạy được tiến trình FastAPI/Socket.IO |
| GitHub Actions | job sống tối đa 6 tiếng, không có URL public nhận request vào — không phải host |

> Nhắc lại cho khỏi lạc: **Docker không bắt buộc**, app chỉ cần một host **chạy được tiến trình
> server**. Doc chọn Docker vì nó gói luôn bước build React vào một image.

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
| | | *Mua key FPT sau:* khai `FPT_API_KEY` + **xoá** `TTS_PRIMARY` (mặc định đã là `fpt`) → Render restart ~30s, **không rebuild**. Đổi ngược lại cũng vậy. Engine hỏng thì tự rơi sang cái còn lại **trong im lặng**, nên muốn biết FPT có chạy thật không thì xem dashboard FPT, đừng tin tai. |
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
| `This service has been suspended` / 503 `x-render-routing: suspend` | Hết 750h — **thường do nhiều service free trong cùng workspace ăn chung quota** (1 service thức cả tháng chỉ tốn 744h, vẫn vừa; 2 cái là 1488h → cháy) | Billing → Usage đếm service free, **xoá/pause hết cái không dùng**; chờ mùng 1 quota reset; hoặc nâng Starter |
| Lần đầu vào chờ ~1 phút rồi mới lên | Render Free ngủ sau 15 phút không có traffic — **bình thường** | Chạy `warmup.sh` trước buổi demo |
| SDK Docker trên HF hiện 🔒 *Paid* | Docker Spaces cần PRO/credits; **gắn thẻ không mở khoá** (đã thử) | Dùng Render; đừng nạp credits để thử |
| `ERR_TOO_MANY_REDIRECTS` | Cloudflare proxy (cam) + SSL mode **Flexible** | Đổi SSL/TLS sang **Full (strict)** |
| Trang lên nhưng **bấm nói không ra gì** | Thiếu `DEEPSEEK_API_KEY` / `GROQ_WHISPER_KEY` — app vẫn khởi động | Khai đủ secret; chạy `smoke_test.sh` |
| Giọng đọc bằng giọng Tây / câm | FPT hết quota, chưa bật edge-tts | Đặt `TTS_PRIMARY=edge` |
| HF trả lỗi routing khi vào qua res3pl.com | Thiếu Origin Rule ghi đè Host | Làm bước C2.3 |
| Cert mismatch trên res3pl.com (host HF, DNS only) | HF không cấp cert cho domain riêng | Phải **Proxied (cam)** + SSL Full, không để xám |

---

## Ghi nhớ 1 dòng

> Deploy Docker lên **Render Free** → khai `DEEPSEEK_API_KEY` + `GROQ_WHISPER_KEY` + `MONGODB_URI`
> → Add Custom Domain `voicego.res3pl.com` → CNAME `voicego` trên Cloudflare **DNS only (xám)**
> → đợi "Certificate Issued" → `smoke_test.sh` 4/4 → gửi BTC.
> **Và đừng cắm uptime monitor 24/7** — đó là thứ đã treo service 2 lần.

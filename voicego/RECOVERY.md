# 🚨 Link chết / bị treo — dựng lại trong ~10 phút

Runbook cho tình huống xấu nhất: sáng ngày chấm, `https://voicego.res3pl.com` không lên.
Đọc từ trên xuống, **đừng bỏ bước 0** — 90% trường hợp là quota Render, không phải app hỏng.

> **Điều quan trọng nhất đã xong rồi:** link nộp BTC là **domain của bạn**, không phải
> `*.onrender.com`. Nên mọi thảm hoạ bên dưới đều chỉ là "đổi đích của 1 bản ghi DNS".
> **Link không bao giờ phải đổi.** Đừng bao giờ nộp link `*.onrender.com` trực tiếp.

---

## Két secret — chuẩn bị TRƯỚC, không phải lúc cháy nhà

Deploy lại nhanh hay chậm gần như chỉ phụ thuộc chuyện này: **có dán được secret ngay
không**, hay phải đi đăng nhập 4 nhà cung cấp để lấy lại key.

Tạo `voicego/backend/.env.production` (đã gitignored — kiểm bằng `git check-ignore -v` bên dưới)
và giữ đủ 3 dòng bắt buộc:

```bash
DEEPSEEK_API_KEY=...
GROQ_WHISPER_KEY=...
MONGODB_URI=mongodb+srv://...
```

```bash
git check-ignore -v voicego/backend/.env.production   # phải in ra dòng .gitignore khớp
```

Không in gì ra = **file đang bị git theo dõi, DỪNG LẠI**, đừng commit.

Nên cất thêm một bản trong password manager — máy hỏng thì `.env.production` cũng mất.

---

## Bước 0 — Chẩn đoán trước khi sửa (30 giây)

```bash
curl -sI https://voicego.res3pl.com | grep -i 'x-render-routing\|^HTTP'
```

| Thấy gì | Nghĩa là | Đi tới |
|---|---|---|
| `x-render-routing: suspend` | **Hết quota 750h** — app không hỏng | Kịch bản A |
| `HTTP/2 200` nhưng app câm | Thiếu/hỏng secret | Kịch bản B |
| Chờ mãi rồi mới 200 | Service đang ngủ, **bình thường** | Kịch bản C |
| Không resolve / lỗi DNS | Bản ghi CNAME sai | Kịch bản D |
| Cảnh báo chứng chỉ | Cert chưa cấp / proxy sai | Kịch bản E |

---

## Kịch bản A — Bị suspend vì hết 750 giờ

**Tìm nguyên nhân trước:** Billing → Usage → đếm số **service free đang chạy trong workspace**.
750 giờ tính cho **cả workspace**, nên 1 service thức cả tháng chỉ tốn 744 giờ (vẫn vừa),
nhưng **2 service free cùng thức là 1488 giờ → cháy quota giữa tháng**. Đó là nguyên nhân
thường gặp hơn nhiều so với chuyện ping. Xoá/pause hết service không dùng.

Trong cùng tháng thì gói Free không có cách "gỡ suspend". Chọn 1:

1. **Chờ mùng 1** — quota reset theo tháng dương lịch. Miễn phí, không rủi ro. Chọn cái này
   nếu buổi chấm ở sau mùng 1.
2. **Nâng Starter (~$7)** — Settings → Instance Type → Starter. Service sống lại ngay, giữ
   nguyên domain, không phải đổi DNS. **Sát giờ chấm thì làm cái này.**
3. **Dựng ở workspace/tài khoản khác** (quota theo workspace) → xem "Dựng lại từ số 0" hoặc
   "Dựng ở tài khoản khác" bên dưới → sửa CNAME sang đích mới.

---

## Kịch bản B — Lên 200 nhưng bấm nói không ra gì

Thiếu secret. App **cố tình vẫn khởi động** khi thiếu key, nên trang chủ xanh không chứng
minh được gì.

```bash
bash voicego/smoke_test.sh https://voicego.res3pl.com
```

Dòng LỖI sẽ chỉ đúng key nào thiếu. Vào Render → Environment, dán lại từ `.env.production`.
Tên key hay bị sai nhất: **`DEEPSEEK_API_KEY`** (không phải `GROQ_API_KEY` như thời trước).

---

## Kịch bản C — Ngủ, vào lần đầu chờ ~1 phút

**Đây là hành vi đúng, không phải lỗi** — chính nó giữ bạn dưới 750h. Trước giờ chấm:

```bash
bash voicego/warmup.sh https://voicego.res3pl.com
```

Chạy trước ~5 phút, xong **tắt đi**. Đừng cắm monitor 24/7.

---

## Kịch bản D & E — DNS / chứng chỉ

- **D:** Cloudflare → DNS → CNAME `voicego` phải trỏ đúng đích `*.onrender.com` **hiện tại**.
  Service mới = subdomain mới → phải sửa lại bản ghi. Proxy để **DNS only (xám)**.
- **E:** Render → Settings → Custom Domains phải báo **"Certificate Issued"**. Nếu bạn bật
  proxy Cloudflare (cam) thì **bắt buộc** SSL/TLS = **Full (strict)**; để **Flexible** sẽ
  `ERR_TOO_MANY_REDIRECTS`.

---

## Dựng lại từ số 0 (service bị xoá / đổi workspace / đổi nhà cung cấp)

1. Render → **New → Blueprint** → trỏ repo này → **Apply**.
   [`render.yaml`](../render.yaml) đã khai sẵn Docker, health check, domain và mọi biến
   mặc định → Render chỉ hỏi 3–5 secret. Dán từ `.env.production`.
2. Đợi build (~5 phút, phải build cả frontend React).
3. Copy đích `*.onrender.com` mới → Cloudflare → sửa CNAME `voicego` → **DNS only**.
4. Đợi "Certificate Issued".
5. `bash voicego/smoke_test.sh https://voicego.res3pl.com` → **phải đủ 4 OK**.

## Dựng ở tài khoản Render khác (không cần quyền GitHub)

Repo `Tan28092006/VoiceGo` là **public**, nên một tài khoản Render bất kỳ dựng được service
mà **không cần authorize GitHub app, không cần là owner repo**:

1. **Gỡ domain khỏi service cũ trước** (Settings → Custom Domains → xoá `voicego.res3pl.com`).
   Một domain chỉ gắn được vào **một** service Render trên toàn hệ thống — không gỡ thì service
   mới không gắn được domain, và `render.yaml` khai sẵn domain đó sẽ làm Blueprint fail.
2. **New → Web Service → Public Git Repository** → dán `https://github.com/Tan28092006/VoiceGo`
3. Điền tay (đúng như `render.yaml`):

   | Trường | Giá trị |
   |---|---|
   | Language / Runtime | **Docker** |
   | Dockerfile Path | `./voicego/Dockerfile` |
   | Docker Build Context Directory | `./voicego` |
   | Health Check Path | `/api/health` |
   | Instance Type | **Free** |

4. **Environment → Add from .env** → dán cả khối này (thay 3 giá trị thật vào):

   ```bash
   DEEPSEEK_API_KEY=...
   GROQ_WHISPER_KEY=...
   MONGODB_URI=mongodb+srv://...
   TTS_PRIMARY=edge
   MONGODB_DB=voicego
   LLM_MODEL=deepseek-chat
   LLM_GEOCODE_MODEL=deepseek-chat
   GROQ_WHISPER_MODEL=whisper-large-v3
   ```

5. Create → đợi build ~5 phút → Settings → Custom Domains → Add `voicego.res3pl.com`.
6. Cloudflare → sửa CNAME `voicego` sang đích `*.onrender.com` mới → **DNS only (xám)**.
7. Đợi "Certificate Issued" → `bash voicego/smoke_test.sh https://voicego.res3pl.com`.

> **Đánh đổi của đường public repo:** không có webhook GitHub → **không tự deploy khi push**.
> Sau mỗi lần push phải vào Render bấm **Manual Deploy → Deploy latest commit**.
>
> Lưu ý: tạo nhiều tài khoản của **cùng một người** để vượt giới hạn free tier là điều Render
> cấm trong ToS, và bị khoá giữa buổi chấm thì tệ hơn mất $7. Tài khoản của **đồng đội thật**
> thì hoàn toàn hợp lệ (đây là project nhóm).

## Đổi hẳn sang nhà cung cấp khác

`voicego/Dockerfile` là chuẩn, không dính gì Render: nó chỉ cần `$PORT`. Nên bất cứ host
chạy được Docker đều nhận (Fly.io, Railway, Koyeb, Cloud Run, HF Spaces nếu có PRO...).
Quy trình luôn là: deploy image → khai 3 secret → **sửa 1 bản ghi CNAME** → smoke test.

Tình hình từng host (7/2026) xem [DEPLOY_DOMAIN.md](DEPLOY_DOMAIN.md) Phần A — đã khảo sát
và loại: HF Docker đã thành trả phí, Koyeb/Fly/Cloud Run/Oracle đều đòi thẻ, GitHub Pages
không chạy được tiến trình server.

---

## Nhớ 1 dòng

> `curl -sI` xem có `suspend` không → suspend thì nâng Starter hoặc Blueprint sang workspace
> khác → sửa CNAME → `smoke_test.sh` 4/4. Secret luôn nằm sẵn ở `.env.production`.

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

Không có cách nào "gỡ suspend" ở gói Free trong cùng tháng. Chọn 1:

1. **Nâng Starter (~$7)** — Settings → Instance Type → Starter. Nhanh nhất, service sống lại
   ngay, giữ nguyên domain, không phải đổi DNS. **Nếu đang sát giờ chấm thì làm cái này.**
2. **Đổi sang workspace Render khác** (quota tính theo workspace) → dựng lại bằng Blueprint
   (mục "Dựng lại từ số 0" bên dưới) → sửa CNAME sang đích mới.

Xong rồi **tắt mọi uptime monitor**, nếu không tháng sau lặp lại y hệt.

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

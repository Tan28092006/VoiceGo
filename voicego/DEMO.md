# VoiceGo — Hướng dẫn truy cập bản DEMO (chạy local)

> Bản demo chạy **local trên máy của nhóm** (chưa deploy). Link demo:
>
> ## 🔗 https://10.236.55.216:5173/
>
> ⚠️ **Bắt buộc dùng cùng mạng WiFi** với máy chủ demo (đây là địa chỉ LAN nội bộ).
> Máy chủ phải đang chạy 3 tiến trình: backend (8000), realtime tài xế (3001), web (5173).

## 1. Vào web (qua cảnh báo chứng chỉ tự ký)
Link dùng **HTTPS chứng chỉ tự ký** (để micro hoạt động) nên trình duyệt báo **“Not secure / Your connection is not private”**. Đây là server dev của nhóm, **an toàn** — cứ bỏ qua cảnh báo:

**Chrome / Edge (máy tính):**
1. Ở trang cảnh báo → bấm **“Advanced” (Nâng cao)**.
2. Bấm **“Proceed to 10.236.55.216 (unsafe)” / “Tiếp tục truy cập…”**.
   - *Mẹo nhanh:* nếu không thấy nút, **bấm vào vùng trống của trang rồi gõ** `thisisunsafe` (Chrome sẽ vào luôn).

**Chrome (Android):** trang cảnh báo → **“Advanced”** → **“Proceed to 10.236.55.216 (unsafe)”**.

**Safari (iPhone):** **“Show Details”** → **“visit this website”** → xác nhận.

## 2. Cho phép Micro
Lần đầu trình duyệt hỏi quyền **micro → chọn “Allow / Cho phép”** (app đặt xe bằng giọng nói nên cần micro). Nếu lỡ chặn: bấm ổ khóa/“Not secure” trên thanh địa chỉ → bật lại Microphone → tải lại trang.

## 3. Đăng nhập (tài khoản demo)
- **Khách (người khiếm thị):** `minhanh.voicego@example.com` / `password123`
- **Tài xế:** `driver.a@example.com` / `password123`

## 4. Demo luồng tài xế nhận cuốc (cần 2 thiết bị, **cùng WiFi**)
Vì chạy local, muốn thử luồng **tài xế nhận cuốc + mã PIN** cần 2 màn hình, **cùng mạng WiFi với máy chủ**:
1. **Thiết bị A (khách):** mở link trên → đăng nhập `minhanh...` → đặt xe bằng giọng nói → tới bước **“Đang tìm tài xế…”**.
2. **Thiết bị B (tài xế):** mở **cùng** `https://10.236.55.216:5173/` (qua cảnh báo chứng chỉ như trên) → đăng nhập `driver.a...` → **“Nhận cuốc” → “Tôi đã đến nơi”** → nhập mã PIN mà bên khách đọc lên.
   - *Tiện nhất:* thiết bị tài xế dùng **chính máy chủ** mở `https://localhost:5173/` (khỏi lo cùng WiFi).

> Thứ tự: **khách đặt trước** (vào hàng chờ) rồi **tài xế mới bấm nhận**. Mỗi lượt demo 1 khách.

## 5. Nếu link không vào được
- Kiểm tra **cùng WiFi** với máy chủ; máy chủ còn chạy 5173/8000/3001.
- IP máy chủ có thể đổi khi đổi WiFi — lấy IP mới bằng `ipconfig` (IPv4) rồi thay vào link `https://<IP>:5173/`.

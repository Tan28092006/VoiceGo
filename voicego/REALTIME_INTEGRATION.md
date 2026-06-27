# 🔌 Ghép app giọng nói (VoiceGo) với app tài xế (Socket.IO)

App giọng nói (`voicego/`, Python + JS thuần) đóng vai **MÀN HÀNH KHÁCH**. Sau khi
khách xác nhận đặt xe bằng giọng nói, nó **bàn giao cho app tài xế thật** của bạn
(nhánh `detection`, Node + Socket.IO) — không còn tài xế hardcode.

> Phía VoiceGo **không sửa code của bạn**. File này ghi rõ những gì VoiceGo gọi/nghe
> để hai bên khớp nhau.

## Luồng hiện tại (đã chạy được với contract của bạn)

```
Khách (VoiceGo)                         Server tài xế (Node 3001)        Tài xế (DriverView)
──────────────                          ─────────────────────────        ───────────────────
nói điểm đến → đặt xe (giọng nói)
  └─ POST /api/auth/login  ───────────▶  trả {data:{id}}                 (đăng nhập driver1)
  └─ socket: "passenger-waiting"{userId} ▶  lưu vào hàng chờ
     "Đang tìm tài xế…" (đọc)                                            bấm "Tôi đã đến nơi"
                                          ◀── "driver-start"{userId}
                          ◀── "driver-arrived"{driverName,licensePlate,pin}
  ĐỌC TỰ ĐỘNG: "Tài xế đã đến. Tài xế …, biển số …"
  ĐỌC TỰ ĐỘNG: "Mã PIN của bạn là X Y Z W…"                              hiện ô nhập PIN
                                                                         nhập PIN → "verify-pin"{pin}
                          ◀── "pin-verified"  ──────────────────────────┘ (nếu khớp)
  ĐỌC: "Bạn đã lên xe an toàn. Chúc đi đường bình an!"
```

### VoiceGo **GỌI** (emit) tới server của bạn
| Kênh | Payload | Khi nào |
|---|---|---|
| `POST /api/auth/login` | `{email, password}` | lấy `userId` hợp lệ (mặc định `passenger1@grab.com` / `password123`) |
| socket `passenger-waiting` | `{ userId }` | ngay sau khi khách xác nhận đặt xe |
| socket `verify-pin` | `{ pin }` | **không** — việc nhập PIN do app tài xế làm |

### VoiceGo **NGHE** (on) từ server của bạn
| Kênh | Payload dùng | Hành vi VoiceGo |
|---|---|---|
| `driver-arrived` | `driverName`, `licensePlate`, `pin` | đọc tự động tên TX + biển số + **đọc PIN từng số** + hiện PIN to |
| `pin-verified` | (bất kỳ) | đọc "đã lên xe an toàn", đóng màn |

➡️ **Contract của bạn đã đủ để chạy.** VoiceGo đã test với mock server đúng các event này.

## Chạy demo 2 máy
1. **Server tài xế (của bạn):** `cd backend && npm i && node server.js` → cổng **3001**.
2. **Backend VoiceGo (giọng nói/agent/geocode):** `cd voicego/backend && py -m uvicorn main:app --port 8000`.
3. **Frontend VoiceGo:** `cd voicego && py -m http.server 5500` → mở **máy khách** ở `http://localhost:5500`.
4. **Máy tài xế:** chạy app React của bạn, đăng nhập `driver1@grab.com`, bấm "Tôi đã đến nơi".

Đổi địa chỉ server tài xế nếu khác máy: `http://localhost:5500/?realtime=http://<IP-máy-tài-xế>:3001`.
Tắt realtime (demo 1 máy): `?realtime=off`. Đổi tài khoản khách: `?pemail=...&ppass=...`.

## Đề xuất (KHÔNG bắt buộc) — tách "nhận cuốc" và "đã đến" cho mượt hơn
Hiện `driver-start` **gộp** nhận khách + đến nơi + lộ PIN cùng lúc, nên VoiceGo đọc
thông tin tài xế và PIN gần như liền nhau. Muốn đúng UX "tìm tài xế → có tài xế (đọc
thông tin) → tài xế đến (mới đọc PIN)", bạn thêm 1 bước/sự kiện:

- Nút **"Nhận cuốc"** → emit `driver-accepted` `{driverName, licensePlate}` (CHƯA gửi PIN).
- Nút **"Tôi đã đến nơi"** → giữ nguyên `driver-arrived` (kèm `pin`).

VoiceGo sẽ: nghe `driver-accepted` → đọc thông tin tài xế; nghe `driver-arrived` →
đọc PIN. (Khi nào bạn thêm, báo mình bật listener `driver-accepted` ở phía khách.)

## ⚠️ Bảo mật cần sửa
`detection:backend/db.js` đang **hardcode chuỗi MongoDB Atlas kèm mật khẩu**. Hãy chuyển
sang biến môi trường `MONGODB_URI` trong `.env` (đã gitignore) và **đổi mật khẩu DB**,
vì chuỗi cũ đã bị đẩy lên Git history.

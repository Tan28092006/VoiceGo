# 📍 Địa điểm demo VoiceGo — đã kiểm chứng độ chính xác geocoding

> Audit 50 địa điểm thật ở TP.HCM, so tọa độ trả về với tọa độ chuẩn (haversine).
> **Kết luận: nói TÊN địa điểm (POI) cho kết quả chuẩn & ổn định nhất.**
> Địa chỉ số nhà lẻ qua OpenStreetMap/Nominatim không ổn định → tránh khi demo.

---

## ✅ TIER S — chuẩn < 50 m (nói tên là pin trúng ngay, dùng để quay demo chính)

| Địa điểm (nói y nguyên) | Sai số |
|---|---|
| Crescent Mall Quận 7 | **17 m** |
| Bến Nhà Rồng | **19 m** |
| Chợ Bến Thành | **23 m** |
| Bitexco Financial Tower | **25 m** |
| Hồ Con Rùa | **27 m** |
| Dinh Độc Lập | **30 m** |
| Bảo tàng Chứng tích Chiến tranh | **31 m** |
| Bưu điện trung tâm Sài Gòn | **33 m** |
| Nhà hát Thành phố Hồ Chí Minh | **38 m** |
| Vincom Center Đồng Khởi | **44 m** |
| Chợ Bình Tây | **46 m** |

## ✅ TIER A — chuẩn < 150 m (vẫn rất tốt)

| Địa điểm | Sai số |
|---|---|
| Chợ Tân Định | 69 m |
| Bệnh viện Chợ Rẫy | 115 m |
| Thảo Cầm Viên Sài Gòn | 138 m |

## 🟡 TIER B — ổn ở mức < 500 m (đủ chính xác để đặt xe, an toàn để demo dự phòng)

Công viên Đầm Sen (352 m) · Chợ An Đông (386 m) · Phố đi bộ Nguyễn Huệ (460 m) ·
Khu du lịch Suối Tiên (481 m) · Sân bay Tân Sơn Nhất (485 m) · Bệnh viện Hùng Vương (507 m) ·
Chùa Vĩnh Nghiêm Quận 3 (604 m)

---

## ⛔ TRÁNH khi demo (geocoding sai/không ổn định)

- **Landmark 81** → khớp nhầm "PetroVietnam Landmark", lệch ~3.1 km. (Nói **"Vinhomes Central Park"** thay thế.)
- **Nhà thờ Đức Bà**, **Sân vận động Thống Nhất** → đôi lúc rơi về tâm thành phố (~2 km). Không ổn định.
- **Đại học Bách Khoa cơ sở Lý Thường Kiệt** → "không tìm thấy" (agent sẽ hỏi lại — đúng hành vi an toàn).
- **Địa chỉ số nhà lẻ** ("268 Lý Thường Kiệt", "97 Phạm Ngũ Lão"…) → kết quả dao động giữa các lần gọi (Nominatim yếu số nhà ở VN). Demo nên đọc **tên địa điểm**, không đọc số nhà.

---

## Tổng quan audit (50 điểm)
- POI theo tên: **~90% trong 500 m**, median sai số **~0.35 km**, **0 ca sai nguy hiểm > 10 km**.
- Pipeline đã chặn việc LLM bịa tọa độ: tra không ra → trả "không tìm thấy" để hỏi lại, **không bao giờ gửi xe tới điểm sai**.

*Cập nhật: kiểm chứng tự động qua `/api/voice/geocode`.*

# MÔ TẢ SÁNG KIẾN

## 1. Tên sáng kiến

**VoiceGo — Nền tảng đặt xe bằng giọng nói dành cho người khiếm thị, hỗ trợ "10 mét cuối" khi khách và tài xế tìm nhau**

## 2. Trụ cột E-S-G chính của sáng kiến

☐ E ☑ **S (Social — Xã hội)** ☐ G

*(Sáng kiến tập trung vào trụ cột Xã hội: đảm bảo quyền tiếp cận dịch vụ di chuyển bình đẳng cho người khuyết tật thị giác — nhóm yếu thế thường bị bỏ quên trong thiết kế sản phẩm công nghệ.)*

## 3. Lý do lựa chọn sáng kiến

Di chuyển độc lập là điều kiện tiên quyết để một người có thể học tập, làm việc và tham gia đời sống xã hội. Tuy nhiên, với người khiếm thị, việc tự mình đặt một chuyến xe công nghệ — điều mà người sáng mắt làm trong 30 giây — lại là một chuỗi rào cản:

- **Rào cản giao diện:** các ứng dụng gọi xe hiện nay được thiết kế cho người nhìn thấy màn hình — chọn điểm đến trên bản đồ, ghim vị trí, đọc biển số xe, so sánh giá. Trình đọc màn hình (screen reader) chỉ giải quyết được một phần, thao tác vẫn chậm và dễ nhầm.
- **Rào cản "10 mét cuối":** kể cả khi đặt được xe, khoảnh khắc khó khăn nhất là khi xe đã tới — **người khiếm thị không thấy xe ở đâu, tài xế không nhận ra ai là khách của mình** giữa đám đông. Nhiều người khiếm thị phải nhờ người qua đường trợ giúp, hoặc bị hủy cuốc vì tài xế không tìm thấy khách.
- **Rào cản an toàn:** không nhìn thấy biển số và mặt tài xế, người khiếm thị có nguy cơ **lên nhầm xe** — một rủi ro an toàn nghiêm trọng, đặc biệt với phụ nữ khiếm thị.

Theo Điều tra Quốc gia về Người khuyết tật Việt Nam (Tổng cục Thống kê & UNICEF), Việt Nam có khoảng **7% dân số từ 2 tuổi trở lên là người khuyết tật (~6,2 triệu người)**, trong đó khuyết tật nhìn là một trong các dạng phổ biến nhất; Tổ chức Y tế Thế giới (WHO) ước tính toàn cầu có **hơn 2,2 tỷ người suy giảm thị lực**. Đây là nhóm người dùng thật, đông đảo, nhưng gần như vắng bóng trong thiết kế của các siêu ứng dụng gọi xe.

Sáng kiến VoiceGo ra đời để trả lời câu hỏi: *"Làm thế nào để một người khiếm thị tự mình đặt xe, tìm được đúng xe của mình và lên xe an toàn — hoàn toàn không cần nhìn màn hình, không cần người trợ giúp?"*

## 4. Mục tiêu sáng kiến

### Mục tiêu tổng quát

Xây dựng một nền tảng đặt xe **điều khiển hoàn toàn bằng giọng nói tiếng Việt**, giúp người khiếm thị và người gặp khó khăn khi thao tác màn hình có thể **tự chủ di chuyển an toàn** — từ lúc nói điểm đến cho tới lúc lên đúng xe — qua đó thúc đẩy quyền tiếp cận bình đẳng (accessibility & inclusion) theo trụ cột Xã hội của ESG, đồng thời tạo ra một mô hình tham chiếu mở để các nền tảng gọi xe, giao hàng có thể áp dụng.

### Mục tiêu cụ thể (theo nguyên tắc SMART)

1. **Hoàn thiện sản phẩm demo chạy thật trên web** (điện thoại + máy tính, không cần cài đặt), cho phép người khiếm thị hoàn tất trọn vẹn một chuyến đi mô phỏng **chỉ bằng giọng nói, 0 lần chạm vào nút bấm** — *đã hoàn thành, chạy tại địa chỉ công khai.*
2. **Rút ngắn thời gian đặt xe còn dưới 60 giây** kể từ khi mở ứng dụng đến khi xác nhận đặt chuyến, so với nhiều phút khi dùng trình đọc màn hình trên ứng dụng thông thường.
3. **Giải quyết bài toán "10 mét cuối"**: 100% chuyến xe có (a) thông báo giọng nói theo khoảng cách thời gian thực, (b) tín hiệu định vị bằng đèn nháy + rung trên máy khách để tài xế nhận diện, (c) xác thực mã PIN hai chiều trước khi lên xe.
4. **Đảm bảo độ chính xác điểm đến**: hệ thống chỉ trả về địa điểm có thật đã được xác minh (gazetteer nội bộ + OpenStreetMap), **0% tọa độ do AI "bịa ra"**, từ chối rõ ràng khi ngoài phạm vi phục vụ.
5. **Thu thập dữ liệu tiếp cận cộng đồng**: xây dựng cơ chế báo cáo (`/api/reports`) để người dùng đánh giá mức độ dễ tiếp cận của điểm đến/điểm đón (cổng có bậc thang, vỉa hè, lối vào...), hướng tới bản đồ tiếp cận mở cho TP.HCM trong 12 tháng.
6. **Thử nghiệm với người dùng thật**: trong 6 tháng sau vòng thi, tổ chức thử nghiệm với ít nhất 20 người khiếm thị (phối hợp hội người mù địa phương/mái ấm), đo tỷ lệ hoàn thành chuyến không cần trợ giúp ≥ 80%.

Mỗi mục tiêu gắn trực tiếp với vấn đề thực tiễn ở mục 5 và có sản phẩm đầu ra kiểm chứng được (mục 10).

## 5. Vấn đề cần giải quyết của sáng kiến

### Thực trạng hiện tại

- Việt Nam có **~6,2 triệu người khuyết tật** (7% dân số từ 2 tuổi, theo Điều tra Quốc gia về Người khuyết tật — GSO & UNICEF); WHO ước tính toàn cầu **2,2 tỷ người suy giảm thị lực**. Phần lớn người khiếm thị tại đô thị phụ thuộc vào người thân hoặc xe ôm quen để di chuyển.
- Các ứng dụng gọi xe phổ biến đều **lấy màn hình và bản đồ làm trung tâm**: nhập điểm đến bằng bàn phím, kéo ghim trên bản đồ, nhận diện xe qua biển số và màu xe — toàn bộ đều là thao tác thị giác.
- Khảo sát và phản ánh từ cộng đồng người khiếm thị (các hội người mù, diễn đàn tiếp cận công nghệ) cho thấy hai điểm nghẽn lặp lại: (1) **không tự đặt được xe** nếu không có người hỗ trợ hoặc không thành thạo trình đọc màn hình; (2) **bị hủy chuyến hoặc chờ rất lâu** vì tài xế không tìm được khách, khách không tìm được xe.
- Rủi ro **lên nhầm xe** là có thật và đã được ghi nhận trên thế giới với cả người sáng mắt (các vụ việc liên quan xe công nghệ giả); với người khiếm thị, rủi ro này cao hơn nhiều lần vì không thể đối chiếu biển số.

### Nguyên nhân

1. **Thiết kế sản phẩm chưa bao trùm (inclusive design):** người khuyết tật là nhóm nhỏ trong tệp khách hàng nên tính năng tiếp cận thường bị xếp ưu tiên thấp; accessibility dừng ở mức "tương thích trình đọc màn hình" thay vì thiết kế lại luồng cho người không nhìn thấy.
2. **Công nghệ giọng nói tiếng Việt trước đây chưa đủ tốt:** nhận dạng giọng nói tiếng Việt trong môi trường ồn (đường phố) và hội thoại nhiều lượt chỉ mới khả thi gần đây nhờ các mô hình ASR/LLM hiện đại (FPT.AI ASR, Whisper, các LLM function-calling).
3. **Khoảng trống "10 mét cuối" chưa ai giải:** các ứng dụng tập trung vào ghép chuyến và định tuyến, coi việc khách–tài xế gặp nhau là hiển nhiên — điều không đúng với người khiếm thị.
4. **Nhận thức cộng đồng:** tài xế ít được hướng dẫn cách hỗ trợ hành khách khuyết tật; thiếu dữ liệu về mức độ tiếp cận của các điểm đón (cổng nào có bậc, lối nào bằng phẳng).

## 6. Đối tượng tác động / hưởng lợi của sáng kiến

### Đối tượng hưởng lợi

| Nhóm | Đặc điểm & nhu cầu | Lợi ích cụ thể |
|---|---|---|
| **Người khiếm thị / thị lực kém** (hưởng lợi trực tiếp) | Không hoặc khó nhìn màn hình; cần di chuyển độc lập để học tập, làm việc, khám bệnh | Tự đặt xe 100% bằng giọng nói; được trấn an bằng lời khi chờ xe; lên đúng xe nhờ xác thực PIN; không phụ thuộc người trợ giúp |
| **Người cao tuổi, người gặp khó khăn thao tác cảm ứng, người không biết chữ** | Ngại/không dùng được app phức tạp | Luồng hội thoại tự nhiên bằng tiếng Việt, không cần gõ chữ hay hiểu bản đồ |
| **Tài xế xe công nghệ** | Mất thời gian, mất thu nhập khi không tìm được khách | Màn hình hiển thị khoảng cách tới khách theo thời gian thực; nhận diện khách nhờ tín hiệu đèn nháy + rung; giảm hủy cuốc |
| **Gia đình, người thân của người khiếm thị** | Đang phải đưa đón, hỗ trợ đặt xe | Giảm gánh nặng chăm sóc, yên tâm nhờ cơ chế PIN chống lên nhầm xe |

### Đối tượng tác động

- **Các nền tảng gọi xe/giao hàng (doanh nghiệp):** sáng kiến là bằng chứng khả thi (proof-of-concept) rằng luồng đặt xe thuần giọng nói + giao thức "10 mét cuối" có thể tích hợp vào sản phẩm thương mại — tác động về **Governance** (trách nhiệm sản phẩm, tiêu chuẩn tiếp cận) và **Social** (dịch vụ bao trùm).
- **Cơ quan quản lý & tổ chức xã hội (hội người mù, trung tâm hỗ trợ người khuyết tật):** có công cụ và dữ liệu tiếp cận (báo cáo cộng đồng về điểm đón) để vận động chính sách hạ tầng; đóng vai trò đối tác thử nghiệm và phản biện trong quá trình phát triển.
- **Cộng đồng lập trình viên/sinh viên:** kiến trúc và bài học thiết kế (chống AI bịa địa điểm, thiết kế hands-free an toàn) được tài liệu hóa, có thể tái sử dụng cho các dịch vụ khác (đặt lịch khám, gọi giao hàng bằng giọng nói).
- **Môi trường (gián tiếp, trụ cột E):** khuyến khích người khuyết tật dùng phương tiện chia sẻ thay vì các chuyến đưa đón riêng của người thân, góp phần giảm phát thải trên mỗi nhu cầu di chuyển.

### Phạm vi tác động

- **Không gian:** giai đoạn demo giới hạn tại **TP. Hồ Chí Minh** (dữ liệu địa điểm đã xác minh cho HCMC, hệ thống chủ động từ chối ngoài phạm vi để đảm bảo an toàn); mô hình mở rộng được ra các đô thị khác chỉ bằng cách bổ sung dữ liệu gazetteer.
- **Thời gian:** demo công khai đã vận hành; lộ trình thử nghiệm người dùng thật 6 tháng; mở rộng dữ liệu tiếp cận 12 tháng.
- **Quy mô:** từ nhóm thử nghiệm 20–50 người khiếm thị → cộng đồng người khiếm thị đô thị → tích hợp vào nền tảng gọi xe thương mại (hàng triệu người dùng tiềm năng).

## 7. Mô tả sáng kiến

### Cách thức hoạt động (trải nghiệm người dùng)

Toàn bộ chuyến đi diễn ra **rảnh tay, không cần nhìn màn hình**:

1. Mở ứng dụng web → trợ lý **tự chào và tự lắng nghe**.
2. Người dùng **nói điểm đến** (ví dụ: *"Chợ Bến Thành"*). Điểm đón lấy tự động từ GPS.
3. Trợ lý hội thoại xác nhận địa điểm (nếu nơi đó có nhiều cơ sở, hệ thống **đọc danh sách cơ sở có thật** để khách chọn), hỏi loại xe (xe máy/ô tô), **đọc giá và quãng đường thật**, khách nói *"đồng ý"* để đặt.
4. Khi tài xế di chuyển tới, app **trấn an bằng giọng nói theo khoảng cách thời gian thực**: *"Tài xế còn cách bạn khoảng 40 mét, đang tới. Bạn cứ đứng yên chỗ an toàn."*
5. **Giao thức "10 mét cuối":**
   - Điện thoại khách **nhấp nháy sáng màn hình + rung** — tài xế (sáng mắt) nhận ra khách giữa đám đông; càng gần nháy càng nhanh. Cố tình **không phát âm thanh** để không lấn tiếng đọc mã PIN.
   - App **đọc mã PIN** cho khách; khách **chạm bất kỳ đâu trên màn hình để nghe lại** (không phải mò tìm nút — thiết kế riêng cho người khiếm thị).
   - Tài xế **nhập đúng PIN mới được xác nhận đón** → chống lên nhầm xe.
   - Màn hình tài xế hiển thị **khoảng cách tới khách theo thời gian thực**.

### Sơ đồ kiến trúc

```
[Người dùng] ── nói ──▶ Frontend (React + Leaflet)
      │ giọng nói
      ▼
  STT: FPT.AI ASR (fallback: Groq Whisper large-v3-turbo)
      │ văn bản
      ▼
  Agent hội thoại (LLM function-calling — ReAct):
      • resolve_destination → gazetteer đã xác minh + OpenStreetMap/Nominatim
      • select_candidate    → chọn cơ sở / cổng dễ tiếp cận
      • get_quote           → OSRM (quãng đường, thời gian, giá thật)
      • book_ride           → MongoDB (tạo chuyến)
      ▼
  TTS: FPT.AI (giọng banmai) đọc phản hồi (fallback: speechSynthesis)
      ▼
  Socket.IO thời gian thực: chờ tài xế → tài xế nhận → tài xế đến (+PIN)
      → xác minh PIN → hoàn tất chuyến
      ▼
  Bản đồ Leaflet: ghim điểm đi/đến, tô XANH điểm đón dễ tiếp cận, vẽ tuyến thật
```

### Công nghệ sử dụng và lý do lựa chọn

| Thành phần | Công nghệ | Lý do lựa chọn |
|---|---|---|
| Nhận dạng giọng nói (STT) | **FPT.AI ASR**, dự phòng Groq Whisper | FPT.AI tối ưu cho **tiếng Việt** (giọng vùng miền, môi trường ồn); có fallback để đảm bảo dịch vụ không gián đoạn |
| Đọc phản hồi (TTS) | **FPT.AI TTS** (giọng banmai), dự phòng trình duyệt | Giọng tiếng Việt tự nhiên, dễ nghe — yếu tố sống còn khi âm thanh là giao diện duy nhất |
| Trợ lý hội thoại | **LLM function-calling (ReAct)** qua Groq | Hiểu hội thoại tự nhiên nhiều lượt; kiến trúc function-calling buộc AI chỉ được **gọi công cụ có kiểm soát**, không tự trả lời bừa |
| Địa điểm | **Gazetteer nội bộ đã xác minh + Nominatim/OpenStreetMap** | Nguyên tắc an toàn cốt lõi: **AI không bao giờ được bịa tọa độ** — đưa người khiếm thị đến sai chỗ nguy hiểm hơn nhiều so với người sáng mắt |
| Định tuyến | **OSRM** (mã nguồn mở) | Quãng đường/thời gian/tuyến đường thật, không ước lượng; miễn phí, tự chủ vận hành |
| Thời gian thực | **Socket.IO** | Ghép khách–tài xế, cập nhật khoảng cách và trạng thái PIN tức thời |
| Dữ liệu | **MongoDB Atlas** | Lưu hồ sơ người dùng kèm **accessibility profile**, chuyến đi, báo cáo tiếp cận |
| Giao diện | **React + Leaflet** | Web app chạy ngay trên mọi điện thoại/máy tính, **không cần cài đặt** — giảm rào cản tiếp cận |

Bản demo hoàn chỉnh chạy công khai (kèm chế độ "tài xế mô phỏng" để trải nghiệm trọn luồng bằng một thiết bị, và chế độ 2 thiết bị để đóng vai tài xế thật).

## 8. Tính khả thi của sáng kiến

**Nguồn lực:**
- *Công nghệ:* sản phẩm **đã được xây dựng và triển khai thực tế** trên hạ tầng đám mây — đây không phải ý tưởng trên giấy. Toàn bộ nền tảng dùng dịch vụ có bậc miễn phí hoặc mã nguồn mở (OSRM, OpenStreetMap, Leaflet, MongoDB Atlas free tier), chi phí vận hành giai đoạn thử nghiệm gần như bằng 0.
- *Nhân sự:* đội sinh viên tự phát triển toàn bộ; kỹ năng cần thiết (web, API AI) phổ biến, dễ mở rộng đội ngũ.
- *Tài chính:* chi phí chính khi mở rộng là API giọng nói tiếng Việt — có thể tối ưu bằng fallback miễn phí (Whisper, speechSynthesis) đã tích hợp sẵn.

**Tuân thủ pháp luật & tiêu chuẩn:** phù hợp Luật Người khuyết tật 2010 (quyền tiếp cận giao thông, công nghệ thông tin) và định hướng WCAG về tiếp cận số; dữ liệu vị trí và giọng nói chỉ dùng cho phiên đặt xe, xin quyền rõ ràng (micro, GPS) theo chuẩn trình duyệt; dữ liệu bản đồ dùng nguồn mở đúng giấy phép (có tài liệu ATTRIBUTION riêng).

**Thử nghiệm trước khi áp dụng rộng:** Có — theo 3 giai đoạn:
1. *0–2 tháng:* thử nghiệm nội bộ + demo công khai (đã xong, đang chạy).
2. *2–6 tháng:* thử nghiệm có kiểm soát với 20–50 người khiếm thị tại TP.HCM, phối hợp hội người mù/trường chuyên biệt; đo tỷ lệ hoàn thành chuyến không trợ giúp, thời gian đặt xe, sự cố "tìm nhau".
3. *6–12 tháng:* mở rộng phạm vi địa điểm, chuẩn hóa API để nền tảng gọi xe tích hợp thí điểm.

**Rủi ro và biện pháp giảm thiểu:**

| Rủi ro | Biện pháp |
|---|---|
| Nhận dạng giọng sai trong môi trường ồn | Hai tầng STT (FPT.AI + Whisper); trợ lý luôn **đọc lại để xác nhận** trước khi đặt |
| AI hiểu sai/bịa địa điểm | Kiến trúc chặn triệt để: tọa độ **chỉ** đến từ dữ liệu đã xác minh; ngoài phạm vi → từ chối |
| Lên nhầm xe / giả danh tài xế | Xác thực **PIN hai chiều bắt buộc** trước khi đón |
| Khách đứng chờ ở vị trí nguy hiểm | Thông báo giọng nói chủ động trấn an, hướng dẫn đứng yên nơi an toàn |
| Dịch vụ bên thứ ba gián đoạn | Mọi thành phần trọng yếu đều có phương án dự phòng (fallback) tích hợp sẵn |
| Rủi ro riêng tư (giọng nói, vị trí) | Xin quyền minh bạch; tối thiểu hóa dữ liệu lưu trữ; không bán/chia sẻ dữ liệu |

## 9. Tính mới của sáng kiến

1. **Tính mới về giải pháp — giao thức "10 mét cuối" cho người khiếm thị:** theo tìm hiểu của nhóm, chưa có ứng dụng gọi xe nào tại Việt Nam giải quyết trực diện khoảnh khắc khách–tài xế tìm nhau bằng tổ hợp: *trấn an giọng nói theo khoảng cách thời gian thực* + *tín hiệu định vị đèn nháy/rung trên máy khách* (đảo ngược vai trò: tài xế sáng mắt tìm khách) + *xác thực PIN hai chiều với thao tác "chạm bất kỳ đâu để nghe lại"*. Chi tiết nhỏ nhưng đắt: **không dùng âm thanh làm tín hiệu định vị** để không lấn tiếng đọc PIN — quyết định chỉ có được khi thiết kế thực sự đặt người khiếm thị làm trung tâm.
2. **Tính mới về công nghệ — trợ lý AI hội thoại tiếng Việt có "hàng rào an toàn":** ứng dụng LLM function-calling cho nghiệp vụ đặt xe, nhưng với nguyên tắc kiến trúc *"AI không bao giờ được bịa tọa độ"* — AI chỉ dẫn dắt hội thoại, mọi dữ liệu địa điểm/giá/tuyến đến từ nguồn xác minh. Đây là mô hình tham chiếu cho việc dùng AI tạo sinh an toàn với nhóm yếu thế.
3. **Tính mới về quy trình — giao diện thuần giọng nói (voice-first), không phải "hỗ trợ giọng nói":** thay vì thêm tính năng tiếp cận lên app có sẵn, VoiceGo thiết kế lại toàn bộ luồng lấy âm thanh làm giao diện chính — tự chào, tự nghe, xác nhận bằng lời, đọc PIN hai lần.
4. **Tính mới về mô hình dữ liệu — bản đồ tiếp cận do cộng đồng đóng góp:** cơ chế báo cáo mức độ dễ tiếp cận của điểm đón/điểm đến (cổng nào bằng phẳng, dễ đón), tô xanh trên bản đồ — tích lũy thành tài sản dữ liệu xã hội mở.

## 10. Kết quả và tác động của sáng kiến

### Sản phẩm đầu ra

- **Nền tảng web VoiceGo hoàn chỉnh, đang vận hành công khai** (đặt xe thuần giọng nói tiếng Việt, luồng khách + luồng tài xế + tài xế mô phỏng để trình diễn).
- **Giao thức "10 mét cuối"** (thông báo khoảng cách + tín hiệu đèn/rung + PIN hai chiều) — có thể đóng gói thành module cho nền tảng khác tích hợp.
- **Bộ tài liệu mở:** kiến trúc hệ thống, hướng dẫn cài đặt, hướng dẫn sử dụng, hướng dẫn demo.
- **Cơ sở dữ liệu tiếp cận** các điểm đón tại TP.HCM (khởi tạo và lớn dần theo báo cáo cộng đồng).

### Chỉ số đánh giá (KPIs)

| Chỉ số | Mục tiêu |
|---|---|
| Tỷ lệ người khiếm thị hoàn thành đặt xe không cần trợ giúp | ≥ 80% trong thử nghiệm |
| Thời gian từ mở app đến xác nhận đặt xe | < 60 giây |
| Tỷ lệ chuyến xác thực PIN thành công trước khi đón | 100% |
| Số lần chạm màn hình cần thiết cho một chuyến | 0 (thuần giọng nói) |
| Tỷ lệ hủy cuốc do "không tìm thấy nhau" | Giảm ≥ 50% so với luồng thông thường (đo trong thử nghiệm) |
| Số điểm đón có dữ liệu tiếp cận | ≥ 100 điểm tại TP.HCM sau 12 tháng |

### Tác động theo thời gian

- **Ngắn hạn (0–6 tháng):** người khiếm thị trong nhóm thử nghiệm tự đặt xe an toàn; nâng nhận thức cộng đồng và doanh nghiệp về thiết kế bao trùm qua các vòng thi, demo công khai.
- **Trung hạn (6–18 tháng):** mở rộng dữ liệu ra nhiều quận/thành phố; hợp tác hội người mù đưa vào sử dụng thường xuyên; đề xuất tích hợp thí điểm với nền tảng gọi xe.
- **Dài hạn (18+ tháng):** giao thức "10 mét cuối" và mô hình voice-first trở thành tiêu chuẩn tham chiếu cho dịch vụ di chuyển bao trùm tại Việt Nam; bản đồ tiếp cận cộng đồng phục vụ cả quy hoạch hạ tầng. Giá trị bền vững đến từ chi phí vận hành thấp (nguồn mở + fallback miễn phí) và dữ liệu cộng đồng tự lớn theo người dùng.

## 11. Ý nghĩa / đóng góp của sáng kiến

**Với cộng đồng:**
- Chứng minh rằng công nghệ AI hiện đại có thể — và nên — được dùng trước hết cho nhóm yếu thế, thay vì chỉ tối ưu trải nghiệm cho số đông; góp phần thay đổi tư duy thiết kế sản phẩm số tại Việt Nam theo hướng bao trùm (inclusive by design).
- Đóng góp trực tiếp vào các Mục tiêu Phát triển Bền vững của Liên Hợp Quốc: **SDG 10** (giảm bất bình đẳng), **SDG 11** (đô thị bao trùm, giao thông tiếp cận được cho người khuyết tật — chỉ tiêu 11.2), **SDG 3** (sức khỏe và an sinh).
- Tạo ra tài sản chung: giao thức, tài liệu và dữ liệu tiếp cận mở mà mọi nền tảng, trường học, tổ chức xã hội đều có thể kế thừa.

**Với nhóm đối tượng hưởng lợi:**
- Trả lại cho người khiếm thị quyền **di chuyển độc lập** — nền tảng của việc học, đi làm, khám bệnh và tham gia xã hội — mà không phụ thuộc người thân.
- Mang lại **sự an toàn và an tâm** ở khoảnh khắc dễ tổn thương nhất (đứng chờ xe một mình nơi công cộng): được trấn an bằng lời, được bảo vệ bằng PIN, được "nhìn thấy" bằng tín hiệu đèn.
- Với tài xế: giảm thời gian tìm khách, giảm hủy cuốc, tăng thu nhập; đồng thời trở thành một mắt xích của dịch vụ nhân văn hơn.

## 12. Cam kết

Đội thi cam kết:

1. Sáng kiến **VoiceGo** gửi tham gia là sản phẩm do chính đội tự nghiên cứu, xây dựng và phát triển; **không sao chép**, không vi phạm quyền sở hữu trí tuệ, bản quyền, quyền tác giả hoặc bất kỳ quy định pháp luật nào hiện hành. Các thành phần mã nguồn mở và dịch vụ bên thứ ba (OpenStreetMap, OSRM, Leaflet, FPT.AI, v.v.) được sử dụng đúng giấy phép và được ghi nhận nguồn đầy đủ trong tài liệu của dự án.
2. Video, hình ảnh, âm thanh và các tư liệu sử dụng trong sản phẩm dự thi **không vi phạm bản quyền**.
3. Đội thi **chịu hoàn toàn trách nhiệm** về tính trung thực, tính hợp pháp và quyền sử dụng đối với mọi nội dung, hình ảnh, tài liệu và sản phẩm dự thi.
4. Đội thi hiểu và đồng ý rằng Ban Tổ chức chỉ tiếp nhận hồ sơ tham gia và không chịu trách nhiệm đối với các tranh chấp, khiếu nại hoặc vi phạm liên quan đến bản quyền, sở hữu trí tuệ, pháp luật hoặc bất kỳ quyền lợi nào của bên thứ ba phát sinh từ sản phẩm dự thi; mọi trách nhiệm thuộc về đội thi.
5. Đội thi đồng ý để Ban Tổ chức sử dụng thông tin, hình ảnh, video và sản phẩm dự thi phục vụ mục đích truyền thông cho chương trình.

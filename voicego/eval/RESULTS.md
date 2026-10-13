# Kết quả eval vòng giọng nói — baseline 11–13/10/2026

Tài liệu này TÁCH RÕ **ĐÃ ĐO** (số từ các lần chạy dưới đây) với **ĐỀ XUẤT** (chưa có trong `src/`, cần Agent A
quyết và đo lại). Không sửa `src/` trong phần việc này. Cách chạy: [README.md](README.md).

## 0. Phiên bản được đo (provenance)

| Đo gì | Lúc | `liveStt.js` | `voiceRecorder.js` | `tts.js` | `useVoiceApp.js` |
|---|---|---|---|---|---|
| Live run `20261011T141452-A` (dev, 26 session) | 11/10 14:14 | `27cdf0c` | không ghi (giữa `7a5b46d`…`3b57eb7`) | `1954e79` | không ghi |
| Live run `20261013T092229-H` (holdout, 18 session) | 13/10 09:22 | `1ef2ca0` | `21c39bf` | `85c1136` | `7817aab` |
| Live run `20261013T093142-T` (đuôi 550/800, 12 session) | 13/10 09:31 | `1ef2ca0` | `21c39bf` | `85c1136` | `d7d8912` |
| Eval offline (vitest, chấm lại toàn bộ) | 13/10 09:32 | `1ef2ca0` | `21c39bf` | `85c1136` | `d7d8912` |

HEAD `f3c11fe` + thay đổi chưa commit của Agent A. Dữ liệu thô live **không phụ thuộc mã app** (clip mô phỏng bằng
hằng số: tiền ghi 1.024s, 5/8 khung VAD); các hàm được chấm (`cancelEcho`, `isBargeIn`, `silenceMsFor`, ngưỡng VAD)
**không đổi** giữa các hash trên (đã `git diff` kiểm). Mỗi file `results/*.json` ghi lại hash lúc chấm.
Ghi chú trung thực về run A: ban đầu ghi ở `datasets/echo_live.json`, sau đó chuyển sang `live/runs/`; metadata
cửa sổ (`echo_words_t`, `speech_end_ms`) được bổ sung **một lần** bằng cách dựng lại tất định từ định nghĩa clip —
finals/interims/timing của Gemini không đổi (ghi trong `meta.provenance_notes` của file).

Tổng lượt gọi Gemini: 1 (smoke) + 26 + 18 + 12 = **57 session**, 1 lỗi (handshake timeout ở holdout, giữ trong mẫu số).

## 1. Thiết kế eval — đo gì, vì sao

| Nguyên tắc (nguồn) | Áp dụng ở đây |
|---|---|
| Đo outcome thật, tách loại lỗi; không một con số tổng (ch06; sách *Building Applications with AI Agents* ch9) | Tách false-barge / missed-barge / user-word loss / echo residue; báo riêng theo nguồn (real_gemini, synthetic, live dev, live holdout), không gộp |
| Pass@k khác pass^k; đừng để retry che bất ổn (ch06, SKILL.md) | 4 clip chạy 3 lần, báo cả pass@3 và pass^3 |
| Không loại lỗi khỏi mẫu số (sách ch2/ch9) | Báo attempted/errored mỗi run; session lỗi được đếm |
| Holdout độc lập khi chỉnh ngưỡng (sách ch9) | Luật đề xuất V1/V1c/V2 được viết trong `echo.test.js` **trước** khi chạy bộ H (câu mới); V1 nảy ra từ việc xem interim của run A nên run A không dùng để xác nhận V1 |
| Observability: runtime signals + correlation + revision (L11 / ch21; ch10 sách) | Hash file nguồn trong mỗi run và mỗi kết quả; parser `[turn]` cho máy thật |
| Latency là phân phối p50/p95/p99 kèm n; p99 với n<100 không đáng tin; tách chặng (latency skill, 01-measurement) | Mọi số độ trễ báo p50/p95/p99 + n, đánh dấu `*` khi n<100; dòng thời gian lượt tách chặng ở §6 |
| Replay là hợp đồng về input giữ lại + version (data-engineer-advanced) | Dữ liệu thô bất biến `live/runs/`, chỉ số dẫn xuất bằng bước riêng (vitest) -> đổi heuristic là chấm lại không gọi API |

Phát lại live **đúng logic app**: mỗi interim/final -> `onText` -> `cancelEcho(text, spokenWordsBetween(t0-800, now+300))`
tại đúng thời điểm đó -> `isBargeIn` -> `confirmBarge()`; hẹn giờ `BARGE_CONFIRM_MS` huỷ lượt nếu chưa xác nhận và
`onAutoStop` (hết tiếng + `silenceMsFor`) chưa tới; bản chốt cuối lượt dùng luật `barge.tts ? isBargeIn : kept>0`.
`LiveStt.finish()` được đo bằng **chính class `LiveStt`** với WebSocket giả + `vi.useFakeTimers` (gợi ý của Agent A).

## 2. Baseline — khử tiếng vọng / chen ngang (ĐÃ ĐO)

### 2.1 Dataset có nhãn (bản chốt, `echo_cases.json`)

| Nhóm | false-barge | missed-barge | user-word loss | echo residue | strict pass |
|---|---|---|---|---|---|
| real_gemini (3 ca, probe 48e3769) | 0/1 | 1/2 (R03: Gemini làm mất hẳn lời người dùng — lỗi tầng STT) | 33.3% | 0% | 2/3 |
| synthetic (67 ca) | **25.0%** (6/24) | 9.3% (4/43) | 17.3% | 5.2% | 77.6% |

Theo kiểu lỗi (strict pass): `reuse_3w` **25%** (2/8), `short_echo_2w` 0/3, `short_echo_1w` 0/1, `window_drift` 0/1,
`stray_word` 0/1; digits 93.8%, appended 91.7%, diacritics 3/3, split_word 3/4.

### 2.2 Live Gemini — transcript THẬT, phát lại theo logic app

| Run / policy | false-barge | missed-barge | user-word loss | echo residue | strict pass |
|---|---|---|---|---|---|
| **dev (A), cur** — 18 clip | **77.8% (7/9)** | 0% (0/9) | 7.3% | 3.9% | 55.6% |
| dev, cur, cửa sổ nội suy theo ký tự (giọng Edge) | 77.8% | 0% | 17.1% | 26.3% | 50.0% |
| **holdout (H), cur** — 17 clip (1 session lỗi) | **77.8% (7/9)** | 12.5% (1/8) | 9.7% | 10.0% | 52.9% |
| holdout, cur, cửa sổ nội suy | 88.9% | 0% | 0% | 27.1% | 52.9% |

Nguyên nhân 100% số false-barge live (cur): **interim đầu tiên của tiếng vọng chỉ 1–2 từ** ("tài xế", "cây số",
"Quận 1", "Honda", "nghìn đồng"), `cancelEcho` chỉ gỡ đoạn >= 3 từ, còn `isBargeIn` nhận `kept >= 2` hoặc `total <= 2`
-> `confirmBarge()` dừng hẳn AI ngay ở 445–1010ms, dù bản chốt cuối (3–4 từ) bị gỡ đúng. Tức là AI tự cắt lời mình
mỗi lần VAD báo nhầm lúc AI đang đọc và tiếng vọng còn tới được Gemini.

Độ ổn định (dev, 4 clip × 3 lần; transcript bản chốt **giống hệt** nhau ở cả 3 lần cho cả 4 clip):

| Policy | pass@3 | pass^3 | ghi chú |
|---|---|---|---|
| cur | 3/4 | 3/4 | `echo_p_g03_A2` hỏng cả 3 lần (false-barge tất định) |
| V1c (đề xuất) | 4/4 | 3/4 | `echo_p_g03_A2` qua ít nhất 1 lần nhưng không phải cả 3: bản chốt giống nhau nhưng **thời điểm interim** khác -> kết quả khác. Pass@k sẽ che đúng sự bất ổn này |

### 2.3 Độ trễ STT (live, ms; `*` = n<100, p99 chỉ tham khảo)

| Chặng | p50 | p95 | p99 | max | n |
|---|---|---|---|---|---|
| Hết tiếng nói -> bản chốt cuối (server VAD của Gemini tự chốt), dev+holdout | 585 | 733 | 746* | 750 | 27 |
| `audioStreamEnd` -> `LiveStt.finish()` trả (class thật, 3 run) | 0 | 397 | 623* | 874 | 55 |
| VAD kêu -> xác nhận chen ngang thật, cur | 552 | 761 | — | 783 | 10 |
| VAD kêu -> xác nhận chen ngang thật, V1c | 796 | 1762 | — | 1809 | 11 |

`finish()` trả vì: maybeFinish 38, done (generationComplete) 13, timeout 4 (cả 4 là nhánh 350ms "không có tiếng"),
chữ trả về == transcript thô 55/55; **không** có bản chốt nào về sau khi `finish()` đã trả (n=0).
Ở 37/55 lượt (dev 16/26, holdout 11/17, T 10/12) bản chốt về **trước** `audioStreamEnd`.

Bộ T (cùng 6 câu sạch, paired): hết tiếng nói -> có chữ = **623 ms p50 (max 763) với đuôi 550** so với **864 ms p50
(max 907) với đuôi 800**; chênh 209 ms p50, 144–292 ms, 6/6 cặp cùng chiều. Server tự chốt 451–763 ms sau khi hết
tiếng **bất kể** đuôi (T4: 763 vs 717, T6: 613 vs 608) -> `audioStreamEnd` sớm không làm bản chốt về sớm hơn; lượt
xong lúc max(chờ im lặng cục bộ, bản chốt server ≈ 450–760 ms).

## 3. Baseline — chốt lượt `silenceMsFor` (ĐÃ ĐO, `endpoint_cases.json`, 59 ca)

| Chính sách | chờ thừa ca complete p50/p95/mean (n=28) | cắt sớm ca incomplete (n=31) |
|---|---|---|
| **silenceMsFor (hiện tại)** | 550 / 1600 / 809 | **32.3%** |
| cố định 950 (Whisper) | 950 | 35.5% |
| cố định 800 | 800 | 64.5% |
| cố định 1600 | 1600 | 0% |

Chỉ trên chữ Gemini thật (15 ca): chờ 550 cho 6/6 câu trọn, nhưng cắt sớm **4/9** ca incomplete — đều là interim
Gemini **đặt dấu chấm lên mảnh câu** khi người dùng ngắt hơi: "Không." / "Được." / "Được rồi." / "Có." (thấy thật ở
run A). Synthetic: 5 câu trọn bị chờ 1600 vì từ cuối nằm trong HANGING ("đi chợ.", "đi bệnh viện.", "đặt xe.", "Ừ",
"đi ra."); "Khoan đã." / "Cho mình đi sân bay." bị cắt 550. `pause_ms` là **giả định**, nên tỉ lệ cắt sớm là so sánh
tương đối giữa chính sách, không phải tỉ lệ ngoài đời.

## 4. Baseline — VAD (ĐÃ ĐO trên mô phỏng, `vad.test.js`, 23 kịch bản)

Chính `VoiceRecorder` chạy qua AudioContext giả; giọng = đường bao RMS thật của TTS; ồn/vọng tổng hợp. Độ trễ ms p50/p95.

| Kịch bản | nghe được | trễ phát hiện p50/p95 | báo nhầm | ghi chú |
|---|---|---|---|---|
| Q1 yên tĩnh, giọng 0.02 | 75.0% (18/24) | 768 / 1195 | 0/phút | 6 ca trượt đều là câu ngắn |
| Q2 giọng nhỏ 0.006 / Q3 0.003 | 41.7% / 0% | 1323 / 1877 | 0 | ngưỡng sàn tuyệt đối 0.006 |
| Q4 "Không" (3 khung), "Dừng lại" (7 khung), AI im | **0% (0/24)** | — | — | cần 8 khung liên tiếp (683 ms) |
| T3 chen ngang bằng "Không" lúc AI đọc | **0% (0/12)** | — | — | cần 5 khung (427 ms) |
| Q5 / T4 ho 3 khung + cộp 1 khung | — | — | **0/phút** | bộ đếm khung chặn tốt |
| N1 phố ồn, xe máy 2s mỗi 15s, không ai nói | — | — | **4.0/phút** (lúc AI im) | mỗi xe máy chạy qua = một lượt gửi Gemini |
| N2 phố, giọng 0.03 / N3 0.015 | 70.8% / 12.5% | 939 / 1399 | 0 | |
| **N4 ồn 0.03 kéo dài ngay khi người dùng nói xong** | 100% | 683 | 2.0/phút | **chốt lượt sau 19.5 s, 6/6 chạm trần `maxTurnMs` 20 s** |
| T1 AEC rò 0.003 / T5 không AEC 0.02 / T6 0.04, 60 s | — | — | **0/phút** | học `_echoPeak` 1 s đầu đủ chặn |
| T11 vọng tăng 0.01 -> 0.03 sau 3 s | — | — | 1.0/phút, AI khựng 1.3 s/phút | |
| T2 AEC, chen ngang 0.02 | 91.7% | 427 / 1280 | 0 | |
| T7 / T10 / T8 / T9: giọng = 2× / 1.5× / 1× / 0.5× tiếng vọng | 91.7% / 58.3% / 25.0% / 0% | 512 / 1280 (T7) | 0 | phải to hơn ~2× **đỉnh** tiếng vọng (`_echoPeak`×1.25) |
| **T12 / T13 chen ngang 0.5 s sau khi AI bắt đầu (trước khi mic mở lúc 1 s)** | **25.0% / 16.7%** | 1280–1536 | 0 | xem lỗi B3 |
| T14 đáp ngay sau khi AI im | 75.0% | 768 / 1195 | 0 | nền không bị tiếng vọng làm phồng (P2 ok); trượt = câu ngắn |

Theo câu (giọng đủ to): "Dừng lại" 7 khung: 0% khi AI im, 100% khi AI đọc; "Không" 3 khung: 0% ở cả hai; "Đi xe máy"
9 khung: 90% khi AI im; mọi câu >= 14 khung: 100%. Ngừng nói -> chốt lượt = 939 ms (= 800 ms `getSilenceMs` cố định
trong mô phỏng + lượng tử khung).

## 5. Lỗi phát hiện (ĐÃ ĐO) và đề xuất tham số (ĐỀ XUẤT) — cho Agent A / trưởng nhóm tích hợp

**B1 — Interim ngắn của tiếng vọng xác nhận chen ngang -> AI tự cắt lời (nghiêm trọng).**
`useVoiceApp` `live.onText`: `if (barge.pending && isBargeIn(res)) confirmBarge()` chạy trên MỌI interim. Bằng chứng:
false-barge live 7/9 (dev) và 7/9 (holdout); cả 14 ca do một interim 1–2 từ ở 445–1010 ms (bảng "chữ nào làm AI dừng" trong output `echo.test.js`). Đề xuất **V1c** (đã chốt trước holdout, mã
tham chiếu `POLICIES.V1c` + `explainedByWindow()` trong `tests/eval/echo.test.js`): với interim, chỉ xác nhận khi phần còn
lại sau `cancelEcho` **không nằm liền** trong cửa sổ tiếng vọng; bản chốt cuối lượt giữ luật cũ; kèm `BARGE_CONFIRM_MS`
2500. Kết quả: dev 77.8% -> 11.1% false-barge, missed 0%; **holdout 77.8% -> 33.3%**, missed 12.5% -> **0%**, user-word
loss 9.7% -> 0%. Đổi lại: xác nhận chen ngang thật chậm hơn (p50 552 -> 796 ms, max 783 -> 1809 ms, n=10–11). V1 (giữ
1500 ms) làm trượt 1/9 dev, 1/8 holdout -> phải đi kèm 2500. V2 (áp cả cho bản chốt) không hơn V1 trên live, và trên
synthetic giảm false-barge 25% -> 8.3% nhưng tăng missed 9.3% -> 11.6% (mất các câu đáp "xe máy", "ô tô").

**B2 — Câu đáp lặp >= 3 từ của AI bị gỡ như tiếng vọng.** `cancelEcho` gỡ mọi đoạn khớp >= 3 đơn vị. Bằng chứng: live
`after_g035_A2` "Có, đặt xe tới đó đi." -> gửi agent "Có, đặt đi." (cửa sổ "xe tới đó không?"), lặp ở 3/3 lượt chạy;
synthetic `reuse_3w` strict pass 2/8 ("đi xe máy" -> rỗng, "Chợ Bến Thành" -> rỗng, "Đúng rồi, Đại học Bách Khoa" ->
"Đúng rồi,"). Đề xuất (CHƯA đo, cần holdout mới): khi AI đã im (`barge.tts` rỗng) chỉ gỡ đoạn khớp nằm ở ĐẦU transcript
(tiếng vọng đến trước lời đáp), hoặc yêu cầu run >= 4 khi AI đã im.

**B3 — Người dùng nói trước khi mic mở (1 s đầu câu AI) bị học thành "mức tiếng vọng".**
`voiceRecorder` `onaudioprocess`: khi `!this.recording` mọi khung lúc TTS phát đều cập nhật `_echoPeak`, kể cả giọng
người dùng; đỉnh chỉ giảm 0.995/khung (nửa đời ~11.8 s). Bằng chứng: T12/T13 nghe được 25% / 16.7% (so với T7/T2
91.7% khi chen sau lúc mic mở). Đề xuất: giới hạn đỉnh học được khi chưa nghe (ví dụ trần = 3× trung vị các khung TTS
gần nhất), hoặc giảm nhanh hơn (0.98/khung), rồi đo lại T12/T13 + T1/T5/T6 (không được tăng báo nhầm).

**B4 — Lệnh một từ không vượt được VAD.** `speechFrames` 8 / `speechFramesTts` 5 khung liên tiếp; "Không" (3 khung TTS)
0% ở mọi chế độ, "Dừng lại" (7) 0% khi AI im. Người thật nói chậm hơn TTS nên mức thật có thể khá hơn — cần đo bằng
`[turn]`. Đề xuất (CHƯA đo trên máy): khi AI vừa hỏi câu có/không, hạ `speechFrames` về 4–5 cho lượt đó; ho/cộp
3 khung hiện cho 0 báo nhầm/phút nên còn dư địa, nhưng phải chạy lại Q5/T4/N1.

**B5 — Ồn liên tục trên ngưỡng giữ lượt mở tới trần 20 s.** N4: 6/6 lượt chốt ở ~19.5 s. Trần `maxTurnMs` của Agent A
đúng là thứ cứu được; đề xuất thêm: khi `_peak` gần mức hiện tại suốt > 3 s sau khi hết chữ mới từ Gemini, chốt sớm
(Gemini đã có bản chốt). CHƯA đo.

**B6 — `silenceMsFor` tin dấu chấm trên mảnh câu.** 4/9 ca incomplete thật bị cắt 550 ("Không.", "Có."...). Đề xuất:
câu <= 1 từ có nghĩa + dấu chấm -> 800 thay vì 550; bỏ "chợ", "ra", "ừ" khỏi HANGING khi đứng sau động từ ("đi chợ.").
Ước lượng trên dataset (giả định pause_ms) — cần đo lại trên holdout endpoint mới trước khi đổi.

**Hằng số đoán (Agent A hỏi) — số quan sát được:**

| Hằng số | Hiện tại | Quan sát (n) | Gợi ý |
|---|---|---|---|
| `BARGE_CONFIRM_MS` | 1500 | xác nhận thật: cur max 783 (n=10); V1c p95 1762, max 1809 (n=11) | giữ 1500 với luật cur (≈1.9× max); **2500 nếu áp V1** (≈1.4× max). 2×p99 ≈ 3.6 s không dùng được vì mỗi báo nhầm làm AI khựng chừng đó; n quá nhỏ cho p99 |
| `finish()` timeout | 1500 | `audioStreamEnd` -> xong p95 397, p99 623*, max 874 (n=55) | 2×p99 ≈ 1.25 s -> 1500 hợp lý; giữ tới khi có `[turn]` n>=100 |
| drain sau timeout/cancel | 2000 | không có bản chốt muộn nào (n=0); bản chốt sau `audioStreamEnd` max 874 ms | chưa đủ dữ liệu; giữ 2000 (≥2× max quan sát) |
| Edge không có tiếng 10 s | 10 s | chưa đo (cần dữ liệu thật) | chờ log `[turn]` |
| đuôi im lặng `silenceMsFor` 800 (câu không dấu chấm) | 800 | đuôi 800 tốn thêm 209 ms p50 so với 550 (n=6 cặp); server tự chốt 451–763 ms | ĐỀ XUẤT: khi đã có bản chốt server (`maybeFinish`) mà chữ không lơ lửng, chốt lượt ngay thay vì chờ đủ 800 -> tiết kiệm ước ~200–300 ms. Phải kiểm cắt sớm (B6) trước |

## 6. Dòng thời gian một lượt (Gemini Live) — chặng nào đã đo

| Chặng | Số | Nguồn |
|---|---|---|
| VAD xác nhận tiếng nói (AI im / AI đọc) | 768 / 427–512 ms p50 sau khi bắt đầu nói | mô phỏng VAD |
| Chờ im lặng cục bộ (endpoint) | 550 / 800 / 1600 theo `silenceMsFor` | thiết kế + endpoint eval |
| Bản chốt Gemini sau khi hết tiếng | 585 ms p50, 750 max (n=27) | live |
| `finish()` sau `audioStreamEnd` | 0 ms p50, 397 p95 (n=55) | live, class thật |
| Agent (request -> câu đầu) | **chưa đo** ở đây | log `[turn]` |
| TTS tiếng đầu tiên (Edge ~0.9–2.7 s theo 664976c; trình duyệt ~tức thì) | **chưa đo** ở đây | log `[turn]` |

Log máy thật: `node voicego/eval/turnlog_report.mjs <console.log> --by engine` in p50/p95/p99 + n cho mọi trường `…Ms`
và mốc `t.*` của `turnTrace.js` (endpointToTextMs, liveFinalMs, whisperMs, bargeConfirmMs, bargeFalseAlarmMs, …), đếm
`outcome`/`finishReason`/`fallback`/trường lạ, đếm dòng hỏng và dòng trùng. Hook chưa gọi `turnTrace` lúc chạy eval này,
nên parser được kiểm trên mẫu tự viết (`datasets/turnlog_sample.log`), chưa có số thật.

## 7. Giới hạn và sai lệch đã biết

- **Giọng TTS, không phải người thật / mic điện thoại thật.** "Người dùng" = vi-VN-NamMinhNeural, AI = HoaiMyNeural; tiếng
  vọng = giọng AI qua bộ lọc dải + vài phản xạ (`PHONE_ECHO_AF`), không phải loa + AEC + AGC thật. Gemini chép giọng TTS
  sạch tốt hơn giọng người ngoài phố (STT word recall ~97% ở đây) -> số live là **cận trên** cho tầng STT.
- **Synthetic do chính người viết eval tạo, sau khi đọc mã `cancelEcho`.** Dễ dồn vào biên của luật (rò rỉ giả định);
  tỉ lệ từng nhóm không phải tỉ lệ ngoài đời. Vì vậy báo riêng từng nguồn và xác nhận đề xuất trên holdout live.
- **Holdout nhỏ** (9 echo, 8 user) và cùng kiểu tạo clip với dev; SE ≈ sqrt(p(1−p)/n) ≈ ±16 điểm % ở p=0.33, n=9.
  V1c tốt hơn cur ở holdout (7/9 -> 3/9 false-barge, paired cùng clip) nhưng cần thêm dữ liệu thật trước khi coi là chắc.
- Các false-barge còn lại của V1c đều do Gemini **nghe sai tiếng vọng 1 từ** ("cho bạn nhé"->"Chào bạn nhé", "bốn trăm
  mét"->"400 m", "Tân Sơn Nhất"->"Tây Sơn Nhất") — khớp mờ (edit distance <= 1 sau bỏ dấu) là ứng viên kế, cần holdout mới.
- VAD: mức RMS lấy từ comment mã và `vad_test.mjs`, không đo trên máy; khung = hằng RMS (không mô phỏng phổ); phản ứng
  app tối giản (không có Gemini, mở lại mic sau 1 s cố định). `pause_ms` của endpoint là giả định.
- Không đo: agent latency, TTS first sound, Whisper branch, session drop thật, máy iOS/Android.
- `npm run eval` chạy song song theo file; trên máy đông agent đã gặp Node OOM -> dùng `--no-file-parallelism`.

## 8. Việc tiếp theo

1. Agent A nối `turnTrace` vào hook -> thu >= 100 lượt `[turn]` trên 2–3 máy thật -> chạy `turnlog_report.mjs`; khi đó
   mới chọn timeout theo p99 (Edge no-sound, drain, finish).
2. Nếu áp V1c: thêm vào `echo.test.js` một run holdout MỚI (bộ câu khác H) trước khi coi là đã xác nhận lần 2.
3. Ghi vài phút audio mic thật (có AEC/không AEC, ngoài phố) -> thay đường bao TTS trong VAD eval bằng đường bao thật.
4. Eval VAD với `speechFrames` theo ngữ cảnh (B4) và trần `_echoPeak` (B3) — chạy lại toàn bộ `vad_scenarios.json`.

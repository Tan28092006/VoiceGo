# voicego/eval — bộ đánh giá vòng giọng nói

Đo thay vì đoán khi chỉnh tham số của vòng giọng nói (khử tiếng vọng, chen ngang, chốt lượt, VAD).
Kết quả, baseline và đề xuất nằm trong [RESULTS.md](RESULTS.md).

## Cấu trúc

| Đường dẫn | Là gì |
|---|---|
| `datasets/echo_cases.json` | 70 ca có nhãn cho `cancelEcho`/`isBargeIn` (3 `real_gemini` + 67 `synthetic`) |
| `datasets/endpoint_cases.json` | 59 ca complete/incomplete cho `silenceMsFor` (15 chữ Gemini thật + 44 synthetic) |
| `datasets/vad_envelopes.json` | Đường bao RMS thật theo khung 4096@48k của 12 câu TTS (sinh bằng `live/make_vad_envelopes.py`) |
| `datasets/vad_scenarios.json` | 23 kịch bản VAD (yên tĩnh, phố ồn, AI đọc có/không AEC, ho/cộp, ồn trên ngưỡng) |
| `datasets/turnlog_sample.log` | Mẫu tự viết để kiểm parser log `[turn]` |
| `live/live_echo_eval.py` | Eval LIVE (opt-in, gọi Gemini thật, tốn quota) |
| `live/runs/<run_id>.json` | **Dữ liệu thô bất biến**, mỗi lần chạy một file, kèm hash file nguồn |
| `results/*.json` | Chỉ số **dẫn xuất** (ghi đè mỗi lần chạy eval offline), kèm hash `src/` lúc chấm |
| `turnlog_report.mjs` | Tổng hợp log `[turn]` từ máy thật -> p50/p95/p99 + tỉ lệ timeout/fallback |
| `../frontend/tests/eval/*.test.js` | Các eval offline (vitest) |

## Chạy

```bash
# Offline, tất định, không mạng — chạy TUẦN TỰ để tránh hết RAM khi nhiều agent cùng chạy test:
cd voicego/frontend && npx vitest run tests/eval --no-file-parallelism
#   (npm run eval cũng chạy được, nhưng song song theo file)

# Live (gọi gemini-3.5-transcribe-live, key trong voicego/backend/.env, không in ra). HỎI trước khi chạy.
py -3.13 voicego/eval/live/live_echo_eval.py --set A            # dev: 18 clip + lặp 4 clip x2 = 26 session
py -3.13 voicego/eval/live/live_echo_eval.py --set H --repeat 1 # holdout: 18 session
py -3.13 voicego/eval/live/live_echo_eval.py --set T --repeat 1 # đuôi im lặng 550 vs 800: 12 session
py -3.13 voicego/eval/live/live_echo_eval.py --set A --dry-run  # chỉ tổng hợp audio + in kế hoạch

# Log [turn] từ máy thật (dán console vào file):
node voicego/eval/turnlog_report.mjs console.log --by engine
```

Đổi heuristic trong `src/` rồi chạy lại eval offline = chấm lại trên **cùng** transcript Gemini thật đã lưu
(backfill), không tốn thêm lượt gọi API. Không chạy vitest trong lúc eval live Python đang chạy.

# VoiceGo — hướng dẫn cho agent / phiên mới

Đặt xe bằng giọng nói cho người khiếm thị (tiếng Việt). Một service Docker: FastAPI phục vụ
API + bản React đã build (`frontend/dist`) + Socket.IO (luồng PIN) trên cùng origin.

- **Production:** https://voicego-9k11.onrender.com (Render **free**, 1 web service Docker).
- Problem/solution/feature: [`../README.md`](../README.md). File này: chạy, test, deploy, trạng thái.
- Khi kết thúc phiên: chạy lại mục 2, cập nhật mục 8 (trạng thái), ghi rõ cái gì **chưa chạy**.

## 0. Quyền hành động của agent trên repo này

Ranh giới theo tác động thật (hành động, tài nguyên, chi phí, có đảo ngược được không), không theo loại task.

| Được tự làm (không cần hỏi) | Phải hỏi user trước |
|---|---|
| Đọc code/docs, `npm test`, `npm run test:live` **khi thiếu** `VITE_BACKEND_URL` (tự skip), `py -m pytest -q` | `git commit` / `git push` lên `main`: **push = Render tự deploy production** (free plan, không có staging) |
| Chạy server local (`uvicorn` cổng riêng, `npm run dev`), rồi tắt | Mọi thứ gọi API trả phí / có quota: DeepSeek (`/api/agent/chat*`), Gemini (`test:live`, eval live, `/api/voice/live-token`, geocode), Groq Whisper, `smoke_test.sh` (gọi TTS + agent), `backend/test_lang_bac.py` |
| Build vào thư mục tạm (`npx vite build --outDir <tmp>`), `docker build --target frontend` | Đọc/sửa/in `backend/.env`, `.env.production`, secret trên Render |
| `curl` GET `/api/health` của production (chỉ đọc) | Ghi DB (`POST /api/db/seed`, đặt chuyến thật), đổi `render.yaml`, DNS, Render dashboard |
| Sửa code/test trong phạm vi task được giao | `npm install` thêm package, `npm audit fix`, xoá file/lịch sử, `npm run build` ghi đè `frontend/dist` (đang được git theo dõi) |

Tách thay đổi thành nhiều commit: thứ gì đã stage (kể cả `git rm`) sẽ vào commit KẾ TIẾP. Xem
`git diff --cached --stat` trước mỗi `git commit` (đã dính: xoá `places_db.py` rơi vào commit agent).

Function call đúng schema chưa phải là được phép: kiểm tra quyền và điều kiện nghiệp vụ tại chỗ commit
(ví dụ `book_ride` chỉ sau khi user xác nhận giá — được prompt ép trong `agent.py`, chưa có gate cứng ở backend).

## 1. Bản đồ

| Đường dẫn | Nội dung |
|---|---|
| `backend/main.py` | FastAPI app, mọi route `/api/*`, phục vụ `../frontend/dist`, `socket_app` = app + Socket.IO |
| `backend/agent.py` | Agent hội thoại (DeepSeek, OpenAI-compatible function-calling): resolve → quote → book |
| `backend/geocode.py`, `routing.py` | Tìm địa điểm (Gemini đề xuất tên/cơ sở → Nominatim, rồi Mapbox chốt toạ độ; không có danh bạ viết cứng), tuyến đường (Mapbox → OSRM) |
| `backend/voice.py` | Whisper STT (Groq), ephemeral token cho Gemini Live, Edge TTS, warmup |
| `backend/realtime.py` | Socket.IO relay nhúng trong FastAPI (không còn server Node :3001) |
| `backend/db.py` | MongoDB; thiếu DB thì route DB trả `database_unavailable` |
| `backend/tests/` | Test offline: deploy contract (health, no-cache), PIN relay Socket.IO, ghim địa điểm theo cơ sở (`test_geocode_branches.py`), chặn danh bạ địa điểm viết cứng (`test_no_hardcoded_places.py`) |
| `backend/test_agent_stream.py` | Test offline agent streaming (`/api/agent/chat_stream`) với LLM giả, cần pytest |
| `backend/test_lang_bac.py` | **Benchmark gọi API thật** (Gemini/Nominatim/Mapbox/DeepSeek/TTS), không phải unit test |
| `frontend/src/hooks/useVoiceApp.js` | Điều phối vòng giọng nói: mic → STT → agent → TTS, barge-in, PIN chain |
| `frontend/src/services/` | Xem mục 5 |
| `frontend/tests/unit/` | Vitest unit tests (fake browser globals, không mạng) |
| `frontend/tests/live/` | Test thật với backend + Gemini Live (tự skip nếu thiếu env) |
| `frontend/tests/eval/`, `eval/` | Eval offline trên dữ liệu thô đã lưu (`eval/live/runs`, KHÔNG gọi API). `shipped_turn.test.js` chấm đúng hàm hook đang ship (`assessTurn`/`bargeTimeout` + hằng số đọc từ `useVoiceApp.js`). `eval/live/` = script gọi API thật (hỏi trước): `live_echo_eval.py`, `geo_trace.py`. Đọc `eval/README.md`, `eval/RESULTS.md` |
| `Dockerfile`, `.dockerignore`, `../render.yaml` | Build 2 stage (node:20-alpine → python:3.11-slim), Render Blueprint |
| `smoke_test.sh`, `warmup.sh` | Kiểm sau deploy / đánh thức service, mặc định trỏ onrender. `smoke_test.sh` gọi TTS + agent thật (tốn quota) |
| `*.html`, `css/`, `js/`, `assets/` ở `voicego/` | Mockup tĩnh cũ, không được app dùng, không vào image |
| `backend/routes/auth.js`, `backend/models/User.js` | Tàn dư Express, không chạy |

## 2. Lệnh (đã chạy thật 2026-10-13 trên `0f979f4` + pass harness, Windows, Node 24, Python 3.13)

```bash
# Frontend unit tests (vitest, node env, fake browser globals): 14 files / 104 tests pass
cd voicego/frontend && npm install && npm test
# Eval offline (đọc eval/datasets + eval/live/runs, không gọi API; đã chạy tuần tự sẵn): 6 files / 10 tests
npm run eval
# Live STT test: skip khi thiếu VITE_BACKEND_URL (tốn quota Gemini, ~2 phút, có bước chờ 70s)
VITE_BACKEND_URL=http://127.0.0.1:8011 npm run test:live

# Backend tests offline (không cần key/Mongo/mạng): 59 pass
cd voicego/backend && py -m pytest -q           # pytest.ini bỏ qua test_lang_bac.py (benchmark gọi API thật)

# Chạy backend (cần backend/.env, xem mục 3). Dùng socket_app, KHÔNG phải main:app (mất Socket.IO)
cd voicego/backend && py -m uvicorn main:socket_app --port 8000
# Frontend dev: HTTPS tự ký :5173, proxy /api + /socket.io về :8000
cd voicego/frontend && npm run dev

# Kiểm build mà không ghi đè frontend/dist (dist đang được git theo dõi)
cd voicego/frontend && npx vite build --outDir <thư-mục-tạm-ngoài-repo>
# Kiểm stage build frontend của Docker (~30s)
cd voicego && docker build --target frontend -f Dockerfile .

# GitNexus (từ gốc repo). Index theo COMMIT: thay đổi chưa commit không được index lại. Repo này
# cần heap lớn, không thì "JavaScript heap out of memory":
NODE_OPTIONS=--max-old-space-size=6144 node .gitnexus/run.cjs analyze
node .gitnexus/run.cjs impact <symbol> -d upstream -f <file>     # khi MCP gitnexus không kết nối được
```

- Nhiều agent/phiên cùng chạy vitest + Python live eval từng làm Node hết RAM: chạy tuần tự
  (`--no-file-parallelism`, `npm run eval` đã có sẵn).
- Kiểm sau deploy (chỉ đọc): `/api/health` 200; route mới tồn tại thì `POST <route>` với body `{}` trả 422.
  Đừng dò bằng `GET`: route frontend bắt-tất-cả trả `index.html` 200 cho mọi đường dẫn.
- Chưa chạy: build full image, `smoke_test.sh` (gọi TTS + agent thật), `test:live`.

## 3. Biến môi trường (default lấy từ code)

Backend đọc `backend/.env` qua `load_dotenv` (không ghi đè biến đã set). Template: `backend/.env.example`.
Giá trị production: `../render.yaml`. **Không in giá trị trong `.env`.**

| Biến | Default | Ghi chú |
|---|---|---|
| `DEEPSEEK_API_KEY` (hoặc `LLM_API_KEY`) | rỗng | Thiếu = app lên xanh nhưng agent câm |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_GEOCODE_MODEL` | `https://api.deepseek.com` / `deepseek-chat` / `deepseek-chat` | |
| `GEMINI_API_KEY`, `GEMINI_API_KEYS` (phẩy), `GEMINI_API_KEY_2..9` | rỗng | Pool key cho Gemini Live token + geocode. Không có key → `gemini_live:false`, STT lùi về Whisper |
| `GEMINI_MODEL` / `GEMINI_MODELS` / `GEMINI_FALLBACK_MODEL` | `gemini-2.5-flash` / rỗng / `gemini-3.1-flash-lite` | `GEMINI_MODELS` = model theo từng key |
| `GEMINI_GROUNDING` | `false` | Google Search grounding. Key **miễn phí** hiện tại trả 429 cho mọi lượt có grounding (đo 2026-10-13, cả 3 key) → cần key bật billing. Bật mà grounding 429 trên mọi key thì code tự tắt grounding 60 phút, không treo key |
| `STT_ENGINE` | `gemini-live` (mọi giá trị khác `whisper`) | Mặc định server; nút Header ghi đè theo máy |
| `GEMINI_LIVE_MODEL` | `gemini-3.5-transcribe-live` | |
| `GROQ_WHISPER_KEY` / `GROQ_WHISPER_MODEL` | rỗng / `whisper-large-v3` | Nhánh Whisper + fallback của Gemini Live |
| `TTS_ENGINE` | `browser` (mọi giá trị khác `edge`) | |
| `EDGE_VOICE` | `vi-VN-HoaiMyNeural` | |
| `MONGODB_URI` / `MONGODB_DB` / `DEMO_PASSENGER_ID` | `mongodb://localhost:27017` / `voicego` / `demo-passenger-visual` | |
| `MAPBOX_TOKEN` | rỗng | Rỗng → OSM/OSRM |
| `PORT` | `8000` | Dockerfile |
| `VITE_BACKEND_URL` (frontend, lúc build) | rỗng = same-origin | |

Không còn được code đọc (vẫn nằm trong `render.yaml` và docs cũ): `FPT_API_KEY`, `TTS_PRIMARY`, `GROQ_API_KEY`, `GROQ_MODEL`.

## 4. Deploy (Render free)

- `../render.yaml` (Blueprint): `plan: free`, `runtime: docker`, `dockerfilePath ./voicego/Dockerfile`,
  `dockerContext ./voicego`, `healthCheckPath /api/health`, `autoDeployTrigger: commit` → **push lên `main` là deploy**.
  Render đặt `WEB_CONCURRENCY=1`.
- Free plan ngủ khi idle: request đầu cold start ~30-50s (đo được 25s cho `/api/health`); frontend hiện "Đang kết nối máy chủ…".
- **Bẫy đã dính:**
  - `/api/health` phải nhẹ: không gọi Mongo/mạng. Trước f3c11fe nó chạy 10 truy vấn Mongo (~2.4s) → deploy "Timed Out" dù server chạy. Chi tiết Mongo ở `/api/db/status`. Được khoá bằng `backend/tests/test_deploy_contract.py`.
  - `index.html` phải trả `Cache-Control: no-cache` (9a63a0b), không thì trình duyệt chạy JS cũ sau deploy. Cũng có test.
  - `/api/health` nhận cả HEAD (monitor dùng HEAD).
  - Đừng cắm uptime monitor 24/7: quota 750h free tính cho cả workspace (xem `DEPLOY_DOMAIN.md` phần E).
- Sau deploy: `curl -s https://voicego-9k11.onrender.com/api/health`, rồi (tốn quota) `bash voicego/smoke_test.sh https://voicego-9k11.onrender.com`.
- Khôi phục service: [`RECOVERY.md`](RECOVERY.md) (Blueprint vẫn đúng; phần domain chưa xác minh).
- Lỗi thời: [`DEPLOY.md`](DEPLOY.md) (Vercel + backend riêng + keep-alive). Chưa xác minh: [`DEPLOY_DOMAIN.md`](DEPLOY_DOMAIN.md)
  (`voicego.res3pl.com` trả NXDOMAIN ngày 2026-10-11).

## 5. Vòng giọng nói: file → trách nhiệm

| File | Trách nhiệm | Test |
|---|---|---|
| `hooks/useVoiceApp.js` | Điều phối lượt (mỗi lần nghe một object lượt riêng): mở mic sau khi AI đọc xong, chọn STT, gửi agent (stream), đọc trả lời qua hàng đợi, barge-in (pause → xác nhận → stop), PIN must-hear, engine mặc định từ `/api/health` | chưa có unit; quyết định chen ngang được chấm qua `tests/eval/shipped_turn.test.js` |
| `services/voiceRecorder.js` | Mic + VAD theo RMS (noise floor giữ qua lượt, echo peak lúc AI đọc), tiền ghi ~950ms, WAV cho Whisper, PCM 16kHz cho Gemini Live, watchdog `noAudio` | `voiceRecorder.*.test.js` |
| `services/liveStt.js` | Gemini Live qua WebSocket thẳng từ trình duyệt (token từ `/api/voice/live-token`, hạn 5s), keepalive, nối segment, `turnDropped` → fallback Whisper; **`assessTurn`** = chỗ duy nhất quyết định echo/user (dùng `cancelEcho`, `explainedByWindow`), `bargeTimeout`, `silenceMsFor` | `liveStt.*.test.js`, `assessTurn.test.js`, `tests/eval/`, `tests/live/` |
| `services/tts.js` | `speak()`: giọng trình duyệt (speechSynthesis, chia câu ≤180 ký tự) hoặc Edge (`/api/voice/tts_stream`), fallback chéo, pause/resume giả lập, timeline từ đã phát (cho echo) | `tts.*.test.js` |
| `services/browserStt.js` | Web Speech API, lưới đỡ khi Whisper lỗi | chưa có |
| `services/api.js` | REST + streaming reply của agent (SSE, `runAgentTurn`, fallback `/api/agent/chat`), Whisper hạn 12s | `agentStream.test.js` |
| `services/turnTrace.js` | Mỗi lượt in MỘT dòng `[turn] {json}` (các mốc thời gian) → `node voicego/eval/turnlog_report.mjs <log>` ra p50/p95/p99 | `turnTrace.test.js` |
| `services/socket.js`, `beacon.js`, `config.js` | Socket.IO (PIN), đèn nháy + rung "10 mét cuối", `BACKEND_URL` | chưa có (relay phía server: `backend/tests/test_pin_relay.py`) |
| `context/AppContext.jsx` | State + lựa chọn engine theo máy (`localStorage` `voicego.stt`, `voicego.tts`) | chưa có |

Lý do thiết kế và số đo: đọc `git log` của 91175bd, c4728e7, 664976c, 03fcd82, 48e3769, d2ee6ef, 9e4a1f1, 0f979f4
(commit body ghi đủ), và `eval/RESULTS.md`.

### Luồng có state: cái gì giữ state, kiểm bằng gì

| Luồng | State có thẩm quyền | Đã kiểm | Chưa kiểm / rủi ro |
|---|---|---|---|
| Đặt chuyến (`book_ride` → `db.create_ride_request`) | MongoDB `ride_requests` | `test_agent_stream.py`: stream chết sau `book_ride` rồi fallback → chỉ 1 chuyến (`_book_once`, khoá theo lượt, in-memory 15 phút) | Idempotency mất khi restart / nhiều worker. Mongo lỗi → `ok:true` + tài xế giả + `dbSaved:false`: backend không dùng câu mẫu, nhưng **frontend vẫn đọc "Đã đặt xe…" khi có `ui.booked`** (chưa sửa) |
| Tìm địa điểm (`resolve_destination` → `geocode.resolve_locations`) | Không (Gemini đề xuất, Nominatim/Mapbox chốt) | `test_geocode_branches.py` (13, offline); kiểm thật bằng `eval/live/geo_trace.py` (hỏi trước) | Nơi nhiều cơ sở mất 10–18 s (Nominatim 1 req/s); nơi OSM không có (vd ĐH CNTT) trả `verified:false` với toạ độ Gemini |
| PIN handoff (`realtime.py`, Socket.IO) | **Một** dict `_trip` toàn cục trong RAM của process | `backend/tests/test_pin_relay.py`: accept chưa lộ PIN, arrive gửi PIN cho khách, PIN đúng → `pin-verified` cả hai, sai → `pin-failed` chỉ tài xế, khách ngắt → xoá trip | 2 khách cùng lúc ghi đè nhau; restart/ngủ (Render free) mất trip; chỉ đúng với 1 worker (`WEB_CONCURRENCY=1`); reconnect socket thật; tài xế mô phỏng khi không ai online |
| Lượt giọng nói (mic → STT → agent → TTS) | State trong `useVoiceApp.js` (client) | Unit test từng service trên fake | Không có test cho `useVoiceApp.js`; chưa có journey end-to-end tự động |

Kiểm tay luồng tài xế: 2 trình duyệt (khách + `DriverView`) theo [`DEMO.md`](DEMO.md).

## 6. Nút chỉnh qua URL (không cần build lại)

| Query | Default | Ý nghĩa |
|---|---|---|
| `?debug=1` | tắt | Overlay VAD trên màn hình |
| `?bargein=<ms>` | 1000 (Gemini Live) / 4000 (Whisper) | Bao lâu sau khi AI bắt đầu đọc thì cho chen ngang |
| `?bargeconfirm=<ms>` | 1500 | Chờ Gemini xác nhận lời thật trước khi AI đọc tiếp |
| `?bargeextend=<ms>` | 700 | Gia hạn MỘT lần khi server vẫn đang nghe thấy tiếng nói |
| `?maxturn=<ms>` | 20000 | Lượt nói dài tối đa (chỗ ồn liên tục), quá thì tự chốt |
| `?vadframes=<n>` | 8 | Số khung (~85ms) liên tiếp đủ to mới là tiếng nói |
| `?vadframestts=<n>` | 5 | Như trên, lúc AI đang đọc (Gemini Live) |
| `?vadmin=<rms>` | 0.006 | Sàn tuyệt đối |
| `?vadmult=<x>` | 4.5 | Vượt noise floor bao nhiêu lần |
| `?vadtts=<x>` | 1.9 | Hệ số ngưỡng thêm lúc AI đọc |
| `?realtime=<url>` | same-origin | Socket.IO ở host khác |

## 7. Rủi ro đã biết

- **DNS máy dev** có thể trả `nominatim.openstreetmap.org` về `127.0.0.1` (đã gặp 2026-10-13): mọi lần tra Nominatim
  lỗi (giờ có log `[geocode] Nominatim lỗi`) và luồng rơi xuống Mapbox — khác production. Thử thật:
  `eval/live/geo_trace.py --nominatim-ip <IP từ nslookup ... 8.8.8.8>`.
- Tìm địa điểm lần đầu mất ~8–13 s: Gemini gọi thường 3–8 s (đo 2026-10-13) + Nominatim 1.1 s/lần, tuần tự.
  Kết quả được nhớ 6 giờ theo (câu nói, ô ~1 km quanh điểm đón) → lần sau ~0 s. Agent không nói gì trong lúc chờ.
- Gemini (không grounding) hay đưa địa chỉ cấp phường không số nhà và đôi khi chép toạ độ điểm đón: `_pin` chỉ dùng
  địa chỉ có số nhà + đường làm mốc; địa chỉ cấp phường có tên chữ chỉ để CHỌN giữa các cơ sở xa nhau (≤6 km), không để ghim.
- `frontend/dist` được commit nhưng Docker build lại (`.dockerignore` loại nó); bản trong git có thể cũ.
- `npm audit`: vitest 3.2.7 có advisory (dev-only, fix cần vitest 4.1.11+); production deps: 1 high (`socket.io-parser`).
- Gemini quota theo key (model 2.5-flash bị khoá với key mới, xem comment `GEMINI_MODELS` trong `render.yaml`).
- Commit `d2ee6ef` đứng riêng không import được (đã xoá `places_db.py` trước commit geocode): đừng bisect dừng ở đó.
- `render.yaml` còn khai `FPT_API_KEY`, `TTS_PRIMARY` (không còn dùng): để nguyên vì Blueprint sync vào service thật.
- `MO_TA_SANG_KIEN.md` (hồ sơ dự thi) còn mô tả "gazetteer đã xác minh": lịch sử, hỏi user trước khi sửa.

## 8. Trạng thái (ghi lại mỗi phiên, kèm revision)

2026-10-13, HEAD `0f979f4` (đã deploy) + pass harness (commit ngay sau):
- **Production đã kiểm (chỉ đọc):** `/api/health` 200 (0.27 s); `POST /api/agent/chat_stream {}` → 422 (route có);
  bundle đang phục vụ chứa `[turn]` và "Micro chưa chạy".
- **Đã kiểm (có output):** frontend unit 104/104; eval 10/10 — `shipped_turn` trên dữ liệu thô Gemini: false barge-in
  dev 1/9, holdout 3/9, bỏ sót chen ngang thật 0/17, mất lời 0% (đổi hằng số hook → eval đỏ, đã thử); backend 59/59.
- **Kiểm thật bằng API (không trên thiết bị):** tìm địa điểm đúng cho Bách Khoa (2 điểm đón), BV Nguyễn Tri Phương,
  Landmark 81, KHTN (2 cơ sở), Bến Thành, Nhà thờ Đức Bà, Tân Sơn Nhất; ĐH CNTT `verified:false`. Sau đó (chưa deploy
  lúc ghi) sửa thêm theo ca user báo "trường học tự nhiên": không ghim theo địa chỉ cấp phường (đã ra "Trạm Y Tế Phường
  Linh Trung"), không trả lại điểm đón khi Gemini chép toạ độ, nhớ kết quả 6 giờ, grounding tự tắt khi 429.
  Câu mẫu báo giá: lượt báo giá p50 1973 → 1388 ms (n=3, DeepSeek thật).
- **Chưa có bằng chứng trên điện thoại thật** (Android Chrome, iOS Safari, loa ngoài): mức echo thật, chen ngang
  P1–P4, pause giả lập speechSynthesis trên Android, unlock iOS, watchdog `noAudio`, SSE qua proxy Render
  (`curl -N` chưa chạy), PIN must-hear đọc lại, PIN handoff giữa 2 máy, `beacon.js`.
- **Bước tiếp theo:** thử trên máy thật với `?debug=1`, dán console → `node voicego/eval/turnlog_report.mjs` → chỉnh
  1500/700 ms, 10 s Edge theo p99 thay vì đoán; sửa frontend khi `dbSaved:false`; holdout thứ hai cho luật V1c.

## 9. Docs khác: đọc khi nào

| Doc | Đọc khi | Ghi chú |
|---|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Cần sơ đồ tổng thể, quyết định thiết kế agent/geocode | |
| [`eval/README.md`](eval/README.md), [`eval/RESULTS.md`](eval/RESULTS.md) | Trước khi chỉnh tham số vòng giọng nói | Số đo + cách chấm lại không tốn API |
| [`SETUP.md`](SETUP.md) | Cài máy mới, tài khoản demo | |
| [`RECOVERY.md`](RECOVERY.md) | Service chết / phải dựng lại | |
| [`REALTIME_INTEGRATION.md`](REALTIME_INTEGRATION.md) | Sửa sự kiện Socket.IO / PIN | |
| [`DEMO.md`](DEMO.md), [`USER_GUIDE.md`](USER_GUIDE.md) | Kịch bản demo, hướng dẫn người dùng | |
| [`PLAN_V2_INTEGRATION.md`](PLAN_V2_INTEGRATION.md) | Kế hoạch tích hợp đối tác (chưa commit) | Kế hoạch, không phải hiện trạng |
| `WORK_BREAKDOWN.md`, `MO_TA_SANG_KIEN.md`, `ATTRIBUTION.md` | Lịch sử phân công, hồ sơ dự thi, giấy phép | Ghi FPT.AI/Groq: lịch sử, không phải stack hiện tại |
| [`DEPLOY.md`](DEPLOY.md), [`DEPLOY_DOMAIN.md`](DEPLOY_DOMAIN.md) | Xem mục 4 | Lỗi thời / chưa xác minh |

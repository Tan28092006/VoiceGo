# VoiceGo — Tech Stack & Architecture

## Tech stack
| Lớp | Công nghệ |
|---|---|
| Frontend | React 18 + Vite, Leaflet (bản đồ), Socket.IO client, CSS thuần |
| Backend | Python 3 + FastAPI + Uvicorn |
| STT (nhận giọng) | **Gemini Live** `gemini-3.5-transcribe-live` (mặc định, WebSocket thẳng từ trình duyệt bằng ephemeral token) · **Groq Whisper** `whisper-large-v3` (fallback / `STT_ENGINE=whisper`) · Web Speech API (lưới đỡ khi Whisper lỗi) |
| TTS (đọc) | **Giọng trình duyệt** `speechSynthesis` (mặc định) · **Edge TTS** qua `/api/voice/tts_stream` (fallback / `TTS_ENGINE=edge`) |
| Agent (hội thoại) | **DeepSeek** `deepseek-chat` (OpenAI-compatible) — function-calling (ReAct) |
| Geocoding | Gazetteer nội bộ (đã xác minh) → **Nominatim/OpenStreetMap** → (tuỳ chọn Gemini grounding) |
| Routing | **OSRM** (quãng đường/thời gian/đường đi thật) |
| DB | **MongoDB** (Atlas) — user, accessibility profile, rides, reports |
| Realtime tài xế | **Socket.IO** nhúng trong FastAPI (`backend/realtime.py`, `main:socket_app`) — ghép khách↔tài xế, PIN |

> Cập nhật 2026-10-11: STT/TTS/Agent/Realtime (bảng + sơ đồ) đã sửa theo code hiện tại (trước đó
> ghi FPT.AI / Groq / server :3001). Chi tiết vòng giọng nói theo file: `AGENTS.md` mục 5.

## Sơ đồ luồng
```
[Người dùng]
  │ nói (giọng)
  ▼
Frontend React ──STT──▶  Gemini Live (WS, token /api/voice/live-token) | fallback /api/voice/stt ─▶ Groq Whisper
  │  text
  ▼
/api/agent/chat ──▶ Agent (DeepSeek deepseek-chat, function-calling)
        │  tools:
        │   • resolve_destination ─▶ Gemini (tên/cơ sở) + Nominatim/Mapbox chốt toạ độ (trong bán kính phục vụ)
        │   • select_candidate    ─▶ chọn cơ sở / cổng tiếp cận
        │   • get_quote           ─▶ OSRM (km, phút, giá)
        │   • book_ride           ─▶ MongoDB (tạo chuyến)
        │   • end_conversation
        ▼
   {reply, ui}  ──TTS──▶ speechSynthesis trình duyệt | fallback /api/voice/tts_stream ─▶ Edge TTS
        │
        ▼  (sau khi đặt)
   Socket.IO (cùng server): passenger-waiting → driver-accepted → driver-arrived(+PIN)
                     → verify-pin → trip-completed
        ▼
   Bản đồ Leaflet: ghim điểm đi/đến, tô XANH điểm dễ tiếp cận, vẽ tuyến OSRM
```

## Quyết định thiết kế chính
- **LLM không bao giờ bịa toạ độ.** Agent chỉ rút tên địa điểm + dẫn dắt; toạ độ đến từ geocoder thật (Nominatim, rồi Mapbox), không có danh bạ địa điểm viết cứng. Ngoài HCMC → từ chối.
- **Nơi nhiều chi nhánh** → liệt kê ứng viên thật để khách chọn (tổng quát qua geocoder, không hardcode từng nơi).
- **Tiếp cận (accessibility)**: gợi ý cổng/điểm đón dễ tiếp cận (vd ĐH Bách Khoa cơ sở 1 — hardcode toạ độ cổng), tô xanh trên bản đồ; thu thập đánh giá accessibility của điểm đến (`/api/reports`).
- **Hands-free + an toàn**: tự chào/tự nghe, đọc lại PIN 2 lần, xác minh PIN trước khi lên xe.

## Cấu trúc thư mục (rút gọn)
```
voicego/
├─ backend/        FastAPI: main.py, agent.py, geocode.py, voice.py, db.py, seed_from_csv.py
├─ frontend/       React/Vite: src/{App.jsx, hooks/useVoiceApp.js, components/*, services/*, styles/*}
├─ SETUP.md  USER_GUIDE.md  ARCHITECTURE.md  ATTRIBUTION.md  REALTIME_INTEGRATION.md
```

## API chính
`/api/auth/login` · `/api/voice/stt` · `/api/voice/tts` · `/api/agent/chat` · `/api/voice/geocode` · `/api/rides` · `/api/reports` · `/api/db/seed` · `/api/health`

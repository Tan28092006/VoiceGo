---
title: VoiceGo
emoji: 🚕
colorFrom: green
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
short_description: Voice-first ride-hailing for visually impaired users
---

# VoiceGo

Đặt xe **hoàn toàn bằng giọng nói** cho người khiếm thị: nói điểm đến, trợ lý AI
lo phần còn lại, và hỗ trợ đặc biệt ở khâu **"10 mét cuối"** khi khách và tài xế
tìm nhau (đèn nháy + rung + xác thực PIN hai chiều).

Space này chạy nguyên khối FastAPI (API + Socket.IO realtime) và phục vụ luôn bản
React đã build — mọi thứ cùng một origin. Xem thêm `ARCHITECTURE.md`, `DEMO.md`.

## Biến môi trường (đặt trong Settings → Variables and secrets)

| Key | Bắt buộc | Ghi chú |
|---|---|---|
| `MONGODB_URI` | ✅ | Chuỗi kết nối MongoDB Atlas |
| `DEEPSEEK_API_KEY` | ✅ | LLM cho agent hội thoại + geocode |
| `GROQ_WHISPER_KEY` | ✅ | STT Whisper (DeepSeek không nhận giọng nói) |
| `FPT_API_KEY` | ⬜ | STT/TTS tiếng Việt (hết quota vẫn chạy nhờ edge-tts) |
| `TTS_PRIMARY` | ⬜ | Đặt `edge` để dùng thẳng edge-tts (miễn phí) làm giọng chính |
| `GEMINI_API_KEY` | ⬜ | Tuỳ chọn, để trống cũng được |

# VoiceGo — Attribution, Licensing & AI Disclosure

## AI-assisted development (disclosure)
Theo quy định BTC: dự án được phát triển **có hỗ trợ của công cụ AI**.
- **Công cụ:** Claude (Anthropic) qua Claude Code.
- **Phạm vi:** sinh/sửa mã nguồn, gỡ lỗi, viết tài liệu, dưới sự định hướng và kiểm thử của nhóm.
- Toàn bộ mã sinh ra **được giữ trong repo này** để giám khảo kiểm tra (theo yêu cầu “keep the resulting code/config in the repo for inspection”).
- Các dịch vụ AI bên thứ ba dùng khi chạy: **Groq** (LLM `gpt-oss-120b`, Whisper), **FPT.AI** (ASR/TTS), **Google Gemini** (geocoding grounding — tuỳ chọn).

## Third-party libraries
| Thư viện | Dùng cho | License |
|---|---|---|
| React, React-DOM | UI | MIT |
| Vite, @vitejs/plugin-react, @vitejs/plugin-basic-ssl | build/dev/HTTPS | MIT |
| Leaflet | bản đồ | BSD-2-Clause |
| socket.io / socket.io-client | realtime tài xế↔khách | MIT |
| FastAPI, Uvicorn, Pydantic, python-multipart | backend API | MIT / BSD |
| requests | HTTP client | Apache-2.0 |
| python-dotenv | đọc .env | BSD-3-Clause |
| openai (SDK) | gọi Groq (OpenAI-compatible) | Apache-2.0 |
| pymongo | MongoDB driver | Apache-2.0 |
| bcrypt | băm mật khẩu | Apache-2.0 |
| google-genai | Gemini grounding (tuỳ chọn) | Apache-2.0 |

## Dịch vụ / dữ liệu bên thứ ba
| Dịch vụ | Dùng cho | Ghi chú bản quyền |
|---|---|---|
| OpenStreetMap / **Nominatim** | geocoding (tìm toạ độ) | Dữ liệu © OpenStreetMap contributors, **ODbL**. Tile bản đồ © OSM. |
| **OSRM** (router.project-osrm.org) | tính tuyến đường | dựa trên dữ liệu OSM |
| **Groq** | LLM + Whisper STT | dịch vụ thương mại (key riêng) |
| **FPT.AI** | ASR + TTS tiếng Việt | dịch vụ thương mại (key riêng) |
| **Google Gemini** | grounding geocoding (tuỳ chọn) | dịch vụ thương mại |

## Khoá API & bí mật
Tất cả khoá nằm trong `backend/.env` (**đã gitignore — không commit**). Mẫu cấu hình ở `backend/.env.example`.

## Mã nguồn của nhóm
Toàn bộ mã nguồn dự án do **nhóm tự viết từ đầu (start from scratch)**. Phần realtime tài xế ↔ khách (Socket.IO) cũng do nhóm tự phát triển ở một nhánh khác rồi tích hợp vào đây — **không** dùng mã có sẵn của bên thứ ba (ngoài các thư viện/dịch vụ đã liệt kê ở trên).

## License
Mã nguồn dự án phát hành theo **MIT License** (trừ phần dữ liệu/dịch vụ bên thứ ba giữ license gốc nêu trên).

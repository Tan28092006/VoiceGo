"""
voice.py — Thin proxies for FPT.AI Speech-to-Text (ASR) and Text-to-Speech (TTS).

These two calls MUST run on the server because (a) the browser would be blocked
by CORS calling api.fpt.ai directly and (b) we keep the API key off the client.
Everything else (intent parsing, place matching, routing, pricing) is done in the
browser by reusing local-engine.js — so this file stays tiny.
"""
import os
import re
import json
import time
import requests

# Load secrets from backend/.env (never committed — see .gitignore).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# Keys come ONLY from the environment / .env — no secrets hardcoded here.
FPT_API_KEY = os.getenv("FPT_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Groq (OpenAI-compatible). Separate keys so Whisper STT has its own quota.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")               # LLM (agent + geocode)
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")  # smart agent brain
GROQ_GEOCODE_MODEL = os.getenv("GROQ_GEOCODE_MODEL", "llama-3.1-8b-instant")  # cheap
GROQ_WHISPER_KEY = os.getenv("GROQ_WHISPER_KEY", "")       # Whisper STT only
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")  # full > turbo cho tiếng Việt
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# TTS: "fpt" (giọng banmai, cần key + còn quota) | "edge" (Microsoft neural,
# miễn phí, không cần key). Engine nào hỏng thì tự rơi sang engine kia.
# Đặt TTS_PRIMARY=edge khi FPT hết quota — khỏi tốn ~1s/lượt gọi FPT rồi mới fallback.
TTS_PRIMARY = os.getenv("TTS_PRIMARY", "fpt").strip().lower()
EDGE_VOICE = os.getenv("EDGE_VOICE", "vi-VN-HoaiMyNeural")  # nữ, miền Bắc

ASR_URL = "https://api.fpt.ai/hmi/asr/general"
TTS_URL = "https://api.fpt.ai/hmi/tts/v5"


def groq_client():
    """OpenAI client pointed at Groq (LLM key), or None if no key/SDK."""
    if not GROQ_API_KEY:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_API_KEY)


def groq_json(prompt: str) -> str | None:
    """One-shot completion on the CHEAP model (geocode no-grounding fallback)."""
    client = groq_client()
    if not client:
        return None
    try:
        r = client.chat.completions.create(
            model=GROQ_GEOCODE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return (r.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001
        return None


def whisper_stt(audio_bytes: bytes, filename: str = "speech.wav") -> dict:
    """Transcribe Vietnamese audio via Groq Whisper-large-v3-turbo (own key)."""
    if not GROQ_WHISPER_KEY:
        return {"text": "", "error": "no_whisper_key"}
    try:
        from openai import OpenAI
        import io
        client = OpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_WHISPER_KEY)
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        r = client.audio.transcriptions.create(
            model=GROQ_WHISPER_MODEL, file=buf, language="vi", temperature=0,
            # Domain hint biases recognition toward HCMC ride vocabulary -> more
            # accurate place names + faster (skips guessing context).
            prompt=("Đặt xe ở Thành phố Hồ Chí Minh. Điểm đến: Chợ Bến Thành, Landmark 81, "
                    "Đại học Bách Khoa, Đại học Công nghệ Thông tin, Đại học Khoa học Tự nhiên, "
                    "sân bay Tân Sơn Nhất, Vạn Hạnh Mall, bệnh viện Chợ Rẫy, Quận 1, Quận 10, Thủ Đức. "
                    "Lệnh: xe máy, ô tô, đồng ý, huỷ, đổi điểm đến."),
        )
        return {"text": (r.text or "").strip()}
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error": f"whisper_failed: {e}"}


def speech_to_text(audio_bytes: bytes) -> dict:
    """Send raw audio (wav/mp3, 16kHz mono works best) to FPT ASR."""
    try:
        r = requests.post(
            ASR_URL,
            # FPT STT docs use "api_key"; TTS uses "api-key". Send both to be safe.
            headers={"api_key": FPT_API_KEY, "api-key": FPT_API_KEY},
            data=audio_bytes,
            timeout=30,
        )
        j = r.json()
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error": f"asr_failed: {e}"}

    hyps = j.get("hypotheses") or []
    text = hyps[0].get("utterance", "") if hyps else ""
    return {"text": text.strip(), "status": j.get("status"), "raw": j}


def _fpt_tts(text: str, voice: str = "banmai", speed: str = "") -> bytes | None:
    """
    Call FPT TTS, then download the generated MP3 (FPT returns an async URL that
    becomes ready after ~1s). Returns mp3 bytes or None on failure.
    """
    if not FPT_API_KEY:
        return None
    try:
        r = requests.post(
            TTS_URL,
            headers={"api-key": FPT_API_KEY, "voice": voice, "speed": str(speed)},
            data=text.encode("utf-8"),
            timeout=15,
        )
        j = r.json()
    except Exception:  # noqa: BLE001
        return None

    async_url = j.get("async")
    if not async_url:
        return None

    # Poll the async URL until the audio is ready. Poll immediately (no lead
    # sleep) then every 0.4s — finer polling catches the file ~1s sooner per
    # reply. Budget ~7s total (18 × 0.4s) ≈ old 8.4s.
    for i in range(18):
        try:
            a = requests.get(async_url, timeout=15)
            ctype = a.headers.get("Content-Type", "")
            if a.status_code == 200 and ("audio" in ctype or a.content[:3] == b"ID3" or a.content[:2] == b"\xff\xfb"):
                return a.content
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return None


def _edge_tts(text: str, speed: str = "") -> bytes | None:
    """
    Microsoft Edge neural TTS — miễn phí, KHÔNG cần API key, giọng vi-VN tự nhiên.
    Lưới an toàn khi FPT hết quota: nếu thiếu tầng này, frontend rơi thẳng xuống
    speechSynthesis của trình duyệt — mà máy tính Windows thường không cài giọng
    tiếng Việt nên sẽ đọc tiếng Việt bằng giọng Anh, nghe không hiểu được.
    """
    try:
        import asyncio
        import edge_tts
    except ImportError:
        return None

    s = str(speed).strip()
    rate = f"{int(s):+d}%" if s.lstrip("+-").isdigit() else "+0%"

    async def _collect() -> bytes:
        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, EDGE_VOICE, rate=rate).stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    try:
        # Endpoint này là sync def -> FastAPI chạy nó trong threadpool, không có
        # event loop sẵn, nên asyncio.run() an toàn.
        return asyncio.run(_collect()) or None
    except Exception:  # noqa: BLE001
        return None


def text_to_speech(text: str, voice: str = "banmai", speed: str = "") -> bytes | None:
    """Đọc tiếng Việt: thử engine chính trước, hỏng thì rơi sang engine còn lại."""
    order = ("edge", "fpt") if TTS_PRIMARY == "edge" else ("fpt", "edge")
    for engine in order:
        audio = _edge_tts(text, speed) if engine == "edge" else _fpt_tts(text, voice, speed)
        if audio:
            return audio
    return None


def stream_agent_narration(booking: dict):
    """
    Generator yielding a short Vietnamese 'AI agent đang đặt xe' narration
    token-by-token via Gemini streaming. Falls back to scripted text if Gemini
    is unavailable, so the agent overlay always shows something.
    """
    place = booking.get("place", "điểm đến")
    address = booking.get("address") or ""
    vehicle = "ô tô" if booking.get("vehicle") == "car" else "xe máy"
    km = booking.get("km", 0) or 0
    price = booking.get("price", 0) or 0

    if not GEMINI_API_KEY:
        for s in [f"Đã xác nhận: đi {place} bằng {vehicle}. ",
                  "Đang tìm tài xế phù hợp gần bạn… ",
                  "Đã khớp tài xế, đang gửi thông tin chuyến đi."]:
            yield s
        return

    try:
        from google import genai
    except ImportError:
        yield f"Đang đặt {vehicle} đi {place}…"
        return

    prompt = (
        "Bạn là trợ lý AI đang THỰC THI việc đặt xe cho người khiếm thị. "
        "Tường thuật NGẮN GỌN, ấm áp các bước đang làm, bằng tiếng Việt, như một agent "
        "đang hành động (2-3 câu, mỗi câu một hành động). "
        f"Thông tin: điểm đến={place} ({address}); loại xe={vehicle}; "
        f"quãng đường≈{km:.1f} km; giá≈{int(price)} đồng. "
        "Phong cách: 'Đang khóa điểm đến...', 'Đang tìm tài xế gần bạn...', "
        "'Đã tìm thấy tài xế, đang xác nhận chuyến đi...'. Không bịa số liệu khác."
    )
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        for chunk in client.models.generate_content_stream(model=GEMINI_MODEL, contents=prompt):
            if chunk.text:
                yield chunk.text
    except Exception:  # noqa: BLE001
        yield f"Đang hoàn tất đặt {vehicle} đi {place}…"


def extract_intent(text: str, known_places: list[dict]) -> dict | None:
    """
    Use Gemini to parse a (possibly messy / misheard) Vietnamese booking command
    into a structured intent, choosing the destination from the known place list.

    known_places: [{"id": "n1", "name": "Bến Thành"}, ...]
    Returns {"intent","vehicle","nodeId","destinationName","source"} or None if
    Gemini is unavailable (caller then falls back to the on-device JS matcher).
    """
    if not GEMINI_API_KEY or not text.strip():
        return None
    try:
        from google import genai
    except ImportError:
        return None

    names = [p["name"] for p in known_places]
    prompt = (
        "Bạn là bộ phân tích lệnh đặt xe cho người khiếm thị. "
        "Văn bản dưới đây từ nhận diện giọng nói nên có thể sai chính tả.\n"
        f'Lệnh: "{text}"\n'
        f"Danh sách điểm đến hợp lệ: {names}\n"
        "Hãy chọn điểm đến GẦN ĐÚNG NHẤT trong danh sách (đúng nguyên văn), và loại xe. "
        "bike = xe ôm/xe máy/2 bánh; car = ô tô/taxi/4 bánh (mặc định bike nếu không rõ). "
        "Nếu không suy ra được điểm đến, để destination rỗng.\n"
        'Chỉ trả về JSON: {"intent":"BOOK_RIDE","destination":"<tên trong danh sách hoặc rỗng>","vehicle_type":"bike|car"}'
    )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = (resp.text or "").strip()
    except Exception:  # noqa: BLE001
        return None

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    dest_name = (data.get("destination") or "").strip()
    vehicle = data.get("vehicle_type", "bike")
    vehicle = "car" if vehicle == "car" else "bike"

    node_id = None
    for p in known_places:
        if p["name"].strip().lower() == dest_name.lower():
            node_id = p["id"]
            dest_name = p["name"]
            break

    return {
        "intent": data.get("intent", "BOOK_RIDE"),
        "vehicle": vehicle,
        "nodeId": node_id,
        "destinationName": dest_name if node_id else "",
        "source": "gemini",
    }

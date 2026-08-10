"""
voice.py — Speech-to-Text (Groq Whisper) and Text-to-Speech (Microsoft Edge TTS).

Everything else (intent parsing, place matching, routing, pricing) is done in the
browser by reusing local-engine.js — so this file stays tiny.
"""
import os
import re
import json

# Load secrets from backend/.env (never committed — see .gitignore).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# Keys come ONLY from the environment / .env — no secrets hardcoded here.
def _collect_gemini_keys() -> list[str]:
    """Gom nhiều key Gemini để CỘNG DỒN hạn mức free — mỗi key thuộc một project
    riêng nên có hạn mức riêng; N key ≈ N lần quota, đủ cho demo QR nhiều người quét.
    Nhận cả 3 kiểu khai báo (tiện dán vào Render): GEMINI_API_KEY,
    GEMINI_API_KEYS="k1,k2,k3", và GEMINI_API_KEY_2 ... GEMINI_API_KEY_9.
    """
    raw = [os.getenv("GEMINI_API_KEY", "")]
    raw += (os.getenv("GEMINI_API_KEYS", "") or "").split(",")
    raw += [os.getenv(f"GEMINI_API_KEY_{i}", "") for i in range(2, 10)]
    keys, seen = [], set()
    for k in raw:
        k = (k or "").strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


GEMINI_API_KEYS = _collect_gemini_keys()
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""   # tương thích code cũ
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── LLM hội thoại + geocode (OpenAI-compatible) ──────────────────────────────
# Mặc định DeepSeek. Muốn đổi nhà cung cấp: set LLM_BASE_URL + LLM_MODEL + key.
# Để quay lại Groq: LLM_API_KEY=<groq key>, LLM_BASE_URL=https://api.groq.com/openai/v1,
# LLM_MODEL=openai/gpt-oss-120b.
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")          # bộ não agent
LLM_GEOCODE_MODEL = os.getenv("LLM_GEOCODE_MODEL", "deepseek-chat")  # geocode fallback

# ── Whisper STT — GIỮ trên Groq (DeepSeek không nhận dạng giọng nói) ──────────
GROQ_WHISPER_KEY = os.getenv("GROQ_WHISPER_KEY", "")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")  # full > turbo cho tiếng Việt
GROQ_BASE_URL = "https://api.groq.com/openai/v1"            # chỉ dùng cho Whisper STT

EDGE_VOICE = os.getenv("EDGE_VOICE", "vi-VN-HoaiMyNeural")  # nữ, miền Bắc


# Client được TÁI SỬ DỤNG, không tạo mới mỗi lượt: mỗi lần new OpenAI() là một
# connection pool mới -> bắt tay TLS lại từ đầu với DeepSeek/Groq, tốn vài trăm ms
# cho MỌI lượt nói, không riêng lượt đầu.
_LLM_CLIENT = None
_WHISPER_CLIENT = None


def llm_client():
    """OpenAI-compatible client cho LLM hội thoại (DeepSeek mặc định), None nếu thiếu key/SDK."""
    global _LLM_CLIENT
    if _LLM_CLIENT is not None:
        return _LLM_CLIENT
    if not LLM_API_KEY:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    _LLM_CLIENT = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    return _LLM_CLIENT


def whisper_client():
    """Client Groq riêng cho Whisper, cũng dùng lại để giữ kết nối.

    timeout=10s: OpenAI SDK default là 600s (10 phút) — nếu Groq treo (không phải
    lỗi rõ như 429/401 mà chỉ không phản hồi), người dùng phải đợi tới 10 phút mới
    rơi được xuống fallback (Web Speech API), vô hiệu hoá hẳn mục đích của lưới đỡ.
    10s là đủ cho một lượt STT bình thường (~1-3s) mà vẫn fail nhanh khi Groq treo.
    max_retries=0: SDK mặc định tự thử lại 2 lần khi timeout — mỗi lần đợi lại đủ
    10s nên tổng thời gian thực đo được là ~33s, không phải 10s. STT là tương tác
    trực tiếp với người dùng (không phải job nền), fail nhanh 1 lần rồi rơi xuống
    fallback tốt hơn thử lại âm thầm 3 lần.
    """
    global _WHISPER_CLIENT
    if _WHISPER_CLIENT is not None:
        return _WHISPER_CLIENT
    if not GROQ_WHISPER_KEY:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    _WHISPER_CLIENT = OpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_WHISPER_KEY,
                              timeout=10.0, max_retries=0)
    return _WHISPER_CLIENT


def warmup():
    """Nạp sẵn SDK + dựng sẵn client ngay lúc server khởi động.

    Các import này (openai, google-genai) nặng cả giây và trước đây nằm trong hàm,
    nên NGƯỜI DÙNG ĐẦU TIÊN phải trả toàn bộ chi phí đó — đúng hiện tượng câu đầu
    lâu hơn hẳn mấy câu sau. Chạy trước thì lượt đầu nhanh ngang lượt sau.
    """
    try:
        llm_client()
        whisper_client()
    except Exception:  # noqa: BLE001
        pass
    try:
        from google import genai  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    # Edge TTS: import thôi CHƯA đủ. Lần tổng hợp đầu tiên tốn 2762ms vì phải lấy
    # token rồi mới phát; các lần sau chỉ 370-500ms. Đọc thử một tiếng ở đây để
    # trả cái giá đó lúc khởi động, thay vì bắt câu trả lời đầu tiên gánh.
    try:
        import asyncio
        import edge_tts

        async def _prime():
            async for chunk in edge_tts.Communicate("xin chào", EDGE_VOICE).stream():
                if chunk["type"] == "audio":
                    break          # có chunk đầu là đủ, token đã nằm trong cache
        asyncio.run(_prime())
    except Exception:  # noqa: BLE001
        pass


def llm_json(prompt: str) -> str | None:
    """One-shot completion cho geocode no-grounding fallback."""
    client = llm_client()
    if not client:
        return None
    try:
        r = client.chat.completions.create(
            model=LLM_GEOCODE_MODEL,
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
        import io
        client = whisper_client()
        if not client:
            return {"text": "", "error": "no_whisper_client"}
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


def _edge_tts(text: str, speed: str = "") -> bytes | None:
    """
    Microsoft Edge neural TTS — miễn phí, KHÔNG cần API key, giọng vi-VN tự nhiên.
    Nếu hàm này hỏng, frontend rơi thẳng xuống speechSynthesis của trình duyệt — mà
    máy tính Windows thường không cài giọng tiếng Việt nên sẽ đọc tiếng Việt bằng
    giọng Anh, nghe không hiểu được.
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
    """Đọc tiếng Việt qua Edge TTS. `voice` giữ lại trong signature cho tương thích
    endpoint cũ, không dùng (Edge chỉ theo EDGE_VOICE)."""
    return _edge_tts(text, speed)


async def edge_tts_stream(segment: str, rate: str):
    """Yield từng chunk mp3 của MỘT mẩu văn bản qua Edge TTS."""
    import edge_tts
    async for chunk in edge_tts.Communicate(segment, EDGE_VOICE, rate=rate).stream():
        if chunk["type"] == "audio":
            yield chunk["data"]


async def stream_text_to_speech(text: str, voice: str = "banmai", speed: str = ""):
    """
    Streaming âm thanh trực tiếp qua Edge TTS (nhanh hơn tải nguyên file rồi mới phát).
    `voice` giữ lại trong signature cho tương thích endpoint cũ, không dùng.

    MỘT lần gọi cho cả đoạn. Đã thử cắt theo câu để ra tiếng sớm hơn nhưng đo lại
    thì tệ hơn: byte đầu chỉ nhanh ~80ms trong khi TỔNG thời gian gấp 3 lần
    (1 lần gọi 885-1123ms so với cắt câu 2688-3190ms), vì mỗi mẩu phải mở một
    WebSocket riêng tới Edge. Độ trễ ở đây do BẮT TAY KẾT NỐI, không do độ dài chữ:
    kết nối ấm thì đoạn 304 ký tự vẫn ra tiếng sau ~500ms.

    Nếu Edge lỗi/đứt giữa đường, response sẽ ngắn hoặc rỗng: HTTP vẫn 200 nên trình
    duyệt chỉ thấy "audio hỏng" — client tự đọc bù bằng speechSynthesis (xem tts.js).
    """
    s = str(speed).strip()
    rate = f"{int(s):+d}%" if s.lstrip("+-").isdigit() else "+0%"
    try:
        async for chunk in edge_tts_stream(text, rate):
            yield chunk
    except Exception:  # noqa: BLE001
        pass


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

"""
main.py — FastAPI backend for VoiceGo (đặt xe bằng giọng nói cho người khiếm thị).

Only does what truly needs a server: proxy FPT.AI Speech-to-Text / Text-to-Speech
and Gemini intent parsing (CORS + keep API keys off the client). Routing and
pricing run in the browser.
"""
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse, StreamingResponse
from pydantic import BaseModel

from data import NODES
from voice import speech_to_text, text_to_speech, extract_intent, stream_agent_narration
from geocode import resolve_destination

app = FastAPI(title="VoiceGo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TtsRequest(BaseModel):
    text: str
    voice: str = "banmai"
    speed: str = ""


class NluRequest(BaseModel):
    text: str


class GeocodeRequest(BaseModel):
    text: str
    lat: float | None = None
    lng: float | None = None


class AgentRequest(BaseModel):
    place: str
    address: str = ""
    vehicle: str = "bike"
    km: float = 0
    price: int = 0


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "voicego", "places": len(NODES)}


@app.post("/api/voice/stt")
async def voice_stt(file: UploadFile = File(...)):
    """Transcribe an uploaded audio clip (wav/mp3) via FPT ASR."""
    audio = await file.read()
    return speech_to_text(audio)


@app.post("/api/voice/tts")
def voice_tts(req: TtsRequest):
    """Synthesize Vietnamese speech via FPT TTS, return mp3 bytes."""
    audio = text_to_speech(req.text, req.voice, req.speed)
    if audio is None:
        return JSONResponse({"error": "tts_failed"}, status_code=502)
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/voice/nlu")
def voice_nlu(req: NluRequest):
    """Parse a booking command with Gemini. Returns {ok:false} if unavailable so
    the frontend can fall back to its on-device matcher."""
    known = [{"id": n["id"], "name": n["name"]} for n in NODES]
    result = extract_intent(req.text, known)
    if not result:
        return {"ok": False}
    return {"ok": True, **result}


@app.post("/api/voice/geocode")
def voice_geocode(req: GeocodeRequest):
    """Resolve an arbitrary spoken place name to a real address + coordinates
    (Gemini grounded search -> Nominatim -> cross-validate)."""
    return resolve_destination(req.text, req.lat, req.lng)


@app.post("/api/agent/stream")
def agent_stream(req: AgentRequest):
    """Stream the AI agent's booking narration token-by-token (Gemini streaming)."""
    return StreamingResponse(
        stream_agent_narration(req.model_dump()),
        media_type="text/plain; charset=utf-8",
    )

"""
main.py — FastAPI backend for VoiceGo (đặt xe bằng giọng nói cho người khiếm thị).

Server-side only what needs to be: FPT.AI STT/TTS proxies (CORS + keep keys off
the client) and the conversational agent loop (Groq function-calling + tools).
"""
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from data import NODES
from voice import speech_to_text, text_to_speech, whisper_stt
from geocode import resolve_destination
from agent import run_agent
from db import (
    DEMO_PASSENGER_ID,
    MongoUnavailable,
    acknowledge_driver_alert,
    create_accessibility_report,
    create_ride_request,
    find_nearby_accessible_places,
    get_user,
    mongo_status,
    seed_demo_data,
    update_accessibility_profile,
)

app = FastAPI(title="VoiceGo API", version="2.0.0")

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


class GeocodeRequest(BaseModel):
    text: str
    lat: float | None = None
    lng: float | None = None


class ChatRequest(BaseModel):
    messages: list[dict]


class AccessibilityProfileRequest(BaseModel):
    disability_type: str = "visual_impairment"
    needs_driver_assistance: bool = True


class RideRequestPayload(BaseModel):
    passenger_id: str = DEMO_PASSENGER_ID
    pickup: dict
    destination: dict
    booking_method: str = "manual"
    vehicle: str = "bike"
    estimated_price: float | None = None
    estimated_distance_km: float | None = None
    estimated_arrival_minutes: int | None = None
    accessibility_score: int | None = None


class AccessibilityReportRequest(BaseModel):
    reporter_id: str = DEMO_PASSENGER_ID
    name: str
    address: str = ""
    lat: float
    lng: float
    disability_accessible_entrance: bool = False
    accessibility_score: int = 3
    reward_points: int = 10


def db_response(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except MongoUnavailable as exc:
        return JSONResponse(
            {"ok": False, "error": "database_unavailable", "reason": str(exc)},
            status_code=503,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"ok": False, "error": "database_error", "reason": str(exc)},
            status_code=500,
        )


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "voicego", "places": len(NODES), "mongo": mongo_status()}


@app.get("/api/db/status")
def db_status():
    """Check whether MongoDB is reachable and show collection counts."""
    return mongo_status()


@app.post("/api/db/seed")
def db_seed():
    """Seed demo passenger, driver, and accessibility places for hackathon demos."""
    return db_response(seed_demo_data)


@app.get("/api/me")
def me(user_id: str = DEMO_PASSENGER_ID):
    return db_response(get_user, user_id)


@app.get("/api/me/accessibility-profile")
def get_accessibility_profile(user_id: str = DEMO_PASSENGER_ID):
    user = db_response(get_user, user_id)
    if isinstance(user, JSONResponse):
        return user
    return {
        "user_id": user_id,
        "accessibility_profile": (user or {}).get("accessibility_profile"),
        "total_reward_points": (user or {}).get("total_reward_points", 0),
    }


@app.put("/api/me/accessibility-profile")
def put_accessibility_profile(req: AccessibilityProfileRequest, user_id: str = DEMO_PASSENGER_ID):
    return db_response(update_accessibility_profile, user_id, req.model_dump())


@app.get("/api/places/accessibility")
def nearby_accessibility_places(
    lat: float = Query(...),
    lng: float = Query(...),
    limit: int = 8,
    max_meters: int = 2500,
):
    return db_response(find_nearby_accessible_places, lat, lng, limit, max_meters)


@app.post("/api/rides")
def create_ride(req: RideRequestPayload):
    return db_response(create_ride_request, **req.model_dump())


@app.patch("/api/rides/{ride_id}/driver-alert/ack")
def ack_driver_alert(ride_id: str):
    return db_response(acknowledge_driver_alert, ride_id)


@app.post("/api/reports")
def create_report(req: AccessibilityReportRequest):
    payload = req.model_dump()
    reporter_id = payload.pop("reporter_id")
    return db_response(create_accessibility_report, reporter_id, payload)


@app.post("/api/voice/stt")
async def voice_stt(file: UploadFile = File(...)):
    """Transcribe Vietnamese audio via Groq Whisper (accurate); FPT ASR fallback."""
    audio = await file.read()
    result = whisper_stt(audio, file.filename or "speech.wav")
    if not result.get("text"):
        result = speech_to_text(audio)  # fallback if Whisper unavailable
    return result


@app.post("/api/voice/tts")
def voice_tts(req: TtsRequest):
    """Synthesize Vietnamese speech via FPT TTS, return mp3 bytes."""
    audio = text_to_speech(req.text, req.voice, req.speed)
    if audio is None:
        return JSONResponse({"error": "tts_failed"}, status_code=502)
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/agent/chat")
def agent_chat(req: ChatRequest):
    """One turn of the conversational booking agent (Groq + tools)."""
    return run_agent(req.messages)


@app.post("/api/voice/geocode")
def voice_geocode(req: GeocodeRequest):
    """Debug: resolve a place name to a real address + coordinates."""
    return resolve_destination(req.text, req.lat, req.lng)

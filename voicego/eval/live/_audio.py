"""Tiện ích âm thanh dùng chung cho eval: tổng hợp giọng edge-tts (có cache), mốc thời
gian từng từ (WordBoundary), trộn tiếng vọng + giọng người dùng, mô phỏng cửa sổ
spokenWordsBetween của tts.js.

Cache nằm NGOÀI repo (thư mục temp, hoặc biến VOICEGO_EVAL_CACHE) để không commit mp3/pcm.
"""
import array
import hashlib
import json
import math
import os
import random
import re
import subprocess
import tempfile
import unicodedata

import edge_tts

CACHE = os.environ.get("VOICEGO_EVAL_CACHE") or os.path.join(tempfile.gettempdir(), "voicego_eval_cache")
AI_VOICE = "vi-VN-HoaiMyNeural"     # giọng AI của app (EDGE_VOICE mặc định)
USER_VOICE = "vi-VN-NamMinhNeural"  # "người dùng" tổng hợp
# Loa điện thoại -> mic: cắt dải (loa nhỏ) + vài phản xạ phòng. Không phải mô hình
# chính xác của một máy cụ thể, chỉ để tiếng vọng bớt "sạch" như giọng gốc.
PHONE_ECHO_AF = "highpass=f=300,lowpass=f=3400,aecho=0.8:0.6:25|60:0.25|0.15"


def _h(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


async def synth(text, voice, rate=16000, af=None):
    """Trả (pcm Int16 array, words=[[word, start_s, dur_s], ...]). Có cache theo (voice, text)."""
    os.makedirs(CACHE, exist_ok=True)
    h = _h(f"{voice}|{text}")
    mp3 = os.path.join(CACHE, f"{h}.mp3")
    meta = os.path.join(CACHE, f"{h}.json")
    if not (os.path.exists(mp3) and os.path.exists(meta)):
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
        words = []
        with open(mp3, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append([ch["text"], ch["offset"] / 1e7, ch["duration"] / 1e7])
        with open(meta, "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False)
    with open(meta, encoding="utf-8") as f:
        words = json.load(f)
    pcm = os.path.join(CACHE, f"{h}_{rate}_{_h(af or '')[:6]}.pcm")
    if not os.path.exists(pcm):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", str(rate)]
        if af:
            cmd += ["-af", af]
        cmd += ["-f", "s16le", pcm]
        subprocess.run(cmd, check=True)
    a = array.array("h")
    with open(pcm, "rb") as f:
        a.frombytes(f.read())
    return a, words


def _norm(w):
    w = unicodedata.normalize("NFC", w.lower())
    return re.sub(r"[^\w]", "", w)


def token_times(text, words, total_s):
    """Gán mốc thời gian (giây) cho từng token tách theo khoảng trắng của `text`
    (đúng cách tts.js tách: /\\S+/), từ các WordBoundary của edge-tts.
    Trả 2 danh sách: exact (theo WordBoundary) và interp (nội suy theo ký tự như
    tts.js làm với giọng Edge: t = start + charIndex/len * dur)."""
    toks = [(m.start(), m.group(0)) for m in re.finditer(r"\S+", text)]
    exact = []
    wi = 0
    for _, tok in toks:
        k = _norm(tok)
        t = None
        for j in range(wi, min(wi + 4, len(words))):
            if _norm(words[j][0]) == k:
                t = words[j][1]
                wi = j + 1
                break
        exact.append(t)
    # Token không khớp được (hiếm) -> lấy theo token liền trước.
    last = 0.0
    for i, t in enumerate(exact):
        if t is None:
            exact[i] = last
        last = exact[i]
    n = max(1, len(text))
    interp = [ci / n * total_s for ci, _ in toks]
    return [t for _, t in toks], exact, interp


def window(tokens, times, t0, t1, stop_at=math.inf):
    """Mô phỏng spokenWordsBetween(t0, t1): các từ đã phát (mốc <= stop_at) trong [t0, t1]."""
    out = []
    for tok, t in zip(tokens, times):
        if t > stop_at or t > t1:
            break
        if t >= t0:
            out.append(tok)
    return out


def mix(total_n, tracks, noise_rms=0.002, seed=0):
    """tracks = [(pcm, start_sample, gain, cut_at_sample|None)]. Trả bytes s16le.
    Thêm ồn nền Gauss nhẹ (mic thật không bao giờ im tuyệt đối)."""
    rnd = random.Random(seed)
    out = [rnd.gauss(0.0, noise_rms * 32768) for _ in range(total_n)]
    for pcm, start, gain, cut in tracks:
        end = len(pcm) if cut is None else max(0, min(len(pcm), cut - start))
        fade = 320  # 20ms tắt dần khi TTS bị pause giữa chừng
        for i in range(end):
            j = start + i
            if 0 <= j < total_n:
                g = gain
                if cut is not None and end - i < fade:
                    g *= (end - i) / fade
                out[j] += pcm[i] * g
    return array.array("h", (max(-32768, min(32767, int(v))) for v in out)).tobytes()


def frame_rms(pcm, frame=4096):
    """RMS từng khung (cỡ khung ScriptProcessor của voiceRecorder: 4096 mẫu @48kHz)."""
    out = []
    for i in range(0, len(pcm) - frame + 1, frame):
        s = 0.0
        for v in pcm[i:i + frame]:
            s += (v / 32768.0) ** 2
        out.append(math.sqrt(s / frame))
    return out


def active_rms(pcm, frame=1600):
    """RMS trung bình của các khung ĐANG NÓI (khung >= 10% khung to nhất), thang 0..1."""
    rs = [r for r in frame_rms(pcm, frame)]
    if not rs:
        return 0.0
    top = max(rs)
    act = [r for r in rs if r >= 0.1 * top]
    return math.sqrt(sum(r * r for r in act) / len(act))

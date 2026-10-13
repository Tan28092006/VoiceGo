"""LIVE eval (opt-in, gọi Gemini THẬT, tốn quota free tier): tiếng AI vọng vào mic +
giọng người dùng -> gemini-3.5-transcribe-live chép ra gì, và bản chốt về sau bao lâu.

Mỗi clip mô phỏng đúng một lượt của app (useVoiceApp + voiceRecorder + liveStt):
  - AI (vi-VN-HoaiMyNeural) đọc một câu; tiếng vọng = giọng AI qua "loa điện thoại"
    (lọc dải + phản xạ), chuẩn hoá để gain=1.0 là TO BẰNG giọng người dùng; gain 0.3
    (~-10dB, AEC còn rò), 0.5 (-6dB), 0.7 (-3dB, loa ngoài không AEC).
  - VAD xác nhận tiếng nói tại t_vad (5 khung ~427ms sau khi người dùng mở miệng nếu AI
    đang đọc, 8 khung ~683ms nếu không). Đoạn tiền ghi (speechFrames+4)*4096/48k = 1.024s
    TRƯỚC t_vad được xả MỘT LẦN lên Gemini, phần sau gửi theo thời gian thực 100ms/khung.
  - Chen ngang mềm: AI TẠM DỪNG ngay tại t_vad (paused=True) -> tiếng vọng tắt.
    paused=False = trường hợp xấu nhất, AI đọc tới hết câu (như mix_probe.py).
  - Sau khi hết tiếng nói, gửi thêm ~0.8-0.95s đuôi im lặng (silenceMs) rồi audioStreamEnd.
  - Cửa sổ tiếng vọng = spokenWordsBetween(t0 - 800ms, cuối clip + 300ms), t0 = đầu tiền ghi,
    dừng ở chỗ pause. Ghi cả bản theo mốc từ thật (WordBoundary) lẫn bản nội suy theo ký tự
    (cách tts.js tính cho giọng Edge).
Kết quả THÔ (finals/interims/mốc thời gian + hash file nguồn) ghi ra một file MỚI
live/runs/<run_id>.json mỗi lần chạy, không bao giờ ghi đè. Eval offline (echo.test.js)
đọc mọi file trong runs/ và tự tính chỉ số -> đổi cancelEcho()/isBargeIn() thì chấm lại
trên cùng transcript THẬT mà không gọi API lại (backfill).

Chạy (từ thư mục gốc repo):
  py -3.13 voicego/eval/live/live_echo_eval.py              # bộ A (dev): 18 clip + lặp 4 clip x2 = 26 session
  py -3.13 voicego/eval/live/live_echo_eval.py --set H --repeat 1   # bộ H (holdout): 18 session
  py -3.13 voicego/eval/live/live_echo_eval.py --set T --repeat 1   # bộ T (đuôi 550 vs 800ms): 12 session
  py -3.13 voicego/eval/live/live_echo_eval.py --dry-run    # chỉ tổng hợp + in kế hoạch, không gọi Gemini
  py -3.13 voicego/eval/live/live_echo_eval.py --repeat 1   # không lặp (18 session)
Key đọc từ voicego/backend/.env (GEMINI_API_KEY), KHÔNG bao giờ in ra.
"""
import argparse
import asyncio
import base64
import datetime
import json
import os
import subprocess
import sys
import time
import zlib

import websockets
from dotenv import dotenv_values

import _audio as A

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
MODEL = "gemini-3.5-transcribe-live"
# Giống backend/voice.py LIVE_VOCAB (app gửi kèm trong setup).
VOCAB = ["Chợ Bến Thành", "Landmark 81", "Đại học Bách Khoa", "Đại học Công nghệ Thông tin",
         "Đại học Khoa học Tự nhiên", "Đại học Quốc tế", "sân bay Tân Sơn Nhất", "Vạn Hạnh Mall",
         "bệnh viện Chợ Rẫy", "Thủ Đức", "Quận 1", "Quận 10", "xe máy", "ô tô", "đồng ý", "huỷ",
         "đổi điểm đến"]

FRAME_S = 4096 / 48000                 # 85.33ms
PREROLL_S = 12 * FRAME_S               # (speechFrames 8 + 4) khung = 1.024s
VAD_TTS_S = 5 * FRAME_S                # speechFramesTts = 5 lúc AI đang đọc
VAD_S = 8 * FRAME_S                    # speechFrames = 8 lúc AI im
SR = 16000
CHUNK = 3200                           # 100ms s16le

# (id, câu AI, lời chen ngang, lời đáp sau khi AI dứt câu)
SENTENCES = [
    ("A1", "Giá khoảng ba mươi nghìn đồng, tài xế sẽ tới trong năm phút. Bạn muốn đi xe máy hay ô tô?",
     "Thôi đổi sang ô tô đi", "Đi xe máy"),
    ("A2", "Mình đã tìm thấy chợ Bến Thành ở quận 1, cách bạn khoảng hai cây số. Bạn có muốn đặt xe tới đó không?",
     "Không, mình muốn đi Landmark 81", "Có, đặt xe tới đó đi"),
    ("A3", "Tài xế Minh đang tới đón bạn bằng xe Honda màu đỏ, còn khoảng ba phút nữa. Bạn nhớ đứng ở cổng chính nhé.",
     "Dừng lại", "Được rồi, cảm ơn nhé"),
]
# Bộ HOLDOUT (split="holdout"): câu mới, KHÔNG dùng khi thiết kế/chỉnh luật đề xuất.
# Luật đề xuất trong echo.test.js được chốt TRƯỚC khi chạy bộ này (xem RESULTS.md).
SENTENCES_HOLDOUT = [
    ("H1", "Mình đặt xe máy tới bệnh viện Chợ Rẫy cho bạn nhé, giá khoảng hai mươi tám nghìn đồng.",
     "Khoan, cho mình đổi sang ô tô", "Được, đặt luôn đi"),
    ("H2", "Hiện có ba tài xế gần bạn, xe đầu tiên cách khoảng bốn trăm mét. Bạn chọn xe nào?",
     "Huỷ chuyến này đi", "Xe đầu tiên"),
    ("H3", "Bạn đã tới sân bay Tân Sơn Nhất, cảm ơn bạn đã đi xe. Bạn có muốn đánh giá tài xế không?",
     "Không cần đâu", "Có, năm sao nhé"),
]
# Bộ T (split="latency"): giọng người dùng SẠCH (không vọng), so cặp đuôi im lặng 550 vs 800ms
# trước audioStreamEnd -> audioStreamEnd sớm có làm bản chốt về sớm hơn không (endpointing).
SENTENCES_TAIL = [
    ("T1", "Dạ.", "Cho mình đặt xe máy đi chợ Bến Thành nhé", ""),
    ("T2", "Dạ.", "Không, mình muốn đi Landmark 81", ""),
    ("T3", "Dạ.", "Đi xe máy", ""),
    ("T4", "Dạ.", "Huỷ chuyến này đi", ""),
    ("T5", "Dạ.", "Có, đặt xe tới đó đi", ""),
    ("T6", "Dạ.", "Mình muốn đi tới bệnh viện Chợ Rẫy, à không, sân bay Tân Sơn Nhất", ""),
]
CONDITIONS_TAIL = [
    ("tail055", "user_only", 0.0, 1.0, {"tail": 0.55}),
    ("tail080", "user_only", 0.0, 1.0, {"tail": 0.80}),
]
SETS = {"A": ("dev", SENTENCES), "H": ("holdout", SENTENCES_HOLDOUT), "T": ("latency", SENTENCES_TAIL)}
# (id, nhãn, gain tiếng vọng, gain người dùng, tham số)
CONDITIONS = [
    ("echo_p_g03", "echo_only", 0.3, 0.0, {"vad_frac": 0.4, "paused": True}),
    ("echo_p_g07", "echo_only", 0.7, 0.0, {"vad_frac": 0.6, "paused": True}),
    ("echo_full_g05", "echo_only", 0.5, 0.0, {"vad_frac": 0.3, "paused": False}),
    ("barge_p_g03", "user_barge", 0.3, 1.0, {"onset_frac": 0.45, "paused": True}),
    ("barge_p_g07_uq", "user_barge", 0.7, 0.6, {"onset_frac": 0.35, "paused": True}),
    ("after_g035", "user_after_ai", 0.35, 1.0, {"gap_s": 0.35}),
]
REPEAT_SUBSET = ["echo_p_g07_A1", "echo_p_g03_A2", "barge_p_g03_A2", "after_g035_A1"]


async def build_clips(sentences=SENTENCES, conditions=None):
    conditions = conditions or CONDITIONS
    clips = []
    for sid, ai_text, barge_text, after_text in sentences:
        ai_echo, words = await A.synth(ai_text, A.AI_VOICE, SR, af=A.PHONE_ECHO_AF)
        ai_dur = len(ai_echo) / SR
        # Chuẩn hoá: gain=1.0 nghĩa là tiếng vọng TO BẰNG giọng người dùng (RMS lúc đang nói).
        ref = A.active_rms((await A.synth(barge_text, A.USER_VOICE, SR))[0])
        norm = ref / max(1e-6, A.active_rms(ai_echo))
        toks, t_exact, t_interp = A.token_times(ai_text, words, ai_dur)
        for cid, label, gain, ugain, p in conditions:
            user_text = barge_text if label in ("user_barge", "user_only") else (after_text if label == "user_after_ai" else "")
            user_pcm = None
            onset = None
            if user_text:
                user_pcm, _ = await A.synth(user_text, A.USER_VOICE, SR)
            if label == "echo_only":
                t_vad = p["vad_frac"] * ai_dur
                speech_end = t_vad if p["paused"] else ai_dur
                tail = 0.95
            elif label == "user_only":
                onset = 0.3
                t_vad = onset + VAD_S
                speech_end = onset + len(user_pcm) / SR
                tail = p["tail"]
            elif label == "user_barge":
                onset = p["onset_frac"] * ai_dur
                t_vad = onset + VAD_TTS_S
                speech_end = max(onset + len(user_pcm) / SR, t_vad if p["paused"] else ai_dur)
                tail = 0.8
            else:
                # Mic vẫn mở suốt lúc AI đọc (Gemini Live, mở sau 1s). Người dùng đáp ~gap_s sau
                # TỪ CUỐI (không phải cuối file: mp3 Edge còn ~0.9s im lặng, isSpeaking() vẫn true).
                onset = (words[-1][1] + words[-1][2]) + p["gap_s"]
                tts_on = onset + VAD_TTS_S < ai_dur
                t_vad = onset + (VAD_TTS_S if tts_on else VAD_S)
                speech_end = onset + len(user_pcm) / SR
                tail = 0.8
            paused = p.get("paused", False)
            clip_start = max(0.0, t_vad - PREROLL_S)
            clip_end = speech_end + tail
            stop_at = t_vad if paused else float("inf")
            w0, w1 = clip_start - 0.8, clip_end + 0.3
            tracks = [(ai_echo, 0, gain * norm, int(t_vad * SR) if paused else None)]
            if user_pcm is not None:
                tracks.append((user_pcm, int(onset * SR), ugain, None))
            audio = A.mix(int(clip_end * SR) + 1, tracks, seed=zlib.crc32(f"{sid}|{cid}".encode()))
            audio = audio[int(clip_start * SR) * 2:]
            clips.append({
                "id": f"{cid}_{sid}", "condition": cid, "sentence": sid, "label": label,
                "tts_active": label == "user_barge" or label == "echo_only" or (label == "user_after_ai" and t_vad < ai_dur), "gain": gain, "user_gain": ugain,
                "ai_text": ai_text, "user_text": user_text, "expected_user": user_text,
                "echo_text": " ".join(A.window(toks, t_exact, w0, w1, stop_at)),
                "echo_text_interp": " ".join(A.window(toks, t_interp, w0, w1, stop_at)),
                # [từ, mốc ms so với t_vad] của các từ trong cửa sổ: eval offline dựng lại cửa sổ
                # spokenWordsBetween(t0-800, now+300) tại thời điểm của TỪNG interim.
                "echo_words_t": [[tk, round((t - t_vad) * 1000)] for tk, t in zip(toks, t_exact)
                                 if w0 <= t <= min(w1, stop_at)],
                "echo_words_t_interp": [[tk, round((t - t_vad) * 1000)] for tk, t in zip(toks, t_interp)
                                        if w0 <= t <= min(w1, stop_at)],
                "tail_s": tail,
                "clip": {"start_s": round(clip_start, 3), "vad_s": round(t_vad, 3), "end_s": round(clip_end, 3),
                         "dur_s": round(clip_end - clip_start, 3), "ai_dur_s": round(ai_dur, 3),
                         "speech_end_ms": round((speech_end - t_vad) * 1000),
                         "user_onset_s": round(onset, 3) if onset is not None else None, "paused": paused},
                "_audio": audio, "_burst": int((t_vad - clip_start) * SR) * 2,
            })
    return clips


def app_done(events, t_end):
    """Mô phỏng LiveStt.finish(1500)/_maybeFinish: khi nào app coi là xong lượt (ms sau audioStreamEnd)."""
    active, saw, interim, finals = False, False, "", []
    after = [(t, m) for t, m in events if t >= t_end]
    for t, m in events:
        if t >= t_end:
            continue
        va = (m.get("voiceActivity") or {}).get("type")
        if va == "ACTIVITY_START":
            active, saw = True, True
        if va == "ACTIVITY_END":
            active = False
        sc = m.get("serverContent") or {}
        if "interimInputTranscription" in sc:
            interim = (sc["interimInputTranscription"].get("text") or "").strip()
        if (sc.get("inputTranscription") or {}).get("text"):
            finals.append(sc["inputTranscription"]["text"].strip())
            interim = ""
    if not active and not interim and finals:
        return 0, "already_final"
    limit = 350 if (not saw and not finals and not interim) else 1500
    for t, m in after:
        dt = (t - t_end) * 1000
        if dt > limit:
            break
        va = (m.get("voiceActivity") or {}).get("type")
        if va == "ACTIVITY_START":
            active = True
        sc = m.get("serverContent") or {}
        if "interimInputTranscription" in sc:
            interim = (sc["interimInputTranscription"].get("text") or "").strip()
        if (sc.get("inputTranscription") or {}).get("text"):
            finals.append(sc["inputTranscription"]["text"].strip())
            interim = ""
        if sc.get("generationComplete"):
            return round(dt), "generationComplete"
        if va == "ACTIVITY_END":
            active = False
            if not interim and finals:
                return round(dt), "activity_end"
    return limit, "timeout"


async def run_clip(url, setup, clip, key):
    events = []
    rec = {"error": None}
    try:
        async with websockets.connect(url, max_size=None, open_timeout=15) as ws:
            t_open = time.perf_counter()
            await ws.send(json.dumps({"setup": setup}))
            first = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if "setupComplete" not in first:
                raise RuntimeError(f"setup failed: {str(first)[:200]}")
            rec["setup_ms"] = round((time.perf_counter() - t_open) * 1000)

            async def reader():
                try:
                    async for m in ws:
                        events.append((time.perf_counter(), json.loads(m)))
                except Exception:  # noqa: BLE001
                    pass

            rt = asyncio.create_task(reader())
            audio, burst = clip["_audio"], clip["_burst"]

            def msg(b):
                return json.dumps({"realtimeInput": {"audio": {"data": base64.b64encode(b).decode(),
                                                               "mimeType": "audio/pcm;rate=16000"}}})
            t_vad = time.perf_counter()
            for j in range(0, burst, CHUNK):        # tiền ghi xả một lần như voiceRecorder
                await ws.send(msg(audio[j:min(j + CHUNK, burst)]))
            nxt = time.perf_counter()
            for j in range(burst, len(audio), CHUNK):
                await ws.send(msg(audio[j:j + CHUNK]))
                nxt += CHUNK / 2 / SR
                await asyncio.sleep(max(0.0, nxt - time.perf_counter()))
            t_end = time.perf_counter()
            await ws.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
            deadline = t_end + 5.0
            while time.perf_counter() < deadline:
                await asyncio.sleep(0.02)
                if any(t >= t_end and (m.get("serverContent") or {}).get("generationComplete") for t, m in events):
                    await asyncio.sleep(0.3)
                    break
            rt.cancel()
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e).replace(key, "***")[:300]
        return rec
    rel = lambda t: round((t - t_vad) * 1000)  # noqa: E731
    finals, interims, gens, acts = [], [], [], []
    for t, m in events:
        sc = m.get("serverContent") or {}
        if "interimInputTranscription" in sc:
            interims.append({"t_ms": rel(t), "text": (sc["interimInputTranscription"].get("text") or "").strip()})
        if (sc.get("inputTranscription") or {}).get("text"):
            finals.append({"t_ms": rel(t), "text": sc["inputTranscription"]["text"].strip()})
        if sc.get("generationComplete"):
            gens.append(rel(t))
        va = (m.get("voiceActivity") or {}).get("type")
        if va:
            acts.append({"t_ms": rel(t), "type": va})
    end_ms = rel(t_end)
    ff = [f["t_ms"] - end_ms for f in finals if f["t_ms"] >= end_ms]
    gc = [g - end_ms for g in gens if g >= end_ms]
    done_ms, reason = app_done(events, t_end)
    rec.update({
        "transcript": " ".join(f["text"] for f in finals).strip(),
        "finals": finals, "interims": interims, "generation_complete_ms": gens, "activity": acts,
        "timing": {"stream_end_ms": end_ms, "first_final_after_end_ms": ff[0] if ff else None,
                   "last_final_after_end_ms": ff[-1] if ff else None,
                   "gen_complete_after_end_ms": gc[0] if gc else None,
                   "app_done_after_end_ms": done_ms, "app_done_reason": reason,
                   "finals_before_end": sum(1 for f in finals if f["t_ms"] < end_ms)},
    })
    return rec


def git_hashes():
    out = {}
    for f in ["voicego/frontend/src/services/liveStt.js", "voicego/frontend/src/services/voiceRecorder.js",
              "voicego/frontend/src/services/tts.js", "voicego/frontend/src/hooks/useVoiceApp.js",
              "voicego/eval/live/live_echo_eval.py", "voicego/eval/live/_audio.py"]:
        try:
            out[f] = subprocess.run(["git", "hash-object", f], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        except Exception:  # noqa: BLE001
            out[f] = None
    try:
        out["head"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        out["head"] = None
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.path.join(ROOT, "voicego", "backend", ".env"))
    ap.add_argument("--set", default="A", choices=sorted(SETS), help="bộ câu: A=dev, H=holdout, T=đuôi im lặng 550/800")
    ap.add_argument("--runs-dir", default=os.path.join(ROOT, "voicego", "eval", "live", "runs"))
    ap.add_argument("--repeat", type=int, default=3, help="số lần chạy cho REPEAT_SUBSET (pass^k)")
    ap.add_argument("--only", default="", help="lọc clip theo id (chuỗi con, phân cách dấu phẩy)")
    ap.add_argument("--max-sessions", type=int, default=30)
    ap.add_argument("--no-vocab", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    split, sentences = SETS[a.set]
    clips = await build_clips(sentences, CONDITIONS_TAIL if a.set == "T" else None)
    if a.only:
        keys = [k for k in a.only.split(",") if k]
        clips = [c for c in clips if any(k in c["id"] for k in keys)]
    plan = [(c, 1) for c in clips]
    for r in range(2, a.repeat + 1):
        plan += [(c, r) for c in clips if c["id"] in REPEAT_SUBSET]
    if len(plan) > a.max_sessions:
        sys.exit(f"{len(plan)} session > --max-sessions {a.max_sessions}; giảm --repeat hoặc dùng --only")
    print(f"{len(clips)} clip, {len(plan)} session (cache: {A.CACHE})")
    if a.dry_run:
        for c, r in plan:
            print(f"  {c['id']:<22} r{r} {c['label']:<14} dur={c['clip']['dur_s']:.2f}s window={c['echo_text']!r}")
        return

    key = (dotenv_values(a.env).get("GEMINI_API_KEY") or "").strip()
    if not key:
        sys.exit("thiếu GEMINI_API_KEY trong " + a.env)
    url = ("wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta."
           f"GenerativeService.BidiGenerateContent?key={key}")
    trans = {"languageCodes": ["vi-VN"]}
    if not a.no_vocab:
        trans["customVocabulary"] = VOCAB
    setup = {"model": f"models/{MODEL}", "generationConfig": {"responseModalities": ["TEXT"]},
             "inputAudioTranscription": trans}

    cases = []
    vocab_ok = not a.no_vocab
    for i, (c, r) in enumerate(plan):
        rec = await run_clip(url, setup, c, key)
        if rec["error"] and vocab_ok and i == 0 and "setup" in rec["error"]:
            # v1beta không nhận customVocabulary -> chạy lại không có vocab, ghi lại trong meta.
            print("  setup lỗi với customVocabulary, thử lại không vocab:", rec["error"][:120])
            vocab_ok = False
            trans.pop("customVocabulary", None)
            rec = await run_clip(url, setup, c, key)
        case = {k: v for k, v in c.items() if not k.startswith("_")}
        case.update({"source": "live", "run": r, "case_id": f"{c['id']}_r{r}"})
        case.update(rec)
        cases.append(case)
        tm = rec.get("timing") or {}
        print(f"[{i + 1:2d}/{len(plan)}] {case['case_id']:<26} done={tm.get('app_done_after_end_ms')}ms"
              f"({tm.get('app_done_reason')}) err={rec['error']} | {rec.get('transcript', '')!r}")
        await asyncio.sleep(0.5)

    now = datetime.datetime.now()
    run_id = f"{now:%Y%m%dT%H%M%S}-{a.set}"
    meta = {"run_id": run_id, "split": split, "sentence_set": a.set,
            "generated_at": now.isoformat(timespec="seconds"), "model": MODEL,
            "endpoint": "v1beta BidiGenerateContent (?key=)", "custom_vocabulary": vocab_ok,
            "ai_voice": A.AI_VOICE, "user_voice": A.USER_VOICE, "echo_filter": A.PHONE_ECHO_AF,
            "preroll_s": PREROLL_S, "vad_tts_s": VAD_TTS_S, "vad_s": VAD_S, "sessions": len(plan),
            "repeat": a.repeat, "repeat_subset": REPEAT_SUBSET, "src_hashes": git_hashes(),
            "note": "t_ms trong finals/interims tính từ t_vad (lúc xả tiền ghi). source=live: transcript Gemini thật trên giọng TTS tổng hợp."}
    meta["attempted"] = len(plan)
    meta["errored"] = sum(1 for c in cases if c.get("error"))
    # DỮ LIỆU THÔ BẤT BIẾN: mỗi lần chạy một file mới, không bao giờ ghi đè. Chỉ số được
    # tính lại từ các file này bằng bước riêng (npm run eval -> echo.test.js), nên đổi
    # heuristic thì chấm lại trên CÙNG dữ liệu thật, không tốn thêm lượt gọi API.
    os.makedirs(a.runs_dir, exist_ok=True)
    out = os.path.join(a.runs_dir, f"{run_id}.json")
    if os.path.exists(out):
        sys.exit(f"{out} đã tồn tại — không ghi đè dữ liệu thô")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cases": cases}, f, ensure_ascii=False, indent=1)
    print("ghi", out)


if __name__ == "__main__":
    asyncio.run(main())

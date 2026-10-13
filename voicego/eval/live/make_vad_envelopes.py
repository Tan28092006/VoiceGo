"""Tạo datasets/vad_envelopes.json: đường bao RMS THẬT theo từng khung (4096 mẫu @48kHz,
đúng cỡ khung ScriptProcessor của voiceRecorder) của các câu TTS tiếng Việt.

Eval VAD offline (vad.test.js) nhân các đường bao này với mức (level) của từng kịch bản,
nên nhịp âm tiết / khoảng ngắt giữa các từ là của giọng nói thật chứ không phải hằng số.
Đường bao được chuẩn hoá: RMS các khung đang nói (>= 10% khung to nhất) = 1.0.
Bỏ khoảng lặng đầu/cuối file (edge-tts có ~0.1s đầu, ~0.9s cuối).

Không gọi Gemini (chỉ edge-tts, miễn phí). Chạy:
  py -3.13 voicego/eval/live/make_vad_envelopes.py
"""
import asyncio
import json
import math
import os
import sys

import _audio as A

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "datasets", "vad_envelopes.json")

AI = [
    "Giá khoảng ba mươi nghìn đồng, tài xế sẽ tới trong năm phút. Bạn muốn đi xe máy hay ô tô?",
    "Mình đã tìm thấy chợ Bến Thành ở quận 1, cách bạn khoảng hai cây số. Bạn có muốn đặt xe tới đó không?",
    "Tài xế Minh đang tới đón bạn bằng xe Honda màu đỏ, còn khoảng ba phút nữa. Bạn nhớ đứng ở cổng chính nhé.",
    "Chào bạn, mình là trợ lý đặt xe VoiceGo. Bạn muốn đi đâu hôm nay?",
]
USER = [
    "Thôi đổi sang ô tô đi",
    "Không, mình muốn đi Landmark 81",
    "Dừng lại",
    "Đi xe máy",
    "Có, đặt xe tới đó đi",
    "Cho mình đặt xe máy đi chợ Bến Thành nhé",
    "Không",
    "Mình muốn đi tới bệnh viện Chợ Rẫy, à không, sân bay Tân Sơn Nhất",
]


def envelope(pcm):
    rs = A.frame_rms(pcm, 4096)
    top = max(rs)
    act = [r for r in rs if r >= 0.1 * top]
    lvl = math.sqrt(sum(r * r for r in act) / len(act))
    # cắt khoảng lặng đầu/cuối (khung < 3% khung to nhất)
    i0 = next(i for i, r in enumerate(rs) if r >= 0.03 * top)
    i1 = len(rs) - next(i for i, r in enumerate(reversed(rs)) if r >= 0.03 * top)
    return [round(r / lvl, 3) for r in rs[i0:i1]]


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = {"frame_ms": round(4096 / 48000 * 1000, 3), "source": "edge-tts, 48kHz mono, RMS/khung 4096 mẫu",
            "ai_voice": A.AI_VOICE, "user_voice": A.USER_VOICE, "ai": [], "user": []}
    for kind, voice, texts in (("ai", A.AI_VOICE, AI), ("user", A.USER_VOICE, USER)):
        for t in texts:
            pcm, _ = await A.synth(t, voice, 48000)
            env = envelope(pcm)
            data[kind].append({"text": t, "env": env})
            low = sum(1 for v in env if v < 0.3) / len(env)
            print(f"{kind:4} {len(env):3d} khung, {low:.0%} khung < 0.3x | {t}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("ghi", os.path.abspath(OUT))


if __name__ == "__main__":
    asyncio.run(main())

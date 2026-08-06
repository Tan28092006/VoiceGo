"""
test_lang_bac.py — Đo benchmark geocoding + agent cho "Lăng Chủ tịch Hồ Chí Minh"

Ground truth (Google Maps): 21.036757, 105.835085
Alias phổ biến: "Lăng Bác", "Lăng Chủ tịch Hồ Chí Minh"

Chạy: cd voicego/backend && python test_lang_bac.py
"""
import os, sys, time, json, math

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# Ground truth
GT_LAT, GT_LNG = 21.036757, 105.835085
GT_NAME = "Lăng Chủ tịch Hồ Chí Minh"

# Pickup giả: Hà Nội (để test ngoài TPHCM)
HN_LAT, HN_LNG = 21.028511, 105.804817  # Hoàn Kiếm

def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def fmt_dist(km):
    if km < 1:
        return f"{km*1000:.0f} m"
    return f"{km:.2f} km"

# ═══════════════════════════════════════════════════════════════════════════
# 1) TEST TỪNG LAYER GEOCODING ĐỘC LẬP
# ═══════════════════════════════════════════════════════════════════════════
def test_layers():
    print("=" * 80)
    print(f"🎯 Ground truth: {GT_NAME}")
    print(f"   Tọa độ mốc (Google Maps): {GT_LAT}, {GT_LNG}")
    print(f"   Pickup giả: Hà Nội ({HN_LAT}, {HN_LNG})")
    print("=" * 80)

    queries = [
        "lăng chủ tịch hồ chí minh",
        "lăng bác",
        "lang bac",
        "lăng bác hồ",
    ]

    results = []

    for q in queries:
        print(f"\n{'─'*70}")
        print(f'📝 Query: "{q}"')
        print(f"{'─'*70}")

        # ── Layer 0: Gazetteer (places_db) ──
        from places_db import lookup, lookup_all
        t0 = time.time()
        ga = lookup(q)
        dt = time.time() - t0
        if ga:
            d = haversine_km(ga["lat"], ga["lng"], GT_LAT, GT_LNG)
            print(f"  GAZETTEER              {ga['lat']:.5f}, {ga['lng']:.5f}   lệch {fmt_dist(d):>10s}   ({dt*1000:.0f}ms)")
            results.append(("gazetteer", q, ga["lat"], ga["lng"], d, dt))
        else:
            print(f"  GAZETTEER              (không khớp)                              ({dt*1000:.0f}ms)")
            results.append(("gazetteer", q, None, None, None, dt))

        # ── Layer 1: Gemini (grounded) ──
        from geocode import _gemini_locations, GEMINI_API_KEY
        if GEMINI_API_KEY:
            t0 = time.time()
            gem = _gemini_locations(q, HN_LAT, HN_LNG)
            dt = time.time() - t0
            if gem and gem.get("locations"):
                loc = gem["locations"][0]
                d = haversine_km(loc["lat"], loc["lng"], GT_LAT, GT_LNG)
                print(f"  GEMINI (grounded)      {loc['lat']:.5f}, {loc['lng']:.5f}   lệch {fmt_dist(d):>10s}   ({dt*1000:.0f}ms)")
                print(f"    → name: {loc.get('name')}")
                print(f"    → addr: {loc.get('address')}")
                results.append(("gemini_grounded", q, loc["lat"], loc["lng"], d, dt))

                # Geocode the Gemini address via Nominatim
                from geocode import _nominatim_full
                addr = loc.get("address") or loc.get("name")
                t1 = time.time()
                nm = _nominatim_full(addr, HN_LAT, HN_LNG)
                dt1 = time.time() - t1
                if nm:
                    d2 = haversine_km(nm[0], nm[1], GT_LAT, GT_LNG)
                    print(f"  NOMINATIM + đ/c Gemini {nm[0]:.5f}, {nm[1]:.5f}   lệch {fmt_dist(d2):>10s}   ({dt1*1000:.0f}ms)")
                    results.append(("nominatim_gemini_addr", q, nm[0], nm[1], d2, dt1))
                else:
                    print(f"  NOMINATIM + đ/c Gemini (không tìm thấy)                     ({dt1*1000:.0f}ms)")
            else:
                print(f"  GEMINI (grounded)      (không trả kết quả)                   ({dt*1000:.0f}ms)")
        else:
            print(f"  GEMINI (grounded)      (không có GEMINI_API_KEY)")

        # ── Layer 2: Nominatim trực tiếp ──
        from geocode import _nominatim_full
        t0 = time.time()
        nm = _nominatim_full(q, HN_LAT, HN_LNG)
        dt = time.time() - t0
        if nm:
            d = haversine_km(nm[0], nm[1], GT_LAT, GT_LNG)
            print(f"  NOMINATIM (raw)        {nm[0]:.5f}, {nm[1]:.5f}   lệch {fmt_dist(d):>10s}   ({dt*1000:.0f}ms)")
            print(f"    → display: {nm[2]}")
            results.append(("nominatim_raw", q, nm[0], nm[1], d, dt))
        else:
            print(f"  NOMINATIM (raw)        (không tìm thấy)                     ({dt*1000:.0f}ms)")

        # ── Layer 3: Mapbox ──
        from geocode import _mapbox_geocode, MAPBOX_TOKEN
        if MAPBOX_TOKEN:
            t0 = time.time()
            mb = _mapbox_geocode(q, HN_LAT, HN_LNG, limit=3)
            dt = time.time() - t0
            if mb:
                loc = mb[0]
                d = haversine_km(loc["lat"], loc["lng"], GT_LAT, GT_LNG)
                print(f"  MAPBOX                 {loc['lat']:.5f}, {loc['lng']:.5f}   lệch {fmt_dist(d):>10s}   ({dt*1000:.0f}ms)")
                print(f"    → name: {loc.get('name')}")
                results.append(("mapbox", q, loc["lat"], loc["lng"], d, dt))
            else:
                print(f"  MAPBOX                 (không tìm thấy)                     ({dt*1000:.0f}ms)")
        else:
            print(f"  MAPBOX                 (không có MAPBOX_TOKEN)")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 2) TEST FULL resolve_locations (luồng tích hợp)
# ═══════════════════════════════════════════════════════════════════════════
def test_resolve_full():
    print("\n" + "=" * 80)
    print("🔄 TEST FULL resolve_locations (luồng tích hợp)")
    print("=" * 80)

    from geocode import resolve_locations
    queries = ["lăng chủ tịch hồ chí minh", "lăng bác", "lang bac"]

    for q in queries:
        print(f'\n📝 Query: "{q}"')
        t0 = time.time()
        r = resolve_locations(q, HN_LAT, HN_LNG)
        dt = time.time() - t0
        print(f"   ⏱  Tổng thời gian: {dt*1000:.0f}ms")
        print(f"   Source: {r.get('source')}")
        if r.get("ok") and r.get("locations"):
            for i, loc in enumerate(r["locations"]):
                d = haversine_km(loc["lat"], loc["lng"], GT_LAT, GT_LNG)
                print(f"   [{i+1}] {loc['name']}")
                print(f"       {loc.get('address')}")
                print(f"       {loc['lat']:.5f}, {loc['lng']:.5f}   lệch {fmt_dist(d)}")
                print(f"       verified={loc.get('verified')}")
        else:
            print(f"   ❌ {r.get('reason', 'unknown')}")


# ═══════════════════════════════════════════════════════════════════════════
# 3) TEST FULL AGENT (mô phỏng user nói "lăng bác")
# ═══════════════════════════════════════════════════════════════════════════
def test_agent_flow():
    print("\n" + "=" * 80)
    print("🤖 TEST FULL AGENT FLOW (mô phỏng đặt xe đến Lăng Bác)")
    print("=" * 80)

    from agent import run_agent

    pickup = {"name": "Hồ Hoàn Kiếm", "lat": HN_LAT, "lng": HN_LNG}
    messages = []

    # Turn 1: User nói "Tôi muốn đi lăng bác"
    user_msg = "Tôi muốn đi lăng bác"
    messages.append({"role": "user", "content": user_msg})
    print(f'\n👤 User: "{user_msg}"')

    t0 = time.time()
    result = run_agent(messages, pickup)
    dt = time.time() - t0

    print(f"   ⏱  Agent turn: {dt*1000:.0f}ms ({dt:.1f}s)")
    print(f"   🤖 Reply: {result['reply']}")
    if result.get("ui"):
        ui = result["ui"]
        if "destination" in ui:
            dest = ui["destination"]
            d = haversine_km(dest["lat"], dest["lng"], GT_LAT, GT_LNG)
            print(f"   📍 Destination: {dest['name']} @ {dest['lat']:.5f}, {dest['lng']:.5f}")
            print(f"      Lệch ground truth: {fmt_dist(d)}")
        if "candidates" in ui:
            print(f"   📋 Candidates: {len(ui['candidates'])} options")
            for i, c in enumerate(ui["candidates"]):
                d = haversine_km(c["lat"], c["lng"], GT_LAT, GT_LNG)
                print(f"      [{i+1}] {c['name']} @ {c['lat']:.5f}, {c['lng']:.5f} - lệch {fmt_dist(d)}")


# ═══════════════════════════════════════════════════════════════════════════
# 4) ĐO THỜI GIAN TỪNG THÀNH PHẦN E2E (mô phỏng điện thoại)
# ═══════════════════════════════════════════════════════════════════════════
def test_e2e_timing():
    print("\n" + "=" * 80)
    print("⏱  THỜI GIAN TỪNG THÀNH PHẦN (E2E trên điện thoại)")
    print("=" * 80)

    timings = {}

    # 1. STT (Whisper) - mô phỏng bằng text vì không có audio
    print("\n  1️⃣  STT (Whisper via Groq)")
    print("     → Trên điện thoại: ghi âm ~2-3s + upload + Whisper ~1-2s")
    print("     → Ước tính: ~3-5s tổng (ghi âm + nhận dạng)")
    timings["stt"] = "~3-5s (ghi âm + Whisper)"

    # 2. Agent turn (DeepSeek + Geocoding)
    from agent import run_agent
    pickup = {"name": "Hồ Hoàn Kiếm", "lat": HN_LAT, "lng": HN_LNG}

    print("\n  2️⃣  Agent turn (DeepSeek + Geocoding)")
    t0 = time.time()
    result = run_agent(
        [{"role": "user", "content": "tôi muốn đi lăng bác"}],
        pickup
    )
    dt_agent = time.time() - t0
    print(f"     → Agent: {dt_agent*1000:.0f}ms ({dt_agent:.1f}s)")
    print(f"     → Reply: {result['reply'][:100]}...")
    timings["agent"] = dt_agent

    # 3. TTS
    from voice import text_to_speech
    reply_text = result["reply"]
    print(f"\n  3️⃣  TTS (đọc reply: {len(reply_text)} ký tự)")
    t0 = time.time()
    audio = text_to_speech(reply_text)
    dt_tts = time.time() - t0
    if audio:
        print(f"     → TTS: {dt_tts*1000:.0f}ms ({dt_tts:.1f}s), {len(audio)} bytes")
    else:
        print(f"     → TTS: FAILED ({dt_tts*1000:.0f}ms)")
    timings["tts"] = dt_tts

    # Tổng kết
    print("\n" + "─" * 60)
    print("📊 TỔNG KẾT THỜI GIAN E2E (1 lượt hỏi-đáp)")
    print("─" * 60)
    print(f"  STT (ghi âm + Whisper):     {timings['stt']}")
    print(f"  Agent (DeepSeek + Geocode): {timings['agent']*1000:.0f}ms ({timings['agent']:.1f}s)")
    print(f"  TTS (đọc reply):            {timings['tts']*1000:.0f}ms ({timings['tts']:.1f}s)")
    total_server = timings["agent"] + timings["tts"]
    print(f"  ──────────────────────────────────────")
    print(f"  Tổng server-side:           {total_server*1000:.0f}ms ({total_server:.1f}s)")
    print(f"  Tổng ước tính E2E:          ~{total_server + 4:.0f}s (thêm ~3-5s ghi âm + upload)")


if __name__ == "__main__":
    print("🚀 VoiceGo Benchmark: Lăng Chủ tịch Hồ Chí Minh")
    print(f"   Ground truth: {GT_LAT}, {GT_LNG}")
    print()

    test_layers()
    test_resolve_full()
    test_agent_flow()
    test_e2e_timing()

    print("\n\n✅ Benchmark hoàn tất.")

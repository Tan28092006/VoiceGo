// Bộ mô phỏng VAD: dựng chuỗi RMS từng khung cho một kịch bản (vad_scenarios.json) rồi
// chạy CHÍNH VoiceRecorder (src/services/voiceRecorder.js) qua AudioContext giả, kèm một
// vòng lặp app tối giản bắt chước useVoiceApp:
//  - mic mở 1s sau khi AI bắt đầu đọc (armMs Gemini Live), mở lại 300ms sau báo nhầm;
//  - VAD kêu lúc AI đang đọc -> TẠM DỪNG AI (hết tiếng vọng). Không có người nói thật ->
//    báo nhầm: AI im tới khi onAutoStop (+400ms chờ Gemini trả rỗng) hoặc hết 1500ms,
//    rồi đọc tiếp; có người nói thật -> AI dừng hẳn;
//  - một lượt thật xong -> mic mở lại sau ~1s (STT + agent).
// Không mô phỏng Gemini: "người nói thật" là nhãn của kịch bản, không phải transcript.
export const FRAME_MS = 4096 / 48000 * 1000;

function rng(seed) {             // mulberry32
  let a = seed >>> 0;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const gauss = (r) => Math.sqrt(-2 * Math.log(r() || 1e-9)) * Math.cos(2 * Math.PI * r());

/** Dựng chuỗi RMS + nhãn cho một seed. */
export function buildTrace(sc, env, seed) {
  const r = rng(seed * 7919 + sc.id.split('').reduce((s, ch) => s + ch.charCodeAt(0), 0));
  const n = Math.round(sc.dur_s * 1000 / FRAME_MS);
  const f = (s) => Math.round(s * 1000 / FRAME_MS);
  const noise = new Float64Array(n), echo = new Float64Array(n), user = new Float64Array(n), tr = new Float64Array(n);
  const tts = new Uint8Array(n);
  const nz = sc.noise || { level: 0.0008, jitter: 0.25 };
  for (let k = 0; k < n; k++) noise[k] = nz.level * Math.exp((nz.jitter || 0) * gauss(r));
  for (const b of nz.bursts || []) {
    const starts = b.every_s ? Array.from({ length: Math.ceil(sc.dur_s / b.every_s) }, (_, i) => (b.phase_s || 0) + i * b.every_s) : [b.at_s];
    for (const s0 of starts) for (let k = f(s0); k < Math.min(n, f(s0 + b.dur_s)); k++) noise[k] = Math.hypot(noise[k], b.level * Math.exp(0.3 * gauss(r)));
  }
  // Tiếng vọng: nối các câu AI liên tiếp (cách 4 khung), bắt đầu ở vị trí ngẫu nhiên.
  const ai = env.ai.map((x) => x.env);
  let ai_i = Math.floor(r() * ai.length), ai_k = 0;
  for (const seg of sc.tts || []) {
    for (let k = f(seg.from_s); k < Math.min(n, f(seg.to_s)); k++) {
      tts[k] = 1;
      let lvl = sc.echo?.level || 0;
      for (const st of sc.echo?.steps || []) if (k >= f(st.at_s)) lvl = st.level;
      const e = ai[ai_i];
      const v = ai_k < e.length ? e[ai_k] : 0;
      ai_k++; if (ai_k >= e.length + 4) { ai_k = 0; ai_i = (ai_i + 1) % ai.length; }
      echo[k] = lvl * v;
    }
  }
  const utts = [];
  (sc.users || []).forEach((u, i) => {
    const ei = u.env != null ? u.env : (seed + i) % env.user.length;
    const e = env.user[ei].env;
    const at = u.at_s != null ? u.at_s : u.at_min + r() * (u.at_max - u.at_min);
    const k0 = f(at);
    for (let j = 0; j < e.length && k0 + j < n; j++) user[k0 + j] = u.level * e[j];
    utts.push({ k0, k1: Math.min(n - 1, k0 + e.length - 1), level: u.level, frames: e.length, env: ei, inTts: false });
  });
  for (const t of sc.transients || []) {
    for (let s = t.phase_s || 0; s < sc.dur_s; s += t.every_s) for (let j = 0; j < t.frames; j++) { const k = f(s) + j; if (k < n) tr[k] = t.level; }
  }
  utts.forEach((u) => { u.inTts = tts[u.k0] === 1; });
  return { n, noise, echo, user, tr, tts, utts };
}

/** Chạy một seed. Trả các sự kiện đo được. */
export async function simulate(VoiceRecorder, ctl, sc, env, seed) {
  const T = buildTrace(sc, env, seed);
  const rec = new VoiceRecorder();
  let k = 0;
  let ttsStopped = false, pausedUntil = -1, paused = false;
  const ttsOn = (kk) => T.tts[kk] === 1 && !ttsStopped;
  const isTts = () => ttsOn(k) && !paused;
  const out = { detections: [], falseTts: 0, falseIdle: 0, stallMs: 0, ends: [], capped: 0, ttsFrames: 0, idleFrames: 0 };
  let recording = false, nextStart = 0, falseEndAt = -1, curUtt = null;
  const userAt = (kk) => T.utts.find((u) => kk >= u.k0 && kk <= u.k1 + 3);
  const handled = new Set();

  // Phòng đã "học nền" từ các lượt trước (giữa phiên): 3s ồn nền, mic mở, AI im.
  ctl.isTts = () => false;
  await rec.start({ isTtsPlaying: () => ctl.isTts(), onAutoStop: () => {}, noSpeechMs: 60000, silenceMs: 800 });
  for (let j = 0; j < 36; j++) ctl.frame(T.noise[j % T.n]);
  rec.stop();
  ctl.isTts = isTts;
  // Mic mở: AI đọc từ đầu -> sau 1s (arm); không thì mở ngay.
  nextStart = T.tts[0] ? Math.round(1000 / FRAME_MS) : 0;

  const start = async () => {
    recording = true;
    await rec.start({
      isTtsPlaying: () => ctl.isTts(), silenceMs: 950, getSilenceMs: () => 800, noSpeechMs: 9000, speechFramesTts: 5,
      onSpeechStart: () => {
        const u = userAt(k);
        const ttsNow = ttsOn(k) && !paused;
        if (u && !handled.has(u)) {
          handled.add(u);
          curUtt = u;
          out.detections.push({ utt: T.utts.indexOf(u), latencyMs: (k - u.k0 + 1) * FRAME_MS, duringTts: ttsNow });
          if (ttsNow) ttsStopped = true;           // chen ngang thật -> AI dừng hẳn
        } else {
          curUtt = null;
          if (ttsNow) { out.falseTts++; paused = true; pausedUntil = k + Math.round(1500 / FRAME_MS); } else out.falseIdle++;
        }
      },
      onAutoStop: () => {
        recording = false;
        rec.stop();
        if (curUtt) {
          out.ends.push({ endMs: (k - curUtt.k1) * FRAME_MS, capped: !!rec.cappedTurn });
          if (rec.cappedTurn) out.capped++;
          curUtt = null;
          nextStart = k + Math.round(1000 / FRAME_MS);
        } else {
          if (paused) pausedUntil = Math.min(pausedUntil, k + Math.round(400 / FRAME_MS));
          nextStart = k + (paused ? Math.round(1800 / FRAME_MS) : 1);
        }
      },
    });
  };

  for (k = 0; k < T.n; k++) {
    if (paused && k >= pausedUntil) {
      paused = false;
      if (recording) { recording = false; rec.stop(); }
      nextStart = Math.max(nextStart, k + Math.round(300 / FRAME_MS));
      if (falseEndAt < 0) falseEndAt = k;
    }
    if (paused) out.stallMs += FRAME_MS;
    if (!recording && k >= nextStart) await start();
    if (ttsOn(k)) out.ttsFrames++; else out.idleFrames++;
    const echo = paused ? 0 : (ttsStopped ? 0 : T.echo[k]);
    ctl.frame(Math.sqrt(T.noise[k] ** 2 + echo ** 2 + T.user[k] ** 2 + T.tr[k] ** 2));
  }
  if (recording) rec.stop();
  out.utts = T.utts.map((u, i) => ({ i, frames: u.frames, env: u.env, inTts: u.inTts, detected: out.detections.some((d) => d.utt === i) }));
  return out;
}

// EVAL VAD năng lượng (src/services/voiceRecorder.js) trên chuỗi RMS tổng hợp từ đường
// bao giọng THẬT (vad_envelopes.json) + ồn/tiếng vọng/ho theo kịch bản (vad_scenarios.json).
// Chạy CHÍNH VoiceRecorder qua AudioContext giả + đồng hồ giả (cách của vad_test.mjs /
// tests/unit/voiceRecorder.vad.test.js), vòng lặp app tối giản ở _vadsim.js.
// Chỉ số: tỉ lệ nghe được, độ trễ phát hiện (ms, phân phối), báo nhầm/phút lúc AI đọc và
// lúc im, thời gian AI bị khựng vì báo nhầm, thời gian chốt lượt sau khi người dùng ngừng
// (kể cả khi ồn LUÔN trên ngưỡng -> chỉ trần maxTurnMs cứu).
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import { loadJson, pct, rate, quantile, table, writeResult } from './_lib.js';
import { simulate, FRAME_MS } from './_vadsim.js';

const ctl = { proc: null, isTts: () => false, clock: 0, buf: new Float32Array(4096) };
ctl.frame = (rms) => { ctl.buf.fill(rms); ctl.proc.onaudioprocess({ inputBuffer: { getChannelData: () => ctl.buf } }); ctl.clock += FRAME_MS; };
class FakeCtx {
  constructor() { this.sampleRate = 48000; this.state = 'running'; this.destination = {}; }
  resume() { return Promise.resolve(); }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createScriptProcessor() { const p = { connect() {}, disconnect() {} }; ctl.proc = p; return p; }
  createGain() { return { gain: {}, connect() {}, disconnect() {} }; }
}

let VoiceRecorder;
beforeAll(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });   // watchdog 3s của recorder không được chạy theo giờ thật
  vi.stubGlobal('window', { AudioContext: FakeCtx, location: { search: '' } });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({ getAudioTracks: () => [{ readyState: 'live' }], getTracks: () => [] }) } });
  vi.stubGlobal('document', { getElementById: () => null });
  vi.stubGlobal('performance', { now: () => ctl.clock });
  vi.resetModules();
  ({ default: VoiceRecorder } = await import('../../src/services/voiceRecorder.js'));
});
afterAll(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const d = (xs) => {
  const a = xs.filter((x) => x != null);
  if (!a.length) return '—';
  const q = (p) => Math.round(quantile(a, p));
  return `${q(0.5)} / ${q(0.95)} / ${q(0.99)}${a.length < 100 ? '*' : ''} (n=${a.length})`;
};

describe('VAD eval — kịch bản tổng hợp', () => {
  const env = loadJson('vad_envelopes.json');
  const ds = loadJson('vad_scenarios.json');
  it('chạy mọi kịch bản, in bảng, ghi kết quả', async () => {
    const res = {};
    for (const sc of ds.scenarios) {
      const runs = [];
      const mute = vi.spyOn(console, 'log').mockImplementation(() => {});   // log của recorder
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      try { for (let s = 1; s <= sc.seeds; s++) runs.push(await simulate(VoiceRecorder, ctl, sc, env, s)); } finally { mute.mockRestore(); warn.mockRestore(); }
      const utts = runs.flatMap((r) => r.utts);
      const det = runs.flatMap((r) => r.detections);
      const ttsMin = runs.reduce((a, r) => a + r.ttsFrames, 0) * FRAME_MS / 60000;
      const idleMin = runs.reduce((a, r) => a + r.idleFrames, 0) * FRAME_MS / 60000;
      const ends = runs.flatMap((r) => r.ends);
      res[sc.id] = {
        group: sc.group, desc: sc.desc, seeds: sc.seeds,
        nUtt: utts.length, detected: rate(utts.filter((u) => u.detected).length, utts.length),
        latency: det.map((x) => Math.round(x.latencyMs)),
        falseTtsPerMin: ttsMin > 0.05 ? runs.reduce((a, r) => a + r.falseTts, 0) / ttsMin : null,
        falseIdlePerMin: idleMin > 0.05 ? runs.reduce((a, r) => a + r.falseIdle, 0) / idleMin : null,
        stallSecPerMin: ttsMin > 0.05 ? runs.reduce((a, r) => a + r.stallMs, 0) / 1000 / ttsMin : null,
        endMs: ends.map((e) => Math.round(e.endMs)), capped: ends.filter((e) => e.capped).length, nEnds: ends.length, utts,
      };
    }
    const f1 = (x) => (x == null ? '—' : x.toFixed(1));
    const groups = [...new Set(ds.scenarios.map((s) => s.group))];
    for (const g of groups) {
      table(`VAD — ${g} (latency/chốt lượt: p50 / p95 / p99 ms; * = n<100)`,
        ['id', 'kịch bản', 'nghe được', 'trễ phát hiện', 'báo nhầm/phút AI đọc', 'báo nhầm/phút AI im', 'AI khựng s/phút', 'ngừng nói -> chốt lượt', 'chạm trần'],
        ds.scenarios.filter((s) => s.group === g).map((s) => { const r = res[s.id]; return [s.id, s.desc.slice(0, 58), r.nUtt ? `${pct(r.detected)} (n=${r.nUtt})` : '—', d(r.latency), f1(r.falseTtsPerMin), f1(r.falseIdlePerMin), f1(r.stallSecPerMin), d(r.endMs), r.nEnds ? `${r.capped}/${r.nEnds}` : '—']; }));
    }
    // Theo từng câu người dùng (độ dài khung) — câu ngắn có vượt được speechFrames không?
    const byEnv = {};
    for (const sc of ds.scenarios) for (const u of res[sc.id].utts) {
      const key = `${u.env}|${u.inTts ? 'AI đọc' : 'AI im'}|${sc.id}`;
      (byEnv[key] ||= []).push(u.detected);
    }
    const envRows = env.user.map((e, i) => {
      const cell = (mode, ids) => { const xs = ids.flatMap((id) => byEnv[`${i}|${mode}|${id}`] || []); return xs.length ? `${pct(rate(xs.filter(Boolean).length, xs.length))} (n=${xs.length})` : '—'; };
      return [i, JSON.stringify(e.text).slice(0, 44), e.env.length, cell('AI im', ['Q1', 'N2', 'T14']), cell('AI đọc', ['T2', 'T7'])];
    });
    table('VAD — nghe được theo câu (giọng đủ to: Q1/N2/T14 khi AI im, T2/T7 khi AI đọc)', ['env', 'câu', 'số khung', 'AI im (cần 8 khung)', 'AI đọc (cần 5 khung)'], envRows);
    writeResult('vad', { frame_ms: FRAME_MS, scenarios: res });
    // Sàn hồi quy LỎNG, đặt ngay dưới baseline đo được (Q1 75%, N2 70.8%, T7 91.7%, T1 0/phút):
    // chỉ bắt tụt hạng rõ rệt, không phải mục tiêu. Q1/N2 < 100% vì "Không"/"Dừng lại" quá
    // ngắn cho speechFrames=8 (xem bảng theo câu) — đó là phát hiện, không phải lỗi mô phỏng.
    expect(res.Q1.detected).toBeGreaterThanOrEqual(0.7);
    expect(res.N2.detected).toBeGreaterThanOrEqual(0.6);
    expect(res.T7.detected).toBeGreaterThanOrEqual(0.8);
    expect(res.T1.falseTtsPerMin).toBeLessThanOrEqual(3);
    expect(res.N4.capped).toBe(res.N4.nEnds);   // ồn luôn trên ngưỡng -> chỉ trần maxTurnMs chốt được
  }, 120000);
});

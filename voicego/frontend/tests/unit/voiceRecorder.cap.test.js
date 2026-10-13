// Regression (Agent A, task A3): hard cap per turn. Continuous noise above the VAD
// threshold (street, motorbikes) means the recorder never sees silence after speech
// started, so the turn never ended ("Đang nghe bạn nói…" forever, nothing sent).
// After maxTurnMs (default 20s, ?maxturn=) from speech start the recorder forces the
// endpoint through onAutoStop and flags cappedTurn. Fake audio clock: 85.33ms/frame.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

let proc = null;
let search = '';
class FakeCtx {
  constructor() { this.sampleRate = 48000; this.state = 'running'; this.destination = {}; }
  resume() { return Promise.resolve(); }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createScriptProcessor() { proc = { connect() {}, disconnect() {} }; return proc; }
  createGain() { return { gain: {}, connect() {}, disconnect() {} }; }
}
let clock = 0;
const frame = (rms) => {
  const d = new Float32Array(4096).fill(rms);
  proc.onaudioprocess({ inputBuffer: { getChannelData: () => d } });
  clock += 85.33;
};

let VoiceRecorder;
beforeAll(async () => {
  vi.stubGlobal('window', { AudioContext: FakeCtx, get location() { return { search }; } });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({ getAudioTracks: () => [{ readyState: 'live' }], getTracks: () => [] }) } });
  vi.stubGlobal('document', { getElementById: () => null });
  vi.stubGlobal('performance', { now: () => clock });
  vi.resetModules();
  ({ default: VoiceRecorder } = await import('../../src/services/voiceRecorder.js'));
});
afterAll(() => { vi.unstubAllGlobals(); });

describe('VoiceRecorder turn cap', () => {
  it('speech that never goes quiet is endpointed at ~20s, cappedTurn=true, WAV returned', async () => {
    const rec = new VoiceRecorder();
    let stops = 0, startedAt = null;
    await rec.start({ onAutoStop: () => { stops++; }, onSpeechStart: () => { startedAt = clock; }, noSpeechMs: 60000 });
    for (let i = 0; i < 6; i++) frame(0.001);           // learn a quiet floor
    let n = 0;
    while (!stops && n < 400) { frame(0.05); n++; }      // loud forever
    expect(startedAt).not.toBe(null);
    expect(stops).toBe(1);
    expect(rec.cappedTurn).toBe(true);
    const dur = clock - startedAt;
    expect(dur).toBeGreaterThan(20000);
    expect(dur).toBeLessThan(20300);
    for (let i = 0; i < 20; i++) frame(0.05);            // no second onAutoStop
    expect(stops).toBe(1);
    expect(rec.stop()).not.toBe(null);
  });

  it('a normal turn ends on silence and is not flagged capped; ?maxturn= overrides the cap', async () => {
    const rec = new VoiceRecorder();
    let stops = 0;
    await rec.start({ onAutoStop: () => { stops++; }, silenceMs: 950, noSpeechMs: 60000 });
    for (let i = 0; i < 6; i++) frame(0.001);
    for (let i = 0; i < 20; i++) frame(0.05);
    for (let i = 0; i < 14; i++) frame(0.001);
    expect(stops).toBe(1);
    expect(rec.cappedTurn).toBe(false);
    rec.stop();

    search = '?maxturn=3000';
    stops = 0;
    await rec.start({ onAutoStop: () => { stops++; }, noSpeechMs: 60000 });
    let n = 0, startAt = null;
    while (!stops && n < 200) { if (rec.heardSpeech && startAt == null) startAt = clock; frame(0.05); n++; }
    expect(rec.cappedTurn).toBe(true);
    expect(clock - startAt).toBeLessThan(3500);
    rec.stop();
    search = '';
  });
});

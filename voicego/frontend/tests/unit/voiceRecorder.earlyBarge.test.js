// Regression (Agent A, task A4 / eval B3): the user starting to speak BEFORE the mic arms
// (the first ~1s of an AI sentence) must not be learned as the "echo level". Before, every
// pre-arm TTS frame went into _echoPeak, so the threshold became the user's own voice x1.25
// and early barge-ins were detected only 17-25% (vad eval T12/T13). Sustained louder echo
// (volume up) must still be learned (T11). Fake audio clock: 85.33ms per 4096-sample frame.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

let proc = null;
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
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });   // watchdog must not run on real time
  vi.stubGlobal('window', { AudioContext: FakeCtx, location: { search: '' } });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({ getAudioTracks: () => [{ readyState: 'live' }], getTracks: () => [] }) } });
  vi.stubGlobal('document', { getElementById: () => null });
  vi.stubGlobal('performance', { now: () => clock });
  vi.resetModules();
  ({ default: VoiceRecorder } = await import('../../src/services/voiceRecorder.js'));
});
afterAll(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

async function scenario({ echo, user, preArmUserFrames, tail = 20 }) {
  let tts = false, started = false;
  const rec = new VoiceRecorder();
  // learn the room (AI silent), then stop: the stream stays open, frames keep coming
  await rec.start({ isTtsPlaying: () => tts, onAutoStop: () => {}, noSpeechMs: 60000 });
  for (let i = 0; i < 12; i++) frame(0.001);
  rec.stop();
  tts = true;
  const preArm = 12;                                   // mic arms 1s after the AI starts
  for (let i = 0; i < preArm; i++) frame(i >= preArm - preArmUserFrames ? Math.hypot(echo, user) : echo);
  await rec.start({ isTtsPlaying: () => tts, onSpeechStart: () => { started = true; }, onAutoStop: () => {},
    noSpeechMs: 60000, speechFramesTts: 5 });
  let n = 0;
  for (; n < tail && !started; n++) frame(user ? Math.hypot(echo, user) : echo);
  rec.stop();
  return { started, frames: n, echoPeak: rec._echoPeak };
}

describe('VoiceRecorder: early barge-in before the mic arms (B3)', () => {
  it('user 0.04 over echo 0.02 starting 0.5s before arming is detected right after arming', async () => {
    const r = await scenario({ echo: 0.02, user: 0.04, preArmUserFrames: 6 });
    expect(r.started).toBe(true);
    expect(r.frames).toBeLessThanOrEqual(6);
    expect(r.echoPeak).toBeLessThan(0.03);           // the user's voice was not learned as echo
  });
  it('echo alone (no user) still never triggers', async () => {
    const r = await scenario({ echo: 0.02, user: 0, preArmUserFrames: 0, tail: 60 });
    expect(r.started).toBe(false);
  });
  it('a sustained louder echo (volume up) IS learned before arming', async () => {
    const rec = new VoiceRecorder();
    let tts = false;
    await rec.start({ isTtsPlaying: () => tts, onAutoStop: () => {}, noSpeechMs: 60000 });
    for (let i = 0; i < 12; i++) frame(0.001);
    rec.stop();
    tts = true;
    for (let i = 0; i < 12; i++) frame(0.01);         // echo level known
    for (let i = 0; i < 24; i++) frame(0.03);         // 2s louder, AI still speaking, mic not armed
    expect(rec._echoPeak).toBeGreaterThan(0.025);
  });
});

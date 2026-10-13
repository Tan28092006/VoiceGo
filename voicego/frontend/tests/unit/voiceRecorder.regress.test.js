// Regression (Agent A) for VoiceRecorder:
//  - noSpeechMs counts from when the AI STOPPED talking, not from mic open
//  - watchdog: no audio frames at all (AudioContext stuck) -> noAudio + onAutoStop (~3s, fake timers)
//  - dead mic track (iOS interruption) -> getUserMedia is called again on the next start()
// Audio frames run on a fake performance clock (85.33ms per 4096-sample frame @48kHz).
// Sequential tests sharing one recorder.
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';

let proc = null;
let gum = 0;
let trackState = 'live';
class FakeCtx {
  constructor() { this.sampleRate = 48000; this.state = 'running'; this.destination = {}; }
  resume() { return Promise.resolve(); }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createScriptProcessor() { proc = { connect() {}, disconnect() {} }; return proc; }
  createGain() { return { gain: {}, connect() {}, disconnect() {} }; }
}
const mkStream = () => {
  const tr = { get readyState() { return trackState; }, stop() {} };
  return { getAudioTracks: () => [tr], getTracks: () => [tr] };
};
let clock = 0;
const frame = (rms) => {
  const d = new Float32Array(4096).fill(rms);
  proc.onaudioprocess({ inputBuffer: { getChannelData: () => d } });
  clock += 85.33;
};
const frames = (rms, n) => { for (let i = 0; i < n; i++) frame(rms); };
// Watchdog uses timers, not the audio clock: fake only the timer functions.
const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });

let VoiceRecorder;
beforeAll(async () => {
  vi.stubGlobal('window', { AudioContext: FakeCtx, location: { search: '' } });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => { gum++; trackState = 'live'; return mkStream(); } } });
  vi.stubGlobal('document', { getElementById: () => null });
  vi.stubGlobal('performance', { now: () => clock });
  vi.resetModules();
  ({ default: VoiceRecorder } = await import('../../src/services/voiceRecorder.js'));
});
afterEach(() => { vi.useRealTimers(); });
afterAll(() => { vi.unstubAllGlobals(); });

describe('VoiceRecorder regressions (sequential)', () => {
  let tts = false;
  let stopped = 0;
  let rec;
  const start = (o = {}) => rec.start({ isTtsPlaying: () => tts, onAutoStop: () => { stopped++; }, noSpeechMs: 9000, ...o });

  it('noSpeech timer starts when the AI stops talking, not at mic open', async () => {
    rec = new VoiceRecorder();
    await start();
    frames(0.001, 6); // warmup / floor
    tts = true;
    frames(0.001, 176); // ~15s of AI speech (echo cancelled -> quiet mic)
    expect(stopped).toBe(0);
    tts = false;
    frames(0.001, 100); // 8.5s of silence after the AI stopped
    expect(stopped).toBe(0);
    frames(0.001, 10); // past 9s after the AI stopped
    expect(stopped).toBe(1);
    rec.stop();
  });

  it('without TTS the plain 9s timeout from mic open still works', async () => {
    stopped = 0;
    await start();
    frames(0.001, 110);
    expect(stopped).toBe(1);
    rec.stop();
  });

  it('watchdog: no frames for ~3s -> onAutoStop, noAudio=true, stop() returns null', async () => {
    stopped = 0;
    fakeTimers();
    await start();
    expect(rec.noAudio).toBe(false);
    await vi.advanceTimersByTimeAsync(3200);
    expect(stopped).toBe(1);
    expect(rec.noAudio).toBe(true);
    expect(rec.stop()).toBeNull();
  });

  it('watchdog does not fire while frames flow', async () => {
    stopped = 0;
    fakeTimers();
    await start();
    frame(0.001);
    await vi.advanceTimersByTimeAsync(3200);
    expect(stopped).toBe(0);
    expect(rec.noAudio).toBe(false);
    rec.stop();
  });

  it('dead track -> getUserMedia again; live track -> stream reused', async () => {
    const before = gum;
    trackState = 'ended';
    await start();
    expect(gum).toBe(before + 1);
    await start();
    expect(gum).toBe(before + 1);
    rec.stop();
  });
});

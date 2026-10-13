// VoiceRecorder VAD: drive onaudioprocess with synthetic frames of a given RMS
// (4096 samples @48kHz = 85.33ms per frame) on a fake clock.
// Covers P2 (noise floor kept across turns), P4 (5 frames while the AI talks) and the
// echo-peak guard (the AI's own voice in the mic must not count as the user).
// Sequential tests sharing one recorder: the floor/echo state carries over on purpose.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

let proc = null;
class FakeCtx {
  constructor() { this.sampleRate = 48000; this.state = 'running'; this.destination = {}; }
  resume() { return Promise.resolve(); }
  createMediaStreamSource() { return { connect() {} }; }
  createScriptProcessor() { proc = { connect() {} }; return proc; }
  createGain() { return { gain: {}, connect() {} }; }
}
let clock = 0;
const frame = (rms) => {
  const d = new Float32Array(4096).fill(rms);
  proc.onaudioprocess({ inputBuffer: { getChannelData: () => d } });
  clock += 85.33;
};

let VoiceRecorder;
beforeAll(async () => {
  vi.stubGlobal('window', { AudioContext: FakeCtx, location: { search: '' } });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({}) } });
  vi.stubGlobal('document', { getElementById: () => null });
  vi.stubGlobal('performance', { now: () => clock });
  vi.resetModules();
  ({ default: VoiceRecorder } = await import('../../src/services/voiceRecorder.js'));
});
afterAll(() => { vi.unstubAllGlobals(); });

describe('VoiceRecorder VAD (sequential, shared recorder state)', () => {
  let tts = false;
  let rec;
  let started = -1, stopped = false, frames = 0;
  const startTurn = async (extra = {}) => {
    started = -1; stopped = false; frames = 0;
    await rec.start({
      isTtsPlaying: () => tts,
      onSpeechStart: () => { started = frames; },
      onAutoStop: () => { stopped = true; },
      silenceMs: 950, noSpeechMs: 60000, ...extra,
    });
  };
  const feed = (rms, n) => { for (let i = 0; i < n; i++) { frames++; frame(rms); } };

  it('turn 1: learns a quiet room (~0.001), detects speech (0.02), auto-stops on silence', async () => {
    rec = new VoiceRecorder();
    await startTurn();
    feed(0.001, 10); feed(0.02, 12);
    expect(started).toBeGreaterThanOrEqual(0);
    feed(0.001, 14);
    expect(stopped).toBe(true);
    rec.stop();
  });

  it('P2: turn 2 opens while the user is already talking -> no warmup, floor kept, detected at frame 8', async () => {
    await startTurn();
    feed(0.02, 9);
    expect(started).toBe(8);
    rec.stop();
  });

  it('echo 0.03 never counts as speech; P4: user louder than echo detected after 5 frames', async () => {
    tts = true;
    feed(0.03, 12); // AI speaks before the mic arms (1s lock): recorder learns the echo peak
    await startTurn({ speechFramesTts: 5 });
    feed(0.03, 40); // echo continues while listening
    expect(started).toBe(-1);
    feed(0.08, 6); // user talks over the AI, clearly louder than the echo
    expect(started - 40).toBe(5);
    rec.stop();
  });

  it('right after the AI stops, a normal answer is heard (floor not inflated by echo)', async () => {
    tts = false;
    await startTurn();
    feed(0.001, 2); feed(0.02, 9);
    expect(started).toBeGreaterThanOrEqual(0);
    expect(started).toBeLessThanOrEqual(11);
    rec.stop();
  });

  it('greeting: first mic open happens during the AI greeting -> no false trigger, user over it detected', async () => {
    const r2 = new VoiceRecorder();
    tts = true;
    let st = -1, n = 0;
    await r2.start({ isTtsPlaying: () => tts, onSpeechStart: () => { st = n; }, onAutoStop: () => {}, noSpeechMs: 60000, speechFramesTts: 5 });
    for (let i = 0; i < 40; i++) { n++; frame(0.03); }
    expect(st).toBe(-1);
    for (let i = 0; i < 6; i++) { n++; frame(0.08); }
    expect(st).toBe(45);
    r2.stop();
  });
});

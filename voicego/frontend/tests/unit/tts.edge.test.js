// Regression (Agent A): the Edge (<audio> -> /api/voice/tts_stream) path of speak()
// must always settle, otherwise `await speak(m)` keeps busy=true and the PIN chain
// (.then(() => speak(...))) never runs.
//  - superseded by a new speak() / stop() -> the old promise resolves
//  - the stream never starts -> falls back to the browser voice after ~10s (fake timers)
//  - onStart fires once even when 'playing' re-fires after a resume
// Sequential tests sharing one fresh tts.js module (engine = edge).
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';

let amode = 'ok'; // ok | hang (playing, never ends) | never (no playing event)
const audioSrc = [];
const spoken = [];
const ss = {
  speaking: false, pending: false, paused: false,
  getVoices: () => [{ name: 'Google Tiếng Việt', lang: 'vi-VN' }],
  addEventListener() {},
  speak(u) {
    spoken.push(u.text); this.speaking = true;
    setTimeout(() => { u.onstart?.(); setTimeout(() => { this.speaking = false; u.onend?.(); }, 10); }, 5);
  },
  cancel() { this.speaking = false; }, pause() {}, resume() {},
};
class FakeAudio {
  constructor() { this.paused = true; this.ended = false; this.currentTime = 0; }
  set src(v) { audioSrc.push(v); this._s = v; this.ended = false; }
  get src() { return this._s || ''; }
  get currentSrc() { return this.src; }
  play() {
    this.paused = false;
    if (amode === 'never') return new Promise(() => {});
    setTimeout(() => {
      this.currentTime = 0.1; this.onplaying?.();
      if (amode === 'hang') return;
      setTimeout(() => { if (this.paused) return; this.paused = true; this.ended = true; this.onended?.(); }, 40);
    }, 5);
    return Promise.resolve();
  }
  pause() { this.paused = true; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const settledWithin = (p, ms) => Promise.race([p.then(() => true), sleep(ms).then(() => false)]);

let tts;
beforeAll(async () => {
  vi.stubGlobal('window', { speechSynthesis: ss, location: { search: '' } });
  vi.stubGlobal('navigator', { userAgent: 'Android' });
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(t) { this.text = t; } });
  vi.stubGlobal('Audio', FakeAudio);
  vi.resetModules();
  tts = await import('../../src/services/tts.js');
  tts.setTtsEngine('edge');
});
afterEach(() => { vi.useRealTimers(); });
afterAll(() => { vi.unstubAllGlobals(); });

describe('tts.js Edge path always settles (sequential)', () => {
  it('a new speak() supersedes one mid-playback -> the old one resolves and its .then() runs', async () => {
    amode = 'hang';
    let chained = false;
    const a = tts.speak('Tài xế đã đến gần.').then(() => { chained = true; });
    await sleep(20);
    amode = 'ok';
    const b = tts.speak('Tài xế còn cách khoảng 50 mét.');
    expect(await settledWithin(a, 200)).toBe(true);
    expect(chained).toBe(true);
    await b;
  });

  it('stop() during playback resolves the pending speak() (barge-in confirm / repeatPin)', async () => {
    amode = 'hang';
    const p = tts.speak('Đã đặt xe. Đang tìm tài xế cho bạn.');
    await sleep(20);
    tts.stop();
    expect(await settledWithin(p, 200)).toBe(true);
  });

  it('onStart fires exactly once across pause/resume', async () => {
    amode = 'hang';
    let starts = 0;
    const p = tts.speak('Giá khoảng ba mươi nghìn đồng.', { onStart: () => starts++ });
    await sleep(20);
    expect(tts.pauseSpeech()).toBe(true);
    tts.resumeSpeech();
    await sleep(20);
    expect(starts).toBe(1);
    tts.stop();
    await p;
  });

  it('stream never starts -> settles within ~10s by reading with the browser voice', async () => {
    vi.useFakeTimers();
    amode = 'never';
    spoken.length = 0;
    let settled = false;
    const p = tts.speak('Xin chào.').then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(11500);
    expect(settled).toBe(true);
    expect(spoken).toContain('Xin chào.');
    await p;
  });
});

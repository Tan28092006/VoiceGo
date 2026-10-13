// Regression (Agent A, task A3): when the browser voice already failed to make a sound
// in this speak() call (2.5s no-start) and the Edge stream then also never starts (10s),
// speak() must NOT try the browser voice a second time (another ~2.5s of silence that
// almost surely fails again). Worst case was 2.5 + 10 + 2.5s of silence; now 2.5 + 10s.
// If the Edge path is used directly (engine=edge), the browser-voice fallback still runs.
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';

let synthMode = 'stuck';   // stuck (never starts) | ok
const spoken = [];
const ss = {
  speaking: false, pending: false, paused: false,
  getVoices: () => [{ name: 'Google Tiếng Việt', lang: 'vi-VN' }],
  addEventListener() {},
  speak(u) {
    spoken.push(u.text);
    if (synthMode === 'stuck') return;
    this.speaking = true;
    setTimeout(() => { u.onstart?.(); setTimeout(() => { this.speaking = false; u.onend?.(); }, 10); }, 5);
  },
  cancel() { this.speaking = false; }, pause() {}, resume() {},
};
const audioSrc = [];
class FakeAudio {   // Edge stream that never starts playing
  constructor() { this.paused = true; this.ended = false; this.currentTime = 0; }
  set src(v) { audioSrc.push(v); this._s = v; }
  get src() { return this._s || ''; }
  get currentSrc() { return this.src; }
  play() { this.paused = false; return new Promise(() => {}); }
  pause() { this.paused = true; }
}

let tts;
beforeAll(async () => {
  vi.stubGlobal('window', { speechSynthesis: ss, location: { search: '' } });
  vi.stubGlobal('navigator', { userAgent: 'Android' });
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(t) { this.text = t; } });
  vi.stubGlobal('Audio', FakeAudio);
  vi.resetModules();
  tts = await import('../../src/services/tts.js');
});
afterEach(() => { vi.useRealTimers(); });
afterAll(() => { vi.unstubAllGlobals(); });

describe('tts.js: no second browser-voice attempt after both voices failed', () => {
  it('browser voice stuck + Edge never starts -> settles at ~12.5s, browser voice tried once', async () => {
    vi.useFakeTimers();
    synthMode = 'stuck'; spoken.length = 0; audioSrc.length = 0;
    tts.setTtsEngine('browser');
    let settled = false;
    const p = tts.speak('Xin chào.').then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(2600);
    expect(audioSrc.some((s) => s.includes('tts_stream'))).toBe(true);   // went to Edge
    await vi.advanceTimersByTimeAsync(9800);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(300);
    expect(settled).toBe(true);
    expect(spoken).toEqual(['Xin chào.']);        // exactly ONE browser attempt
    await p;
  });

  it('engine=edge, stream never starts -> still falls back to the browser voice once', async () => {
    vi.useFakeTimers();
    synthMode = 'ok'; spoken.length = 0;
    tts.setTtsEngine('edge');
    let settled = false;
    const p = tts.speak('Tài xế đã tới.').then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(10500);
    expect(spoken).toEqual(['Tài xế đã tới.']);
    expect(settled).toBe(true);
    await p;
  });
});

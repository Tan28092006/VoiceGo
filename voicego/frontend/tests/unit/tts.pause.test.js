// tts.js emulated pause/resume of the browser voice + the timeline of words actually
// played (used by cancelEcho to know which words can be echo). Fake speechSynthesis
// that reads word by word (20ms/word) and fires boundary events.
// Sequential tests sharing one fresh tts.js module.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

const spoken = [];
let queue = [];
let boundaries = true;
const ss = {
  speaking: false, pending: false, paused: false,
  getVoices: () => [{ name: 'Google Tiếng Việt', lang: 'vi-VN' }],
  addEventListener() {},
  speak(u) { spoken.push(u.text); queue.push(u); if (queue.length === 1) this._next(); },
  _next() {
    const u = queue[0];
    if (!u) { this.speaking = false; return; }
    this.speaking = true;
    setTimeout(() => {
      if (queue[0] !== u) return;
      u.onstart?.();
      const words = [...u.text.matchAll(/\S+/g)];
      let k = 0;
      const tick = () => {
        if (queue[0] !== u) return;
        if (k < words.length) {
          if (boundaries) u.onboundary?.({ name: 'word', charIndex: words[k].index });
          k++; setTimeout(tick, 20); return;
        }
        queue.shift(); u.onend?.(); this._next();
      };
      tick();
    }, 5);
  },
  cancel() { const q = queue; queue = []; this.speaking = false; setTimeout(() => q.forEach((u) => u.onerror?.({ error: 'interrupted' })), 1); },
  pause() {}, resume() {},
};
class FakeAudio { constructor() { this.paused = true; this.ended = false; } play() { return Promise.resolve(); } pause() {} }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TEXT = 'Giá khoảng ba mươi nghìn đồng. Tài xế sẽ tới trong năm phút nữa nhé.';

let tts;
beforeAll(async () => {
  vi.stubGlobal('window', { speechSynthesis: ss, location: { search: '' } });
  vi.stubGlobal('navigator', { userAgent: 'Android' });
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(t) { this.text = t; } });
  vi.stubGlobal('Audio', FakeAudio);
  vi.resetModules();
  tts = await import('../../src/services/tts.js');
});
afterAll(() => { vi.unstubAllGlobals(); });

describe('tts.js pause/resume + spoken-word timeline (sequential)', () => {
  it('pause keeps speak() pending, records words, resume continues from the current word', async () => {
    let done = false;
    const p = tts.speak(TEXT).then(() => { done = true; });
    await sleep(5 + 20 * 3 + 5); // ~3 words into sentence 1
    expect(tts.pauseSpeech()).toBe(true);
    expect(tts.isSpeaking()).toBe(false);
    await sleep(60);
    expect(done).toBe(false); // PIN chain must keep waiting while paused
    const heard = tts.spokenWordsBetween(0, performance.now());
    expect(heard.length).toBeGreaterThanOrEqual(2);
    expect(heard.length).toBeLessThanOrEqual(5);
    spoken.length = 0;
    tts.resumeSpeech();
    await sleep(20);
    expect(spoken[0]).toBeTruthy();
    expect(spoken[0].startsWith('Giá')).toBe(false);
    expect(TEXT.includes(spoken[0])).toBe(true);
    await p;
    expect(done).toBe(true);
  });

  it('stop() while paused resolves speak(); resume after stop is a no-op', async () => {
    let done = false;
    tts.speak(TEXT).then(() => { done = true; });
    await sleep(40); tts.pauseSpeech(); await sleep(20); tts.stop();
    await sleep(5);
    expect(done).toBe(true);
    spoken.length = 0;
    tts.resumeSpeech();
    expect(spoken).toHaveLength(0);
  });

  it('timeline window returns only the last words spoken', async () => {
    await tts.speak('Một hai ba bốn năm. Sáu bảy tám chín mười.');
    const end = performance.now();
    const recent = tts.spokenWordsBetween(end - 60, end);
    expect(recent.length).toBeGreaterThan(0);
    expect(recent.length).toBeLessThanOrEqual(5);
    expect(recent).not.toContain('Một');
  });

  it('no boundary events (some engines) -> resume from the start of the current sentence', async () => {
    boundaries = false; spoken.length = 0;
    const p = tts.speak(TEXT);
    await sleep(50); tts.pauseSpeech(); await sleep(10);
    spoken.length = 0;
    tts.resumeSpeech();
    await sleep(10);
    expect(['Giá khoảng ba mươi nghìn đồng.', 'Tài xế sẽ tới trong năm phút nữa nhé.']).toContain(spoken[0]);
    await p;
  });
});

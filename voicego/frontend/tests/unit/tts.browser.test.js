// tts.js with the BROWSER voice (speechSynthesis) and its Edge fallback (<audio> ->
// /api/voice/tts_stream). Fake speechSynthesis + Audio, controllable per test.
//
// tts.js keeps module-level state (engine, chosen voice, current utterance), so the
// module is imported fresh for this file and the tests below run IN ORDER and share it.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

let mode = 'ok'; // ok | stuck (never starts) | noend (starts, never ends)
let voices = [{ name: 'Google Tiếng Việt', lang: 'vi-VN' }];
const spoken = [];
let queue = [];
const ss = {
  speaking: false, pending: false, paused: false,
  getVoices: () => voices,
  addEventListener(ev, fn) { this._vc = fn; },
  speak(u) { spoken.push(u.text); queue.push(u); if (queue.length === 1) this._next(); },
  _next() {
    const u = queue[0];
    if (!u) { this.speaking = false; return; }
    if (mode === 'stuck') return;
    this.speaking = true;
    setTimeout(() => {
      if (queue[0] !== u) return;
      u.onstart?.();
      if (mode === 'noend') return;
      setTimeout(() => { if (queue[0] !== u) return; queue.shift(); u.onend?.(); this._next(); }, 30);
    }, 10);
  },
  cancel() { const q = queue; queue = []; this.speaking = false; q.forEach((u) => u.onerror?.({ error: 'interrupted' })); },
  pause() { this.paused = true; },
  resume() { this.paused = false; },
};
let audioSrc = [];
class FakeAudio {
  constructor() { this.paused = true; this.ended = false; }
  set src(v) { audioSrc.push(v); this._s = v; }
  get src() { return this._s || ''; }
  get currentSrc() { return this.src; }
  play() {
    this.paused = false;
    setTimeout(() => { this.onplaying?.(); setTimeout(() => { this.paused = true; this.ended = true; this.onended?.(); }, 20); }, 5);
    return Promise.resolve();
  }
  pause() { this.paused = true; }
}
const reset = () => { spoken.length = 0; queue = []; audioSrc = []; ss.speaking = false; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let tts;
beforeAll(async () => {
  vi.stubGlobal('window', { speechSynthesis: ss, location: { search: '' } });
  vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/140' });
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(t) { this.text = t; } });
  vi.stubGlobal('Audio', FakeAudio);
  vi.resetModules();
  tts = await import('../../src/services/tts.js');
});
afterAll(() => { vi.unstubAllGlobals(); });

describe('tts.js browser voice (sequential, shared module state)', () => {
  it('chunks by sentence, onStart once, resolves at the end, no Edge request', async () => {
    reset(); mode = 'ok';
    let starts = 0;
    const t = Date.now();
    await tts.speak('Đã đặt xe. Đang tìm tài xế cho bạn, vui lòng chờ. Cảm ơn!', { onStart: () => starts++ });
    expect(spoken).toHaveLength(3);
    expect(starts).toBe(1);
    expect(audioSrc).toHaveLength(0);
    expect(Date.now() - t).toBeLessThan(1000);
  });

  it('splits a long sentence at commas (<=180 chars, Chrome ~15s cutoff) without losing text', async () => {
    reset();
    const long = Array.from({ length: 12 }, (_, i) => `đoạn số ${i} của một câu rất dài để thử`).join(', ') + '.';
    await tts.speak(long);
    expect(spoken.length).toBeGreaterThan(1);
    expect(spoken.every((p) => p.length <= 180)).toBe(true);
    expect(spoken.join(' ').replace(/\s+/g, ' ')).toBe(long);
  });

  it('isSpeaking() is true while reading; stop() resolves the pending speak (PIN chain must not hang)', async () => {
    reset(); mode = 'noend';
    const p = tts.speak('Xin chào bạn.');
    await sleep(30);
    expect(tts.isSpeaking()).toBe(true);
    tts.stop();
    const t = Date.now();
    await p;
    expect(Date.now() - t).toBeLessThan(100);
    expect(tts.isSpeaking()).toBe(false);
  });

  it('stuck engine (speak swallowed) -> falls back to Edge after ~2.5s, onStart still fires', async () => {
    reset(); mode = 'stuck';
    let starts = 0;
    await tts.speak('Xin chào.', { onStart: () => starts++ });
    expect(audioSrc.some((s) => s.includes('tts_stream'))).toBe(true);
    expect(starts).toBe(1);
  });

  it('no Vietnamese voice -> straight to Edge (no English voice reading Vietnamese)', async () => {
    reset(); mode = 'ok';
    voices = [{ name: 'Google US English', lang: 'en-US' }];
    ss._vc();
    await tts.speak('Xin chào.');
    expect(audioSrc).toHaveLength(1);
    expect(spoken).toHaveLength(0);
  });

  it('engine=edge -> Edge even with a vi voice', async () => {
    reset();
    voices = [{ name: 'Google Tiếng Việt', lang: 'vi-VN' }];
    ss._vc();
    tts.setTtsEngine('edge');
    await tts.speak('Xin chào.');
    expect(audioSrc).toHaveLength(1);
    expect(spoken).toHaveLength(0);
  });

  it('a new speak() while reading -> old one resolves, only the new one plays', async () => {
    tts.setTtsEngine('browser'); reset(); mode = 'noend';
    const a = tts.speak('Câu thứ nhất.');
    await sleep(30);
    mode = 'ok';
    const b = tts.speak('Câu thứ hai.');
    await a; await b;
    expect(spoken.at(-1)).toBe('Câu thứ hai.');
  });
});

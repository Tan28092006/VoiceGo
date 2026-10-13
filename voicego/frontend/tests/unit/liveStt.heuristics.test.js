// Pure heuristics of the Gemini Live STT branch (src/services/liveStt.js):
//  - silenceMsFor(): how long a silence ends the turn, chosen from the words heard so far
//  - cancelEcho()/isBargeIn(): strip the AI's own voice (echo) from a transcript
//  - LiveStt.cancel() during finish() must resolve at once (double tap / mic off)
// No browser globals and no network are needed.
import fs from 'node:fs';
import { describe, it, expect } from 'vitest';
import LiveStt, { silenceMsFor, cancelEcho, isBargeIn } from '../../src/services/liveStt.js';

describe('silenceMsFor', () => {
  it('no text yet -> default wait', () => {
    expect(silenceMsFor('')).toBe(950);
  });
  it('complete sentence (ends with ".") -> short wait', () => {
    expect(silenceMsFor('Cho mình đặt xe máy đi chợ Bến Thành nhé.')).toBe(550);
  });
  it.each([
    ['hanging "đi tới"', 'cho mình đi tới'],
    ['filler "Ừm"', 'Ừm'],
    ['hanging "Đại học"', 'đi Đại học'],
  ])('%s -> long wait', (_name, text) => {
    expect(silenceMsFor(text)).toBe(1600);
  });
  it('plain phrase -> medium wait', () => {
    expect(silenceMsFor('đi Landmark 81')).toBe(800);
  });
});

describe('cancelEcho / isBargeIn', () => {
  // Real Gemini transcripts of: AI sentence played into the mic (echo only), and the
  // same echo with the user speaking over it. Generated with edge-tts audio mixed at
  // gain 0.35 / 0.2, transcribed by gemini-3.5-transcribe-live (see 48e3769).
  const mix = JSON.parse(fs.readFileSync(new URL('../fixtures/gemini_echo_mix.json', import.meta.url), 'utf8'));
  const W = (s) => s.split(/\s+/);
  const aiWords = W(mix.ai);

  it('[gemini] echo only (with "30.000" / "5 phút") -> nothing left, not a barge-in', () => {
    const r = cancelEcho(mix.res['echo_only_g0.35'], aiWords);
    expect(r.kept).toBe(0);
    expect(isBargeIn(r)).toBe(false);
  });
  it('[gemini] echo + user -> the user words are kept', () => {
    const r = cancelEcho(mix.res['echo_g0.35+user@3.0s'], aiWords);
    expect(r.text).toMatch(/thôi đổi sang ô tô đi/i);
    expect(isBargeIn(r)).toBe(true);
  });
  it('[gemini] echo misheard as "30 đô la" -> not a barge-in', () => {
    const r = cancelEcho(mix.res['echo_g0.2+user@3.0s'], aiWords);
    expect(isBargeIn(r)).toBe(false);
  });

  // Windowed: only words the AI spoke recently count as echo.
  it('answer "ô tô" right after "...hay ô tô?" is kept', () => {
    const r = cancelEcho('ô tô', W('Bạn muốn đi xe máy hay ô tô?'));
    expect(r.text).toBe('ô tô');
    expect(isBargeIn(r)).toBe(true);
  });
  it('3-word answer equal to the echo window -> removed (the window is the guard)', () => {
    expect(cancelEcho('đi xe máy', W('đi xe máy hay ô tô')).kept).toBe(0);
  });
  it('"Không." during AI speech is a barge-in', () => {
    expect(isBargeIn(cancelEcho('Không.', W('giá khoảng ba mươi nghìn đồng')))).toBe(true);
  });
  it('misheard echo + stray word -> not a barge-in', () => {
    const r = cancelEcho('giá khoảng ba mười nghìn đồng xẻ', W('Giá khoảng ba mươi nghìn đồng, tài xế sẽ'));
    expect(isBargeIn(r)).toBe(false);
  });
  it('echo then "thôi dừng lại" -> barge-in with the user words', () => {
    const r = cancelEcho('tài xế sẻ tới thôi dừng lại', W('tài xế sẽ tới trong năm phút'));
    expect(isBargeIn(r)).toBe(true);
    expect(r.text).toMatch(/thôi dừng lại/);
  });
  it('no echo window -> transcript untouched', () => {
    const r = cancelEcho('cho mình đi Landmark 81', []);
    expect(r.text).toBe('cho mình đi Landmark 81');
    expect(r.removed).toBe(0);
  });
  it('filler alone is not a barge-in', () => {
    expect(isBargeIn(cancelEcho('ừm', W('xin chào')))).toBe(false);
  });
});

describe('LiveStt.cancel', () => {
  it('cancel() during finish() resolves fast with empty, non-failed text', async () => {
    const l = new LiveStt();
    l.ws = { send() {}, close() {} };
    l.ready = true;
    l.begin();
    l.sawActivity = true; // server still hearing speech
    l.active = true;
    const t = Date.now();
    const p = l.finish(5000);
    setTimeout(() => l.cancel(), 50); // double tap / mic off mid-finish
    const r = await p;
    expect(Date.now() - t).toBeLessThan(500);
    expect(r).toMatchObject({ text: '', failed: false });
  });
});

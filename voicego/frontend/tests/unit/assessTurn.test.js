// Regression (Agent A, task A4): the single turn-decision function assessTurn(evidence, phase)
// + bargeTimeout + explainedByWindow (liveStt.js), on cases taken from Agent D's live Gemini
// runs (eval/live/runs) and echo dataset (eval/datasets/echo_cases.json):
//  - B1: a 1-2 word echo interim ("tài xế", "Quận 1", "cây số") must NOT confirm a barge-in
//  - real barge-ins still confirm on interims; finals keep the isBargeIn rule ("ô tô")
//  - B2: an answer that repeats 3+ of the AI's words is not stripped
//  - B6: silenceMsFor — short answer with a period waits 800, "đi chợ." is not 1600
import { describe, it, expect } from 'vitest';
import { assessTurn, bargeTimeout, explainedByWindow, cancelEcho, silenceMsFor } from '../../src/services/liveStt.js';

const W = (s) => s.split(/\s+/);
const ev = (text, echo, more = {}) => ({ text, echoWords: W(echo), aiSpeakingAtStart: true, hasFinal: false,
  interimPending: true, serverActive: true, serverHeardSpeech: true, localVoice: true, ...more });

describe('assessTurn — interim (AI paused, waiting for confirmation)', () => {
  it('B1: short echo interims are explained by the AI window -> uncertain, not user', () => {
    // dev echo_p_g03_A1 / A2, echo_p_g07_A2, holdout echo_p_g03_H1 (were false barges @445-1010ms)
    for (const [text, echo] of [
      ['tài xế', 'xế sẽ tới.'.replace('xế', 'Tài xế')],
      ['Quận 1', 'chợ Bến Thành ở quận 1, cách bạn'],
      ['cây số', 'khoảng hai cây số. Bạn có muốn'],
      ['bệnh viện', 'tới bệnh viện Chợ Rẫy cho bạn'],
    ]) {
      const a = assessTurn(ev(text, echo), 'interim');
      expect(a.verdict, text).toBe('uncertain');
      expect(a.reason).toBe('interim-explained-by-ai');
    }
  });
  it('real barge-in words not in the AI window confirm on an interim', () => {
    const a = assessTurn(ev('Tôi đổi sang', 'xế sẽ tới trong năm phút.'), 'interim');
    expect(a.verdict).toBe('user');
    expect(assessTurn(ev('Khoan.', 'bệnh viện Chợ Rẫy để chỉ cho bạn nhé.'), 'interim').verdict).toBe('user');
  });
  it('echo leading + user words after it -> user, with the echo removed', () => {
    const a = assessTurn(ev('Tài xế sẽ tới trong năm phút. Thôi dừng lại', 'Tài xế sẽ tới trong năm phút.'), 'interim');
    expect(a.verdict).toBe('user');
    expect(a.userText).toBe('Thôi dừng lại');
  });
  it('final segment that is entirely echo, server and mic quiet -> echo (fast false alarm)', () => {
    const e = ev('Tài xế sẽ tới.', 'Tài xế sẽ tới.', { hasFinal: true, interimPending: false, serverActive: false, localVoice: false });
    expect(assessTurn(e, 'interim')).toMatchObject({ verdict: 'echo', reason: 'interim-echo-final' });
    // ...but not while the mic still hears a voice, or the server still hears speech
    expect(assessTurn({ ...e, localVoice: true }, 'interim').verdict).toBe('uncertain');
    expect(assessTurn({ ...e, serverActive: true }, 'interim').verdict).toBe('uncertain');
  });
});

describe('assessTurn — final (end-of-turn text)', () => {
  it('"ô tô" right after "...hay ô tô?" is the user (final rule = isBargeIn)', () => {
    const a = assessTurn(ev('ô tô', 'Bạn muốn đi xe máy hay ô tô?'), 'final');
    expect(a).toMatchObject({ verdict: 'user', userText: 'ô tô' });
  });
  it('echo-only final -> echo, empty user text', () => {
    expect(assessTurn(ev('Tài xế sẽ tới.', 'Tài xế sẽ tới.'), 'final')).toMatchObject({ verdict: 'echo', userText: '', reason: 'final-echo' });
  });
  it('B2: answer repeating 3 AI words mid-sentence is kept (live after_g035_A2)', () => {
    const a = assessTurn(ev('Có, đặt xe tới đó đi.', 'xe tới đó không?'), 'final');
    expect(a.userText).toBe('Có, đặt xe tới đó đi.');
  });
  it('B2: AI silent at turn start -> only >=4-unit leading echo is stripped', () => {
    const quiet = { aiSpeakingAtStart: false };
    expect(assessTurn(ev('đi xe máy', 'Bạn muốn đi xe máy hay ô tô?', quiet), 'final').userText).toBe('đi xe máy');
    expect(assessTurn(ev('Đúng rồi, Đại học Bách Khoa', 'Bạn đang ở gần trường Đại học Bách Khoa, đúng không?', quiet), 'final').userText)
      .toBe('Đúng rồi, Đại học Bách Khoa');
    expect(assessTurn(ev('Chợ Bến Thành', 'chợ Bến Thành ở quận 1, cách bạn khoảng hai cây số.', quiet), 'final').userText).toBe('Chợ Bến Thành');
    // a long echo tail at the START is still removed
    expect(assessTurn(ev('với giá hai mươi lăm nghìn đồng nhé xác nhận', 'tới Landmark 81 với giá hai mươi lăm nghìn đồng nhé?', quiet), 'final').userText)
      .toBe('xác nhận');
  });
});

describe('bargeTimeout', () => {
  const base = { text: '', echoWords: [], aiSpeakingAtStart: true, serverHeardSpeech: true };
  it('session lost -> hard-stop; server still hearing speech -> extend once; else discard', () => {
    expect(bargeTimeout({ ...base, sessionLost: true }, false)).toBe('hard-stop');
    expect(bargeTimeout({ ...base, serverActive: true }, false)).toBe('extend');
    expect(bargeTimeout({ ...base, serverActive: true }, true)).toBe('discard');
    expect(bargeTimeout({ ...base, serverActive: false }, false)).toBe('discard');
  });
});

describe('explainedByWindow / cancelEcho opts', () => {
  it('contiguous residue inside the window is explained; non-contiguous is not', () => {
    expect(explainedByWindow('tài xế', W('Tài xế sẽ tới.'))).toBe(true);
    expect(explainedByWindow('30.000 đồng', W('giá ba mươi nghìn đồng nhé'))).toBe(true);   // numbers = one unit
    expect(explainedByWindow('tài tới', W('Tài xế sẽ tới.'))).toBe(false);
    expect(explainedByWindow('ừm', W('Tài xế'))).toBe(true);                                 // fillers only
  });
  it('default cancelEcho behaviour is unchanged (opts are opt-in)', () => {
    expect(cancelEcho('Có, đặt xe tới đó đi.', W('xe tới đó không?')).text).toBe('Có, đặt đi.');
    expect(cancelEcho('Có, đặt xe tới đó đi.', W('xe tới đó không?'), { leadingOnly: true }).text).toBe('Có, đặt xe tới đó đi.');
  });
  it('leadingOnly keeps removing an echo split into consecutive runs (Gemini dropped words)', () => {
    const r = cancelEcho('Xin lỗi mình chưa nghe rõ, bạn nói lại giúp mình được không?',
      W('Xin lỗi, mình chưa nghe rõ. Bạn nói lại điểm đến giúp mình được không?'), { leadingOnly: true });
    expect(r.kept).toBe(0);
  });
});

describe('silenceMsFor — B6', () => {
  it('a short answer with a period waits 800 (Gemini puts periods on fragments)', () => {
    for (const t of ['Không.', 'Có.', 'Được.', 'Được rồi.']) expect(silenceMsFor(t), t).toBe(800);
  });
  it('a full sentence with a period still cuts at 550', () => {
    expect(silenceMsFor('Cho mình đặt xe máy đi chợ Bến Thành nhé.')).toBe(550);
    expect(silenceMsFor('Không, mình muốn đi Landmark 81.')).toBe(550);
  });
  it('noun/direction endings with a period are complete, not hanging', () => {
    for (const t of ['Cho mình đi chợ.', 'Cho mình đặt xe.', 'Mình muốn đi bệnh viện.', 'Mình muốn đi ra.']) expect(silenceMsFor(t), t).toBe(550);
    expect(silenceMsFor('Ừ')).toBe(800);
  });
  it('function-word endings still wait 1600, with or without a period', () => {
    for (const t of ['cho mình đi tới', 'Mình muốn đi.', 'Ừm', 'đi Đại học', 'Đi tới bệnh viện Chợ']) expect(silenceMsFor(t), t).toBe(1600);
  });
});

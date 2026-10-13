// Streaming agent reply (Agent B), no network and no real browser:
//  - createSseParser(): SSE framing from /api/agent/chat_stream, split at any byte
//  - runAgentTurn(): first sentence spoken before the reply is done, ui applied once,
//    fallback to /api/agent/chat, interrupt policy for the conversation history
//  - createSpeechQueue() in tts.js over a fake speechSynthesis: order, coalescing,
//    stop() / a foreign speak() closes the queue, pause does not.
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest';
import { createSseParser, runAgentTurn, interruptedMessages } from '../../src/services/api.js';

const sse = (type, data) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const until = async (fn) => { for (let k = 0; k < 500 && !fn(); k++) await tick(1); expect(fn()).toBeTruthy(); };

describe('createSseParser', () => {
  it('parses events split at arbitrary points, ignores comments, keeps unicode', () => {
    const wire = ': stream\n\n' + sse('sentence', { i: 0, text: 'Được rồi.' })
      + sse('done', { reply: 'Được rồi.', messages: [], ui: {} });
    for (let cut = 1; cut < wire.length; cut += 7) {
      const p = createSseParser();
      const evs = [...p.feed(wire.slice(0, cut)), ...p.feed(wire.slice(cut))];
      expect(evs.map((e) => e.type)).toEqual(['sentence', 'done']);
      expect(evs[0].data.text).toBe('Được rồi.');
    }
  });
  it('accepts CRLF framing', () => {
    const p = createSseParser();
    expect(p.feed('event: tools\r\ndata: {"ui":{}}\r\n\r\n')).toEqual([{ type: 'tools', data: { ui: {} } }]);
  });
});

// Fake speech queue with the same surface as tts.createSpeechQueue.
function fakeQueueFactory() {
  const queues = [];
  const create = ({ onFirstStart } = {}) => {
    let resolve;
    const q = { items: [], spoken: [], closed: false, ended: false, result: null, onFirstStart };
    q.drained = new Promise((r) => { resolve = r; });
    q.push = (t) => { q.items.push(t); if (q.items.length === 1) onFirstStart?.(); return true; };
    q.end = () => { q.ended = true; };
    q.close = (interrupted) => {
      if (q.closed) return;
      q.closed = true;
      q.result = { interrupted, spoken: q.spoken.slice(), partial: interrupted ? 'Bạn xác' : '' };
      resolve(q.result);
    };
    q.cancel = () => q.close(true);
    q.finishAll = () => { q.spoken.push(...q.items); q.close(false); };
    queues.push(q);
    return q;
  };
  return { create, queues };
}

// Scripted SSE stream: emits events with awaits in between, like the real server.
function scriptedStream(script, { failAt = -1 } = {}) {
  return async (messages, pickup, { signal, onEvent }) => {
    for (let k = 0; k < script.length; k++) {
      await tick(1);
      if (signal.aborted) throw new DOMException('aborted', 'AbortError');
      if (k === failAt) throw new Error('network');
      const [type, data] = script[k];
      if (type === 'done') return data;
      onEvent(type, data);
    }
    throw new Error('no done');
  };
}

const USER = [{ role: 'user', content: 'đi xe máy' }];
const CKPT = {
  messages: [{ role: 'system', content: 'S' }, ...USER,
    { role: 'assistant', content: '', tool_calls: [{ id: 'c1', type: 'function', function: { name: 'get_quote', arguments: '{}' } }] },
    { role: 'tool', tool_call_id: 'c1', content: '{"ok":true,"kind":"quote"}' }],
  ui: { quote: { priceVnd: 92000 } },
};
const S1 = 'Từ chỗ bạn tới Chợ Bến Thành khoảng 20 ki-lô-mét, giá 92 nghìn đồng bằng xe máy.';
const S2 = 'Bạn xác nhận đặt xe nhé?';
const DONE = { reply: `${S1} ${S2}`, messages: [...CKPT.messages, { role: 'assistant', content: `${S1} ${S2}` }], ui: CKPT.ui };
const SCRIPT = [['tools', CKPT], ['sentence', { i: 0, text: S1 }], ['sentence', { i: 1, text: S2 }], ['done', DONE]];

describe('runAgentTurn', () => {
  it('speaks the first sentence before the reply is complete; ui applied once from the checkpoint', async () => {
    const fq = fakeQueueFactory();
    const seen = [];
    const onFirstSentence = vi.fn(() => true);
    const turn = runAgentTurn(USER, null, {
      createQueue: fq.create, onFirstSentence,
      onSentence: (s, first) => seen.push([s, first]),
      onFirstStart: () => seen.push(['<sound>']),
      stream: scriptedStream(SCRIPT), fallback: () => { throw new Error('must not fall back'); },
    });
    let finished = false;
    turn.result.then(() => { finished = true; });
    await until(() => fq.queues.length === 1);   // tools + first sentence delivered...
    expect(finished).toBe(false);                 // ...while the reply is still streaming
    expect(onFirstSentence).toHaveBeenCalledWith(CKPT.ui);
    expect(fq.queues).toHaveLength(1);
    expect(fq.queues[0].items[0]).toBe(S1);
    const result = await turn.result;
    expect(onFirstSentence).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([[S1, true], ['<sound>'], [S2, false]]);
    expect(fq.queues[0].items).toEqual([S1, S2]);
    expect(fq.queues[0].ended).toBe(true);            // q.end() after 'done'
    expect(result).toMatchObject({ reply: DONE.reply, messages: DONE.messages, uiApplied: true, streamed: true });
    fq.queues[0].finishAll();
    expect(await turn.speech).toMatchObject({ interrupted: false });
  });

  it('booked checkpoint -> onFirstSentence returns false -> no sentence is spoken', async () => {
    const fq = fakeQueueFactory();
    const turn = runAgentTurn(USER, null, {
      createQueue: fq.create, onFirstSentence: () => false, stream: scriptedStream(SCRIPT),
    });
    const r = await turn.result;
    expect(fq.queues).toHaveLength(0);
    expect(turn.speech).toBe(null);
    expect(r.uiApplied).toBe(true);
  });

  it('stream fails before any sentence -> /api/agent/chat from the tool checkpoint (no tool re-run)', async () => {
    const fallback = vi.fn(async () => ({ reply: 'ok', messages: ['x'], ui: { booked: { ok: true } } }));
    const turn = runAgentTurn(USER, { lat: 1, lng: 2 }, {
      createQueue: fakeQueueFactory().create, stream: scriptedStream(SCRIPT, { failAt: 1 }), fallback,
    });
    const r = await turn.result;
    expect(fallback).toHaveBeenCalledWith(CKPT.messages, { lat: 1, lng: 2 });
    expect(r).toMatchObject({ legacy: true, uiApplied: false, reply: 'ok' });
    expect(r.ui).toEqual({ quote: { priceVnd: 92000 }, booked: { ok: true } });   // ui of both halves
  });

  it('stream fails before anything -> fallback with the original messages', async () => {
    const fallback = vi.fn(async () => ({ reply: 'ok', messages: [], ui: {} }));
    await runAgentTurn(USER, null, { stream: async () => { throw new Error('HTTP 502'); }, fallback }).result;
    expect(fallback).toHaveBeenCalledWith(USER, null);
  });

  it('stream breaks after the first sentence -> keep what was received, no second request', async () => {
    const fq = fakeQueueFactory();
    const fallback = vi.fn();
    const r = await runAgentTurn(USER, null, {
      createQueue: fq.create, stream: scriptedStream(SCRIPT, { failAt: 2 }), fallback,
    }).result;
    expect(fallback).not.toHaveBeenCalled();
    expect(r.partial).toBe(true);
    expect(r.messages).toEqual([...CKPT.messages, { role: 'assistant', content: S1 }]);
    expect(fq.queues[0].ended).toBe(true);
  });

  it('barge-in mid-stream -> stop speaking, drain the stream silently, then commit checkpoint + heard part', async () => {
    const fq = fakeQueueFactory();
    let committed = null;
    let aborted = false;
    const late = [];
    const stream = async (m, p, { signal, onEvent }) => {
      signal.addEventListener('abort', () => { aborted = true; });
      onEvent('tools', { messages: USER, ui: {}, ms: 10 });
      onEvent('sentence', { i: 0, text: 'Mình đặt xe ngay nhé.' });     // a lead-in before a tool call
      fq.queues[0].spoken.push('Mình đặt xe ngay nhé.');
      fq.queues[0].close(true);           // = stop() from the barge-in
      await tick(5);
      onEvent('sentence', { i: 1, text: 'Không được đọc câu này.' });   // after the cut: never spoken
      onEvent('action', { name: 'book_ride', phase: 'start', ms: 20 });
      onEvent('tools', { ...CKPT, ui: { booked: { rideId: 'r1' } }, ms: 30 });  // the booking DID commit
      return DONE;
    };
    const turn = runAgentTurn(USER, null, {
      createQueue: fq.create, stream, onLateUi: (ui) => late.push(ui), onInterrupted: (m) => { committed = m; },
    });
    expect(await turn.result).toBe(null);
    expect(aborted).toBe(false);                                  // drained, not cut off
    expect(fq.queues[0].items).toEqual(['Mình đặt xe ngay nhé.']);  // nothing pushed after the cut
    expect(late).toEqual([{ booked: { rideId: 'r1' } }]);          // committed booking still surfaced
    expect(committed).toEqual([...CKPT.messages, { role: 'assistant', content: 'Mình đặt xe ngay nhé. Bạn xác …' }]);
    expect(turn.isCut()).toBe(true);
  });

  it('drain after a cut is bounded: a stuck stream is aborted and the last checkpoint committed', async () => {
    const fq = fakeQueueFactory();
    let committed = null;
    const stream = (m, p, { signal, onEvent }) => new Promise((resolve, reject) => {
      onEvent('tools', CKPT);
      onEvent('sentence', { i: 0, text: S1 });
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    });
    const turn = runAgentTurn(USER, null, {
      createQueue: fq.create, stream, drainMs: 20, onInterrupted: (m) => { committed = m; },
    });
    await until(() => fq.queues.length === 1);
    await turn.cut();
    expect(committed).toEqual([...CKPT.messages, { role: 'assistant', content: 'Bạn xác …' }]);
    expect(await turn.result).toBe(null);
  });

  it('cut() by a new turn resolves once the history is committed', async () => {
    const fq = fakeQueueFactory();
    let committed = null;
    const turn = runAgentTurn(USER, null, {
      createQueue: fq.create, stream: scriptedStream(SCRIPT), onInterrupted: (m) => { committed = m; },
    });
    await until(() => fq.queues.length === 1);
    await turn.cut();
    expect(committed).toEqual([...CKPT.messages, { role: 'assistant', content: 'Bạn xác …' }]);
    expect(await turn.result).toBe(null);
  });

  it('cut() after a normally finished, fully spoken turn changes nothing', async () => {
    const fq = fakeQueueFactory();
    const onInterrupted = vi.fn();
    const turn = runAgentTurn(USER, null, { createQueue: fq.create, stream: scriptedStream(SCRIPT), onInterrupted });
    await turn.result;
    fq.queues[0].finishAll();
    await tick();
    await turn.cut();
    expect(onInterrupted).not.toHaveBeenCalled();
  });

  it('duplicate sentence events (same i) are spoken once', async () => {
    const fq = fakeQueueFactory();
    const dup = [['tools', CKPT], ['sentence', { i: 0, text: S1 }], ['sentence', { i: 0, text: S1 }],
      ['sentence', { i: 1, text: S2 }], ['done', DONE]];
    await runAgentTurn(USER, null, { createQueue: fq.create, stream: scriptedStream(dup) }).result;
    expect(fq.queues[0].items).toEqual([S1, S2]);
  });

  it('stream dies after book_ride started but before its checkpoint -> resync the SAME turn (idempotent server)', async () => {
    const fallback = vi.fn(async () => ({ reply: 'Đã đặt xe.', messages: ['m'], ui: { booked: { rideId: 'r1' } } }));
    const script = [['tools', CKPT], ['action', { name: 'book_ride', phase: 'start', ms: 50 }], ['tools', CKPT]];
    const ck = { ...CKPT, ms: 40 };
    script[0] = ['tools', ck];
    const r = await runAgentTurn(USER, null, {
      createQueue: fakeQueueFactory().create, stream: scriptedStream(script, { failAt: 2 }), fallback,
    }).result;
    expect(r.resync).toBe(true);
    expect(fallback).toHaveBeenCalledWith(USER, null);       // same turn input -> same idempotency key
    expect(r.ui.booked.rideId).toBe('r1');
  });

  it('action already committed (checkpoint after it) -> plain fallback from the checkpoint', async () => {
    const fallback = vi.fn(async () => ({ reply: 'ok', messages: [], ui: {} }));
    const script = [['action', { name: 'book_ride', phase: 'start', ms: 50 }], ['tools', { ...CKPT, ms: 60 }]];
    const r = await runAgentTurn(USER, null, {
      createQueue: fakeQueueFactory().create, stream: scriptedStream(script, { failAt: 2 }), fallback,
    }).result;
    expect(r.resync).toBe(false);
    expect(fallback).toHaveBeenCalledWith(CKPT.messages, null);
  });

  it('interrupt after the stream finished replaces the full reply by the heard part', async () => {
    const fq = fakeQueueFactory();
    let committed = null;
    const turn = runAgentTurn(USER, null, {
      createQueue: fq.create, stream: scriptedStream(SCRIPT), onInterrupted: (m) => { committed = m; },
    });
    await turn.result;
    fq.queues[0].spoken.push(S1);
    fq.queues[0].close(true);
    await tick();
    expect(committed.at(-1)).toEqual({ role: 'assistant', content: `${S1} Bạn xác …` });
    expect(committed.slice(0, -1)).toEqual(CKPT.messages);
  });

  it('interruptedMessages: nothing heard still closes the turn with an assistant message', () => {
    expect(interruptedMessages(USER, '  ')).toEqual([...USER, { role: 'assistant', content: '…' }]);
  });
});

// ── createSpeechQueue over a fake speechSynthesis ────────────────────────────────
describe('createSpeechQueue (tts.js)', () => {
  let tts;
  const played = [];
  beforeAll(async () => {
    class Utt { constructor(t) { this.text = t; } }
    const ss = {
      speaking: false, pending: false, paused: false, cur: null, timers: [],
      getVoices: () => [{ lang: 'vi-VN', name: 'Google Tiếng Việt' }],
      addEventListener() {},
      speak(u) {
        const t1 = setTimeout(() => { ss.speaking = true; ss.cur = u; u.onstart?.(); played.push(u.text); }, 2);
        const t2 = setTimeout(() => { ss.speaking = false; ss.cur = null; u.onend?.(); }, 15);
        ss.timers.push(t1, t2);
      },
      cancel() {
        ss.timers.forEach(clearTimeout); ss.timers = [];
        const u = ss.cur; ss.cur = null; ss.speaking = false;
        if (u) u.onerror?.({ error: 'interrupted' });
      },
      resume() {},
    };
    vi.stubGlobal('window', { speechSynthesis: ss, location: { search: '' } });
    vi.stubGlobal('SpeechSynthesisUtterance', Utt);
    vi.stubGlobal('Audio', class { constructor() { this.paused = true; this.ended = false; } pause() { this.paused = true; } play() { return Promise.resolve(); } });
    vi.resetModules();
    tts = await import('../../src/services/tts.js');
    tts.setTtsEngine('browser');
  });
  afterAll(() => vi.unstubAllGlobals());

  it('plays items in order, coalesces what queued up meanwhile, onFirstStart once', async () => {
    played.length = 0;
    const onFirstStart = vi.fn();
    const q = tts.createSpeechQueue({ onFirstStart });
    q.push('Câu một.');
    q.push('Câu hai.');
    q.push('Câu ba.');
    q.end();
    const r = await q.drained;
    expect(r).toEqual({ interrupted: false, spoken: ['Câu một.', 'Câu hai. Câu ba.'], partial: '', unheard: [] });
    expect(played).toEqual(['Câu một.', 'Câu hai.', 'Câu ba.']);   // synth still reads per sentence
    expect(onFirstStart).toHaveBeenCalledTimes(1);
  });

  it('waits for late sentences until end(), then drains', async () => {
    const q = tts.createSpeechQueue();
    q.push('Một.');
    await tick(40);
    expect(q.closed).toBe(false);          // first item done, no end() yet -> still open
    q.push('Hai.');
    q.end();
    expect((await q.drained).spoken).toEqual(['Một.', 'Hai.']);
  });

  it('stop() closes the queue synchronously and drops queued sentences', async () => {
    played.length = 0;
    const q = tts.createSpeechQueue();
    q.push('Một.');
    q.push('Hai.');
    await tick(8);                          // "Một." is playing
    tts.stop();
    expect(q.closed).toBe(true);
    expect(q.result.interrupted).toBe(true);
    expect(q.result.spoken).toEqual([]);
    expect(q.push('Ba.')).toBe(false);
    await tick(40);
    expect(played).toEqual(['Một.']);       // nothing after the stop
  });

  it('a foreign speak() (e.g. driver arrived) interrupts the queue', async () => {
    const q = tts.createSpeechQueue();
    q.push('Một.');
    await tick(8);
    tts.speak('Tài xế đã tới.');
    expect((await q.drained).interrupted).toBe(true);
    await tick(40);
  });

  it('must-hear items (PIN) cut off by stop() are reported as unheard, not delivered', async () => {
    const q = tts.createSpeechQueue();
    q.push('Tài xế đã tới.');
    q.push('Mã PIN của bạn là 4 7 1 9.', { mustHear: true });
    await tick(8);                          // first item playing, PIN still queued
    tts.stop();
    expect(q.result.interrupted).toBe(true);
    expect(q.result.unheard).toEqual(['Mã PIN của bạn là 4 7 1 9.']);
    const q2 = tts.createSpeechQueue();
    q2.push('Mã PIN của bạn là 4 7 1 9.', { mustHear: true });
    await tick(4);                          // PIN itself playing -> cut mid-way
    tts.stop();
    expect(q2.result.unheard).toEqual(['Mã PIN của bạn là 4 7 1 9.']);
    await tick(40);
  });

  it('pauseSpeech() does not close the queue; resumeSpeech() continues it', async () => {
    const q = tts.createSpeechQueue();
    q.push('Một.');
    q.push('Hai.');
    q.end();
    await tick(8);
    expect(tts.pauseSpeech()).toBe(true);
    await tick(30);
    expect(q.closed).toBe(false);
    tts.resumeSpeech();
    const r = await q.drained;
    expect(r.interrupted).toBe(false);
    expect(r.spoken).toEqual(['Một.', 'Hai.']);
  });
});

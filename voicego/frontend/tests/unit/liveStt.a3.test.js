// Regression (Agent A, task A3) for LiveStt:
//  - a hung live-token fetch must settle ensureOpen() as false within ~5s (fake timers),
//    and a later ensureOpen() must be able to open normally (was: _opening hung forever)
//  - begin() shortens a pending drain (late final of a cancelled turn) to <= 300ms,
//    so the new turn's text is not swallowed for 2s
//  - finish() resolves with an extra `reason` field: done / maybeFinish / timeout /
//    dropped / not-ready / cancelled / idle (existing text/failed fields unchanged)
//  - onActivity(active) is called on server ACTIVITY_START/END during a turn
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';

const sockets = [];
class FakeWS {
  constructor(url) { this.url = url; this.sent = []; sockets.push(this); setTimeout(() => this.onopen?.(), 1); }
  send(s) { const m = JSON.parse(s); this.sent.push(m); if (m.setup) setTimeout(() => this._msg({ setupComplete: {} }), 1); }
  _msg(o) { this.onmessage?.({ data: JSON.stringify(o) }); }
  close() { setTimeout(() => this.onclose?.({ code: 1000, reason: '' }), 1); }
  serverDrop() { this.onclose?.({ code: 1011, reason: 'internal' }); }
}
let fetchMode = 'ok';   // ok | hang
const okFetch = async () => ({ ok: true, json: async () => ({ token: 't', model: 'm' }) });
const fetchStub = (...a) => (fetchMode === 'hang' ? new Promise(() => {}) : okFetch(...a));

let LiveStt;
beforeAll(async () => {
  vi.stubGlobal('WebSocket', FakeWS);
  vi.stubGlobal('fetch', fetchStub);
  vi.resetModules();
  ({ default: LiveStt } = await import('../../src/services/liveStt.js'));
});
afterEach(() => { vi.useRealTimers(); fetchMode = 'ok'; });
afterAll(() => { vi.unstubAllGlobals(); });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

describe('LiveStt token fetch deadline', () => {
  it('hung token fetch -> ensureOpen() resolves false within ~5s, then a later open succeeds', async () => {
    vi.useFakeTimers();
    fetchMode = 'hang';
    const l = new LiveStt();
    let res = 'pending';
    l.ensureOpen().then((ok) => { res = ok; });
    await vi.advanceTimersByTimeAsync(4900);
    expect(res).toBe('pending');
    await vi.advanceTimersByTimeAsync(200);
    expect(res).toBe(false);
    expect(l._opening).toBe(null);          // a later ensureOpen() is not stuck on the old promise
    fetchMode = 'ok';
    const p = l.ensureOpen();
    await vi.advanceTimersByTimeAsync(50);
    expect(await p).toBe(true);
    expect(l.ready).toBe(true);
    l.close();
  });
});

describe('LiveStt drain + finish reasons (real timers)', () => {
  let l, ws;
  beforeAll(async () => {
    l = new LiveStt();
    expect(await l.ensureOpen()).toBe(true);
    ws = sockets.at(-1);
  });
  afterAll(() => l.close());

  it('finish() reason=done on generationComplete', async () => {
    l.begin();
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ serverContent: { interimInputTranscription: { text: 'đi chợ' } } });
    const p = l.finish(500);
    ws._msg({ serverContent: { inputTranscription: { text: 'Đi chợ Bến Thành.' } } });
    ws._msg({ serverContent: { generationComplete: true } });
    expect(await p).toMatchObject({ text: 'Đi chợ Bến Thành.', failed: false, reason: 'done' });
  });

  it('finish() reason=maybeFinish when the server already closed the last segment', async () => {
    l.begin();
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ serverContent: { inputTranscription: { text: 'Landmark 81.' } } });
    ws._msg({ voiceActivity: { type: 'ACTIVITY_END' } });
    expect(await l.finish(500)).toMatchObject({ text: 'Landmark 81.', failed: false, reason: 'maybeFinish' });
  });

  it('finish() reason=timeout keeps the interim; then a cancelled/timeout drain is cut short by begin()', async () => {
    l.begin();
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ serverContent: { interimInputTranscription: { text: 'cho mình đi' } } });
    expect(await l.finish(100)).toMatchObject({ text: 'cho mình đi', reason: 'timeout' });
    expect(l._drainUntil).toBeGreaterThan(Date.now() + 1500);   // 2s drain armed
    // The old turn never sends generationComplete. A new turn begins right away:
    l.begin();
    expect(l._drainUntil).toBeLessThanOrEqual(Date.now() + 300);
    await sleep(350);
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ serverContent: { interimInputTranscription: { text: 'xe máy' } } });
    expect(l.text).toBe('xe máy');              // new turn's text is NOT swallowed
    const p = l.finish(500);
    ws._msg({ serverContent: { inputTranscription: { text: 'Xe máy.' } } });
    ws._msg({ serverContent: { generationComplete: true } });
    expect(await p).toMatchObject({ text: 'Xe máy.', reason: 'done' });
  });

  it('a late final of the cancelled turn inside the short drain window is still dropped', async () => {
    l.begin();
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    l.cancel();                                  // sawActivity -> 2s drain
    l.begin();                                   // new turn: drain <= now+300
    ws._msg({ serverContent: { inputTranscription: { text: 'tiếng vọng cũ' } } });   // old turn's late final
    expect(l.text).toBe('');
    l.cancel();
  });

  it('onActivity is called with the server VAD state during a turn', () => {
    const seen = [];
    l.onActivity = (a) => seen.push(a);
    l.begin();
    l._drainUntil = 0;
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ voiceActivity: { type: 'ACTIVITY_END' } });
    expect(seen).toEqual([true, false]);
    l.onActivity = null;
    l.cancel();
  });

  it('reasons: cancelled / idle / dropped', async () => {
    l.begin();
    const p = l.finish(5000);
    l.cancel();
    expect(await p).toMatchObject({ failed: false, reason: 'cancelled' });
    expect(await l.finish()).toMatchObject({ reason: 'idle' });
    l.begin();
    ws._msg({ serverContent: { interimInputTranscription: { text: 'đi' } } });
    ws.serverDrop();
    expect(await l.finish(500)).toMatchObject({ failed: true, reason: 'dropped' });
  });

  it('reason=not-ready when the session never opened during the turn', async () => {
    const l2 = new LiveStt();
    fetchMode = 'hang';
    l2.begin();                                   // starts an open that never finishes in time
    expect(await l2.finish(500)).toMatchObject({ failed: true, reason: 'not-ready' });
  });
});

// Regression (Agent A): a Gemini Live session dropping MID-TURN must make finish()
// report failed=true (the caller then sends the full WAV to Whisper) instead of
// returning the partial interim as the final transcript. Also: auto-reopen after a
// drop only for a session that lived >10s (no reopen loop). Fake WebSocket + fetch.
// Sequential tests sharing one LiveStt instance.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

const sockets = [];
class FakeWS {
  constructor(url) { this.url = url; this.sent = []; sockets.push(this); setTimeout(() => this.onopen?.(), 1); }
  send(s) { const m = JSON.parse(s); this.sent.push(m); if (m.setup) setTimeout(() => this._msg({ setupComplete: {} }), 1); }
  _msg(o) { this.onmessage?.({ data: JSON.stringify(o) }); }
  close() { setTimeout(() => this.onclose?.({ code: 1000, reason: '' }), 1); }
  serverDrop() { this.onclose?.({ code: 1011, reason: 'internal' }); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let l;
beforeAll(async () => {
  vi.stubGlobal('WebSocket', FakeWS);
  vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({ token: 't', model: 'm' }) }));
  vi.resetModules();
  const { default: LiveStt } = await import('../../src/services/liveStt.js');
  l = new LiveStt();
  expect(await l.ensureOpen()).toBeTruthy();
});
afterAll(() => { vi.unstubAllGlobals(); });

describe('LiveStt session drop (sequential)', () => {
  let ws;
  it('normal turn -> final text, failed=false', async () => {
    ws = sockets.at(-1);
    l.begin();
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ serverContent: { interimInputTranscription: { text: 'cho mình đi chợ' } } });
    const p = l.finish(500);
    ws._msg({ serverContent: { inputTranscription: { text: 'Cho mình đi chợ Bến Thành.' } } });
    ws._msg({ serverContent: { generationComplete: true } });
    expect(await p).toMatchObject({ text: 'Cho mình đi chợ Bến Thành.', failed: false });
  });

  it('drop mid-speech -> turnDropped, finish() failed=true, partial text kept as fallback', async () => {
    l.begin();
    ws._msg({ voiceActivity: { type: 'ACTIVITY_START' } });
    ws._msg({ serverContent: { interimInputTranscription: { text: 'cho mình đi' } } });
    ws.serverDrop();
    expect(l.turnDropped).toBe(true);
    const r = await l.finish(500);
    expect(r.failed).toBe(true);
    expect(r.text).toBe('cho mình đi');
  });

  it('drop of a short-lived session (<10s) -> no reopen loop', async () => {
    await sleep(700);
    expect(sockets).toHaveLength(1);
  });

  it('long-lived session drops while waiting for the final -> failed=true and reopens', async () => {
    await l.ensureOpen();
    ws = sockets.at(-1);
    l._openedAt = Date.now() - 20000;
    l.begin();
    ws._msg({ serverContent: { interimInputTranscription: { text: 'đi Landmark' } } });
    const p = l.finish(1500);
    ws.serverDrop();
    expect((await p).failed).toBe(true);
    await sleep(700);
    expect(sockets).toHaveLength(3);
    expect(l.ready).toBeTruthy();
  });

  it('next turn after a drop starts clean', () => {
    l.begin();
    expect(l.turnDropped).toBe(false);
    l.cancel();
  });

  it('close() mid-turn (STT toggle) -> that turn goes to Whisper (failed=true)', async () => {
    l.begin();
    l.close();
    expect((await l.finish(500)).failed).toBe(true);
  });
});

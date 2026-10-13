// LIVE test: drives the real liveStt.js against a running backend + real Gemini Live,
// simulating what voiceRecorder does (85ms frames of 16kHz Int16 PCM).
// Costs Gemini quota and takes ~2 min (one step idles 70s to test the keepalive).
//
// Skipped unless VITE_BACKEND_URL is set (vitest exposes it to import.meta.env):
//   cd voicego/backend && py -m uvicorn main:socket_app --port 8011     (needs GEMINI_API_KEY in .env)
//   cd voicego/frontend && VITE_BACKEND_URL=http://127.0.0.1:8011 npm run test:live
//
// Fixtures u0.pcm / u1.pcm: edge-tts (vi-VN-NamMinhNeural) -> ffmpeg s16le 16kHz mono.
//   u0 ~ "... đặt xe máy đi chợ Bến Thành ...", u1 ~ "... Đại học Công nghệ Thông tin ...".
import fs from 'node:fs';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';

const LIVE = !!process.env.VITE_BACKEND_URL;
const pcm = (n) => {
  const b = fs.readFileSync(new URL(`../fixtures/u${n}.pcm`, import.meta.url));
  return new Int16Array(b.buffer, b.byteOffset, b.length / 2);
};
const sil = (ms) => new Int16Array(16 * ms);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function stream(live, a) {
  for (let i = 0; i < a.length; i += 1365) { live.send(a.subarray(i, i + 1365)); await sleep(85); }
}

describe.skipIf(!LIVE)('LiveStt against backend + Gemini Live', () => {
  let live, silenceMsFor;
  beforeAll(async () => {
    const mod = await import('../../src/services/liveStt.js');
    silenceMsFor = mod.silenceMsFor;
    live = new mod.default();
    expect(await live.ensureOpen()).toBeTruthy();
  }, 30000);
  afterAll(() => live?.close());

  it('turn 1: normal sentence + adaptive tail', async () => {
    live.begin();
    await stream(live, pcm(0));
    await stream(live, sil(silenceMsFor(live.text)));
    const r = await live.finish();
    expect(r.failed).toBeFalsy();
    expect(r.text).toMatch(/Bến Thành/);
  }, 30000);

  it('turn 2: 1.2s mid-sentence pause -> both segments joined', async () => {
    live.begin();
    await stream(live, pcm(0)); await stream(live, sil(1200)); await stream(live, pcm(1)); await stream(live, sil(800));
    const r = await live.finish();
    expect(r.text).toMatch(/Bến Thành/);
    expect(r.text).toMatch(/Công nghệ Thông tin/);
  }, 30000);

  it('turn 3: cancelled turn does not leak into the next one', async () => {
    live.begin();
    await stream(live, pcm(0).subarray(0, 16000 * 2));
    live.cancel();
    live.begin();
    await stream(live, pcm(1)); await stream(live, sil(800));
    const r = await live.finish();
    expect(r.text).not.toMatch(/Bến Thành|chợ/);
    expect(r.text).toMatch(/Thông tin/);
  }, 30000);

  it('turn 4: silence only -> fast empty result, not failed', async () => {
    live.begin();
    await stream(live, sil(1000));
    const t = Date.now();
    const r = await live.finish();
    expect(r.text).toBe('');
    expect(r.failed).toBeFalsy();
    expect(Date.now() - t).toBeLessThan(800);
  }, 30000);

  it('turn 5: still open after 70s idle (> 60s server idle timeout, keepalive)', async () => {
    await sleep(70000);
    expect(live.ready).toBeTruthy();
    live.begin();
    await stream(live, pcm(1)); await stream(live, sil(800));
    const r = await live.finish();
    expect(r.text).toMatch(/Thông tin/);
  }, 120000);

  it('turn 6: closed session -> failed (caller falls back to Whisper) or text', async () => {
    live.close();
    live.begin(); // reconnects in background, frames queue
    await stream(live, pcm(0).subarray(0, 8000));
    const r = await live.finish();
    expect(r.failed || r.text !== '').toBe(true);
  }, 30000);
});

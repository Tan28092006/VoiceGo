// EVAL phát lại dữ liệu thô Gemini (eval/live/runs/*.json) qua CHÍNH class LiveStt
// (src/services/liveStt.js) với WebSocket giả + đồng hồ giả (vi.useFakeTimers):
//  - Các tin interim/final/generationComplete/voiceActivity được bơm vào _onMessage đúng
//    mốc ms đã ghi (tính từ lúc VAD kêu = begin()).
//  - Tại mốc audioStreamEnd đã ghi, gọi finish(1500) như app; đo finish() xong sau bao lâu,
//    vì lý do gì (done / maybeFinish / timeout ...), chữ trả về có khớp transcript không.
//  - Bản chốt về SAU khi finish() đã trả (bị bỏ / rơi vào lượt sau) -> so với drain 2s.
// Đây là phần "LiveStt finish timeout 1500ms" và "drain 2s" mà Agent A đánh dấu là hằng số
// đoán: báo p50/p95/p99 quan sát được (n nhỏ -> p99 chỉ tham khảo).
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, vi, afterAll } from 'vitest';
import LiveStt from '../../src/services/liveStt.js';
import { EVAL_DIR, quantile, table, writeResult, pct, rate } from './_lib.js';

function loadCases() {
  const dir = path.join(EVAL_DIR, 'live', 'runs');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort().flatMap((f) => {
    const d = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    return d.cases.map((c) => ({ ...c, _run: d.meta.run_id, _split: d.meta.split }));
  });
}

/** Dựng lại các tin WebSocket thô (đúng thứ tự trong cùng một ms: activity, interim, final, generationComplete). */
function messages(c) {
  const out = [];
  (c.activity || []).forEach((a) => out.push({ t: a.t_ms, o: 0, msg: { voiceActivity: { type: a.type } } }));
  (c.interims || []).forEach((x) => out.push({ t: x.t_ms, o: 1, msg: { serverContent: { interimInputTranscription: { text: x.text } } } }));
  (c.finals || []).forEach((x) => out.push({ t: x.t_ms, o: 2, msg: { serverContent: { inputTranscription: { text: x.text } } } }));
  (c.generation_complete_ms || []).forEach((t) => out.push({ t, o: 3, msg: { serverContent: { generationComplete: true } } }));
  return out.sort((a, b) => a.t - b.t || a.o - b.o);
}

async function replay(c, timeoutMs = 1500) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  vi.setSystemTime(1_000_000);
  const base = Date.now();
  const l = new LiveStt();
  l.ws = { send() {}, close() {} };
  l.ready = true;
  l.begin();
  const msgs = messages(c);
  const end = c.timing.stream_end_ms;
  let now = 0, res = null, resAt = null;
  const go = async (t) => { if (t > now) { await vi.advanceTimersByTimeAsync(t - now); now = t; } };
  let i = 0;
  for (; i < msgs.length && msgs[i].t < end; i++) { await go(msgs[i].t); l._onMessage(msgs[i].msg); }
  await go(end);
  l.finish(timeoutMs).then((r) => { res = r; resAt = Date.now() - base; });
  await Promise.resolve();
  const late = [];
  for (; i < msgs.length; i++) {
    await go(msgs[i].t);
    if (res && msgs[i].msg.serverContent?.inputTranscription) late.push(msgs[i].t - resAt);
    l._onMessage(msgs[i].msg);
    await Promise.resolve();
  }
  await go(end + timeoutMs + 100);
  vi.useRealTimers();
  return { id: c.case_id, cid: c.id, split: c._split, tail: c.tail_s, speechToDoneMs: resAt - c.clip.speech_end_ms, finishMs: resAt - end, reason: res?.reason, text: res?.text ?? null, sameText: (res?.text || '') === (c.transcript || ''), late };
}

const fmtD = (xs) => (xs.length ? `p50 ${Math.round(quantile(xs, 0.5))} | p95 ${Math.round(quantile(xs, 0.95))} | p99 ${Math.round(quantile(xs, 0.99))}${xs.length < 100 ? '*' : ''} | max ${Math.max(...xs)} (n=${xs.length})` : '— (n=0)');

describe('LiveStt.finish() — phát lại dữ liệu thô Gemini', () => {
  const cases = loadCases();
  afterAll(() => vi.useRealTimers());
  it.skipIf(!cases.length)('đo thời gian finish(), lý do, bản chốt muộn', async () => {
    const ok = cases.filter((c) => !c.error && c.timing);
    const rows = [];
    for (const c of ok) rows.push(await replay(c));
    const reasons = {};
    rows.forEach((r) => { reasons[r.reason] = (reasons[r.reason] || 0) + 1; });
    const finishMs = rows.map((r) => r.finishMs);
    const late = rows.flatMap((r) => r.late);
    table(`LiveStt.finish(1500) trên ${rows.length} lượt thật (bỏ ${cases.length - ok.length} session lỗi khỏi phép phát lại, KHÔNG khỏi báo cáo lỗi)`, ['đại lượng', 'giá trị'], [
      ['audioStreamEnd -> finish() trả (ms)', fmtD(finishMs)],
      ['lý do', Object.entries(reasons).map(([k, v]) => `${k}: ${v}`).join(', ')],
      ['chữ trả về == transcript thô', pct(rate(rows.filter((r) => r.sameText).length, rows.length))],
      ['bản chốt về SAU khi finish() trả (ms sau đó)', fmtD(late)],
      ['finish() hết hạn (timeout)', `${rows.filter((r) => r.reason === 'timeout').length}/${rows.length}`],
    ]);
    const diff = rows.filter((r) => !r.sameText);
    if (diff.length) table('Lượt có chữ trả về KHÁC transcript (thường: finish trả interim/rỗng trước bản chốt)', ['case', 'lý do', 'finish ms', 'chữ trả về'], diff.map((r) => [r.id, r.reason, r.finishMs, JSON.stringify(r.text)]));
    // Bộ T: cùng câu, đuôi im lặng 550 vs 800ms trước audioStreamEnd (paired).
    const lat = rows.filter((r) => r.split === 'latency');
    if (lat.length) {
      const by = {};
      lat.forEach((r) => { (by[r.cid.replace(/^tail0\d\d_/, '')] ||= {})[r.tail] = r.speechToDoneMs; });
      const pairs = Object.entries(by).filter(([, v]) => v[0.55] != null && v[0.8] != null);
      table('Bộ T — hết tiếng nói -> LiveStt.finish() trả chữ (ms), cùng câu, đuôi 550 vs 800 (paired)', ['câu', 'đuôi 550', 'đuôi 800', 'chênh (800-550)'],
        pairs.map(([k, v]) => [k, v[0.55], v[0.8], v[0.8] - v[0.55]]));
      table('Bộ T — phân phối', ['đuôi', 'hết tiếng -> có chữ'], [['550', fmtD(pairs.map(([, v]) => v[0.55]))], ['800', fmtD(pairs.map(([, v]) => v[0.8]))], ['chênh 800-550', fmtD(pairs.map(([, v]) => v[0.8] - v[0.55]))]]);
    }
    writeResult('livestt_replay', { n: rows.length, sessions_errored: cases.length - ok.length, reasons, finishMs, late, rows });
    expect(rows.every((r) => r.finishMs <= 1500 + 50)).toBe(true);
  });
});

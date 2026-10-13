// EVAL chốt lượt (endpointing): silenceMsFor(text) của src/services/liveStt.js quyết định
// im lặng bao lâu thì coi là NÓI XONG. Hai cái giá ngược chiều nhau:
//  - ca complete  : thời gian chờ thừa = chính silenceMs (cộng thẳng vào độ trễ cả lượt).
//  - ca incomplete: cắt sớm (tách lượt) nếu silenceMs < quãng ngừng của người dùng.
// So với các chính sách cố định (950 = nhánh Whisper, 800, 550, 1600) trên CÙNG các ca
// (paired). pause_ms trong dataset là GIẢ ĐỊNH, nên tỉ lệ cắt sớm chỉ là ước lượng tương đối.
import { describe, it, expect } from 'vitest';
import { silenceMsFor } from '../../src/services/liveStt.js';
import { loadJson, pct, rate, quantile, mean, table, writeResult } from './_lib.js';

const POLICIES = {
  'silenceMsFor (hiện tại)': silenceMsFor,
  'cố định 950 (Whisper)': () => 950,
  'cố định 800': () => 800,
  'cố định 550': () => 550,
  'cố định 1600': () => 1600,
};
const cls = (ms) => (ms <= 550 ? 'fast' : ms >= 1600 ? 'wait' : 'mid');

function evaluate(cases, fn) {
  const comp = cases.filter((c) => c.label === 'complete');
  const inc = cases.filter((c) => c.label === 'incomplete');
  const waits = comp.map((c) => fn(c.text));
  const cut = inc.filter((c) => fn(c.text) < c.pause_ms);
  return {
    nComplete: comp.length, nIncomplete: inc.length,
    waitP50: quantile(waits, 0.5), waitP95: quantile(waits, 0.95), waitMean: mean(waits),
    fastRate: rate(comp.filter((c) => fn(c.text) <= 550).length, comp.length),
    prematureCut: rate(cut.length, inc.length), cutIds: cut.map((c) => c.id),
  };
}

describe('endpoint eval — silenceMsFor', () => {
  const ds = loadJson('endpoint_cases.json');
  const summary = {};
  it('in bảng + ghi kết quả', () => {
    for (const [name, sub] of [['tất cả', ds.cases], ['real_gemini_*', ds.cases.filter((c) => c.source.startsWith('real'))], ['synthetic', ds.cases.filter((c) => c.source === 'synthetic')]]) {
      const rows = Object.entries(POLICIES).map(([p, fn]) => {
        const e = evaluate(sub, fn);
        summary[`${name}|${p}`] = e;
        return [p, `${e.waitP50} / ${e.waitP95} / ${Math.round(e.waitMean)} (n=${e.nComplete})`, pct(e.fastRate), `${pct(e.prematureCut)} (n=${e.nIncomplete})`];
      });
      table(`Endpoint — ${name}`, ['chính sách', 'chờ thừa ca complete ms p50/p95/mean', 'cắt nhanh (550)', 'cắt sớm ca incomplete'], rows);
    }
    // Ma trận: nhãn x quyết định của silenceMsFor
    const m = {};
    ds.cases.forEach((c) => { const k = `${c.label}|${cls(silenceMsFor(c.text))}`; m[k] = (m[k] || 0) + 1; });
    table('Endpoint — nhãn x quyết định silenceMsFor (fast=550, mid=800/950, wait=1600)', ['nhãn', 'fast', 'mid', 'wait'],
      ['complete', 'incomplete'].map((l) => [l, m[`${l}|fast`] || 0, m[`${l}|mid`] || 0, m[`${l}|wait`] || 0]));
    const bad = ds.cases.filter((c) => (c.label === 'complete' && silenceMsFor(c.text) >= 1600) || (c.label === 'incomplete' && silenceMsFor(c.text) < c.pause_ms));
    table('Endpoint — ca sai đáng chú ý (silenceMsFor)', ['id', 'nguồn', 'nhãn', 'text', 'ms', 'pause_ms', 'tags'],
      bad.map((c) => [c.id, c.source, c.label, JSON.stringify(c.text), silenceMsFor(c.text), c.pause_ms ?? '', c.tags.join(',')]));
    summary.bad = bad.map((c) => c.id);
    writeResult('endpoint', summary);
  });
  it('sàn hồi quy (lỏng)', () => {
    const e = evaluate(ds.cases, silenceMsFor);
    // Không được tệ hơn chính sách cố định 950 cũ ở cả hai chiều cùng lúc.
    const base = evaluate(ds.cases, () => 950);
    expect(e.waitMean <= base.waitMean || e.prematureCut <= base.prematureCut).toBe(true);
    expect(e.prematureCut).toBeLessThanOrEqual(0.6);
  });
});

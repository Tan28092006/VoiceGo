#!/usr/bin/env node
// Đọc log console trình duyệt (dán/lưu ra file) và tổng hợp các dòng `[turn] {...}` do
// src/services/turnTrace.js in ra — MỘT dòng mỗi lượt nói trên máy thật.
// In p50/p95/p99 (+ n, max) cho mọi trường thời gian (…Ms ở cấp ngoài và các mốc trong t),
// và đếm mọi trường phân loại (outcome, reason, engine, … — trường lạ cũng được đếm).
// Sách latency: chọn timeout từ phân phối đo được; p99 với n < 100 chỉ để tham khảo.
//
// Dùng:
//   node voicego/eval/turnlog_report.mjs console.log            # file log
//   node voicego/eval/turnlog_report.mjs a.log b.log --by engine
//   pbpaste | node voicego/eval/turnlog_report.mjs -            # stdin
//   node voicego/eval/turnlog_report.mjs console.log --json > turns.json
// Log có thể kèm tiền tố của DevTools (tên file:dòng, giờ) — chỉ lấy JSON sau "[turn] ".
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

/** Tách các bản ghi lượt từ văn bản log. Bỏ qua dòng hỏng nhưng ĐẾM chúng (không giấu khỏi mẫu số). */
export function parseTurnLog(text) {
  const records = [];
  let bad = 0;
  for (const line of String(text).split(/\r?\n/)) {
    const i = line.indexOf('[turn]');
    if (i < 0) continue;
    const j = line.indexOf('{', i), k = line.lastIndexOf('}');
    if (j < 0 || k < j) { bad++; continue; }
    try { records.push(JSON.parse(line.slice(j, k + 1))); } catch { bad++; }
  }
  // Trùng id + at (dán log 2 lần) -> giữ một.
  const seen = new Set();
  const uniq = records.filter((r) => { const key = `${r.id}|${r.at}`; if (seen.has(key)) return false; seen.add(key); return true; });
  return { records: uniq, bad, duplicates: records.length - uniq.length };
}

const q = (a, p) => { const i = (a.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return a[lo] + (a[hi] - a[lo]) * (i - lo); };
function dist(xs) {
  const a = xs.filter((x) => typeof x === 'number' && Number.isFinite(x)).sort((x, y) => x - y);
  if (!a.length) return null;
  return { n: a.length, p50: Math.round(q(a, 0.5)), p95: Math.round(q(a, 0.95)), p99: Math.round(q(a, 0.99)), max: a[a.length - 1], p99Reliable: a.length >= 100 };
}

const SKIP = new Set(['id', 'at', 't']);
/** Tổng hợp: phân phối thời gian + đếm phân loại. */
export function summarize(records) {
  const timings = {}, cats = {};
  for (const r of records) {
    for (const [k, v] of Object.entries(r)) {
      if (SKIP.has(k)) continue;
      if (typeof v === 'number' && /ms$/i.test(k)) (timings[k] ||= []).push(v);
      else if (typeof v === 'string' || typeof v === 'boolean') ((cats[k] ||= {})[String(v)] = (cats[k][String(v)] || 0) + 1);
      else if (typeof v === 'number') (timings[k] ||= []).push(v);   // số không đuôi Ms: vẫn báo phân phối
    }
    for (const [k, v] of Object.entries(r.t || {})) if (typeof v === 'number') (timings[`t.${k}`] ||= []).push(v);
  }
  const n = records.length;
  return {
    n,
    timings: Object.fromEntries(Object.entries(timings).map(([k, xs]) => [k, { ...dist(xs), missing: n - xs.length }])),
    categories: Object.fromEntries(Object.entries(cats).map(([k, c]) => [k, Object.fromEntries(Object.entries(c).sort((a, b) => b[1] - a[1]).map(([v, m]) => [v, { count: m, rate: m / n }]))])),
  };
}

function print(title, s) {
  const out = [`\n## ${title} — ${s.n} lượt`];
  out.push('\n| chặng / trường | n | p50 | p95 | p99 | max |', '|---|---|---|---|---|---|');
  for (const [k, d] of Object.entries(s.timings).sort()) out.push(`| ${k} | ${d.n} | ${d.p50} | ${d.p95} | ${d.p99}${d.p99Reliable ? '' : '*'} | ${d.max} |`);
  out.push('\n| trường phân loại | giá trị: số lượt (tỉ lệ trên tổng lượt) |', '|---|---|');
  for (const [k, c] of Object.entries(s.categories)) out.push(`| ${k} | ${Object.entries(c).map(([v, x]) => `${v}: ${x.count} (${(x.rate * 100).toFixed(1)}%)`).join(', ')} |`);
  out.push('\n* = n < 100: p99 chưa đáng tin, chỉ tham khảo.');
  console.log(out.join('\n'));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fs.realpathSync(process.argv[1])) {
  const args = process.argv.slice(2);
  const json = args.includes('--json');
  const byIdx = args.indexOf('--by');
  const by = byIdx >= 0 ? args[byIdx + 1] : null;
  const files = args.filter((a, i) => !a.startsWith('--') && (byIdx < 0 || i !== byIdx + 1));
  if (!files.length) { console.error('cách dùng: node turnlog_report.mjs <log...|-> [--by <trường>] [--json]'); process.exit(2); }
  const text = files.map((f) => (f === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(f, 'utf8'))).join('\n');
  const { records, bad, duplicates } = parseTurnLog(text);
  const all = summarize(records);
  const groups = by ? Object.fromEntries([...new Set(records.map((r) => String(r[by])))].map((g) => [g, summarize(records.filter((r) => String(r[by]) === g))])) : null;
  if (json) { console.log(JSON.stringify({ parsed: records.length, bad, duplicates, all, groups }, null, 1)); process.exit(0); }
  console.log(`Đọc ${records.length} dòng [turn] (hỏng: ${bad}, trùng bỏ: ${duplicates}).`);
  print('Tất cả', all);
  if (groups) for (const [g, s] of Object.entries(groups)) print(`${by} = ${g}`, s);
}

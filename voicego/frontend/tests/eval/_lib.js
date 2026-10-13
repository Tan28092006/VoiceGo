// Tiện ích chung cho bộ eval offline (tests/eval/*.test.js): tách từ để so khớp,
// đếm multiset, in bảng tóm tắt, ghi kết quả JSON kèm hash file nguồn (để so được
// giữa các revision — chương 06: ghi config/version cùng kết quả).
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FRONTEND = path.resolve(HERE, '..', '..');
export const EVAL_DIR = path.resolve(FRONTEND, '..', 'eval');
export const DATASETS = path.join(EVAL_DIR, 'datasets');

export function loadJson(name) {
  const p = path.join(DATASETS, name);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
}

/** Từ đã chuẩn hoá để CHẤM (không phải để khử vọng): thường, bỏ dấu câu, bỏ dấu thanh. */
export function tokens(s) {
  return String(s || '').toLowerCase().normalize('NFC')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean)
    .map((w) => w.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd'));
}

/** |a ∩ b| theo multiset. */
export function overlap(a, b) {
  const m = new Map();
  b.forEach((w) => m.set(w, (m.get(w) || 0) + 1));
  let n = 0;
  a.forEach((w) => { const c = m.get(w) || 0; if (c) { n++; m.set(w, c - 1); } });
  return n;
}

/** a − b theo multiset. */
export function minus(a, b) {
  const m = new Map();
  b.forEach((w) => m.set(w, (m.get(w) || 0) + 1));
  return a.filter((w) => { const c = m.get(w) || 0; if (c) { m.set(w, c - 1); return false; } return true; });
}

export const pct = (x) => (x == null || Number.isNaN(x) ? '—' : `${(x * 100).toFixed(1)}%`);
export const rate = (num, den) => (den ? num / den : null);

export function quantile(xs, q) {
  const a = xs.filter((x) => x != null && !Number.isNaN(x)).sort((p, r) => p - r);
  if (!a.length) return null;
  const i = (a.length - 1) * q;
  const lo = Math.floor(i), hi = Math.ceil(i);
  return a[lo] + (a[hi] - a[lo]) * (i - lo);
}
export const mean = (xs) => { const a = xs.filter((x) => x != null); return a.length ? a.reduce((s, x) => s + x, 0) / a.length : null; };

/** SE ≈ sqrt(p(1-p)/n) — sanity estimate theo ch06, KHÔNG phải khoảng tin cậy chặt. */
export const se = (p, n) => (n ? Math.sqrt((p * (1 - p)) / n) : null);

export function table(title, cols, rows) {
  const w = cols.map((c, i) => Math.max(String(c).length, ...rows.map((r) => String(r[i] ?? '').length)));
  const line = (r) => '| ' + r.map((v, i) => String(v ?? '').padEnd(w[i])).join(' | ') + ' |';
  const out = [`\n### ${title}`, line(cols), '|' + w.map((x) => '-'.repeat(x + 2)).join('|') + '|', ...rows.map(line)];
  console.log(out.join('\n'));
}

export function srcHashes() {
  const files = ['src/services/liveStt.js', 'src/services/voiceRecorder.js', 'src/services/tts.js', 'src/hooks/useVoiceApp.js'];
  const out = {};
  for (const f of files) {
    try { out[f] = execSync(`git hash-object "${f}"`, { cwd: FRONTEND, encoding: 'utf8' }).trim(); } catch { out[f] = null; }
  }
  try { out.head = execSync('git rev-parse --short HEAD', { cwd: FRONTEND, encoding: 'utf8' }).trim(); } catch { out.head = null; }
  return out;
}

/** Ghi voicego/eval/results/<name>.json (bản mới nhất, ghi đè) — để so giữa các lần chạy. */
export function writeResult(name, summary) {
  const dir = path.join(EVAL_DIR, 'results');
  fs.mkdirSync(dir, { recursive: true });
  const body = { eval: name, at: new Date().toISOString(), src: srcHashes(), ...summary };
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(body, null, 1));
  return body;
}

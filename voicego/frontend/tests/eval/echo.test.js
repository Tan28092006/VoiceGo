// EVAL khử tiếng vọng / chen ngang (cancelEcho + isBargeIn của src/services/liveStt.js).
//
// Hai nguồn dữ liệu, chấm và báo cáo TÁCH RIÊNG (không gộp thành một con số):
//  1. datasets/echo_cases.json — ca có nhãn (real_gemini + synthetic), chấm trên bản chốt.
//  2. eval/live/runs/*.json — dữ liệu THÔ từ Gemini thật (live_echo_eval.py). Ở đây PHÁT
//     LẠI đúng logic của useVoiceApp: mỗi interim/final gọi onText -> cancelEcho với cửa sổ
//     spokenWordsBetween(t0-800, now+300) tại THỜI ĐIỂM đó -> isBargeIn -> confirmBarge();
//     hẹn giờ BARGE_CONFIRM_MS (1500) huỷ lượt nếu chưa xác nhận; onAutoStop = hết tiếng +
//     silenceMsFor(). Chỉ số được TÍNH LẠI từ dữ liệu thô mỗi lần chạy (backfill: đổi
//     heuristic -> chấm lại trên cùng transcript thật, không gọi API).
//
// Chỉ số (chương 06: đo outcome thật, tách theo loại lỗi, không để retry che bất ổn):
//  - false-barge rate  : ca echo_only mà AI bị dừng (tự cắt lời mình).
//  - missed-barge rate : người dùng nói thật mà lượt bị bỏ (không xác nhận / text rỗng).
//  - user-word loss    : từ của người dùng CÓ trong transcript nhưng bị cancelEcho gỡ mất.
//  - echo residue      : từ vọng còn sót lại trong chữ gửi cho agent.
//  - confirm latency   : ms từ lúc VAD kêu tới lúc Gemini xác nhận (AI im chờ trong lúc này).
//  - pass@k / pass^k   : trên các clip chạy lặp.
// Biến thể ĐỀ XUẤT (V1, V1c, V2) được chốt TRƯỚC khi chạy bộ holdout H — xem RESULTS.md.
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';
import { cancelEcho, isBargeIn, silenceMsFor } from '../../src/services/liveStt.js';
import { loadJson, tokens, overlap, minus, pct, rate, quantile, table, writeResult, EVAL_DIR, se } from './_lib.js';

const W = (s) => String(s || '').split(/\s+/).filter(Boolean);

// ── Đơn vị khớp giống liveStt.units() (bản sao để kiểm "bị cửa sổ giải thích") ──
const NUM = new Set(['một', 'hai', 'ba', 'bốn', 'tư', 'năm', 'lăm', 'sáu', 'bảy', 'tám', 'chín', 'mười',
  'mươi', 'mốt', 'trăm', 'nghìn', 'ngàn', 'triệu', 'tỷ', 'tỉ', 'linh', 'lẻ']);
const fold = (w) => w.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd');
function unitKeys(text) {
  const out = [];
  for (const raw of W(text)) {
    const w = raw.toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}]/gu, '');
    if (!w) continue;
    const isNum = /^\d/.test(w) || NUM.has(w);
    if (isNum && out[out.length - 1] === '#') continue;
    out.push(isNum ? '#' : fold(w));
  }
  return out;
}
const FILL = new Set(['um', 'o', 'a', 'hmm', 'ua', 'uh']);
/** Chữ còn lại sau khử vọng có NẰM LIỀN trong cửa sổ không (tức là có thể chỉ là tiếng vọng ngắn). */
function explainedByWindow(resText, echoWords) {
  const k = unitKeys(resText).filter((x) => !FILL.has(x));
  if (!k.length) return true;
  const b = unitKeys(echoWords.join(' '));
  for (let i = 0; i + k.length <= b.length; i++) {
    if (k.every((x, j) => b[i + j] === x)) return true;
  }
  return false;
}

// ── Chính sách (policy) để so sánh ──
// cur : đúng như app hiện tại.
// V1  : ĐỀ XUẤT — interim chỉ được xác nhận chen ngang khi phần còn lại KHÔNG nằm liền
//       trong cửa sổ tiếng vọng (interim đầu của tiếng vọng chỉ 1-2 từ: "tài xế", "cây số").
//       Bản chốt cuối lượt giữ luật cũ (để "ô tô"/"xe máy" vẫn qua).
// V1c : V1 + BARGE_CONFIRM_MS 2500 (bù việc V1 xác nhận chậm hơn).
// V2  : V1 + áp luật "không nằm liền trong cửa sổ" cho cả bản chốt khi AI đang đọc.
const POLICIES = {
  cur: { confirmMs: 1500, interim: (res) => isBargeIn(res), final: (res) => isBargeIn(res) },
  V1: { confirmMs: 1500, interim: (res, win) => isBargeIn(res) && !explainedByWindow(res.text, win), final: (res) => isBargeIn(res) },
  V1c: { confirmMs: 2500, interim: (res, win) => isBargeIn(res) && !explainedByWindow(res.text, win), final: (res) => isBargeIn(res) },
  V2: { confirmMs: 1500, interim: (res, win) => isBargeIn(res) && !explainedByWindow(res.text, win), final: (res, win) => isBargeIn(res) && !explainedByWindow(res.text, win) },
};

/** Chấm từ: mất bao nhiêu từ người dùng có trong transcript, sót bao nhiêu từ vọng. */
function wordScore(transcript, delivered, expected) {
  const raw = tokens(transcript), out = tokens(delivered), exp = tokens(expected);
  const userInRaw = overlap(exp, raw);
  const userOut = overlap(exp, out);
  const echoRaw = minus(raw, exp).length;
  const echoOut = minus(out, exp).length;
  return { userInRaw, userLost: Math.max(0, userInRaw - userOut), echoRaw, echoOut, expN: exp.length };
}

function aggregate(rows) {
  const by = (l) => rows.filter((r) => r.label === l);
  const echo = by('echo_only'), user = rows.filter((r) => r.label !== 'echo_only');
  const s = (xs, f) => xs.reduce((a, x) => a + f(x), 0);
  return {
    n: rows.length,
    falseBarge: rate(echo.filter((r) => r.accepted).length, echo.length), nEcho: echo.length,
    missed: rate(user.filter((r) => !r.accepted).length, user.length), nUser: user.length,
    userWordLoss: rate(s(user, (r) => r.w.userLost), s(user, (r) => r.w.userInRaw)),
    sttWordRecall: rate(s(user, (r) => r.w.userInRaw), s(user, (r) => r.w.expN)),
    echoResidue: rate(s(rows, (r) => (r.accepted ? r.w.echoOut : 0)), s(rows, (r) => r.w.echoRaw)),
    strictPass: rate(rows.filter((r) => r.pass).length, rows.length),
  };
}

// ── 1. Dataset có nhãn, chấm trên bản chốt ──
function scoreCase(c, policy = 'cur') {
  const win = W(c.echo_text);
  const res = cancelEcho(c.transcript, win);
  const P = POLICIES[policy];
  const accepted = c.tts_active ? P.final(res, win) : res.kept > 0;
  const delivered = accepted ? res.text : '';
  const w = wordScore(c.transcript, delivered, c.expected_user);
  const pass = c.label === 'echo_only' ? !accepted : accepted && w.userLost === 0;
  return { id: c.id, source: c.source, label: c.label, tags: c.tags || [], accepted, delivered, w, pass, res };
}

// ── 2. Phát lại một ca live theo logic app ──
function replayLive(c, policy = 'cur', windowKey = 'echo_words_t') {
  const P = POLICIES[policy];
  const wt = c[windowKey] || [];
  const winAt = (t) => wt.filter(([, tt]) => tt <= t + 300).map(([w]) => w);
  const fullWin = wt.map(([w]) => w);
  // Dòng onText: interim thay đoạn đang nghe; final đẩy vào finals và xoá interim.
  const ev = [...(c.interims || []).map((x) => ({ ...x, kind: 'i' })), ...(c.finals || []).map((x) => ({ ...x, kind: 'f' }))]
    .sort((a, b) => a.t_ms - b.t_ms || (a.kind === 'i' ? -1 : 1));
  const finals = []; let interim = '';
  const texts = [];
  for (const e of ev) {
    if (e.kind === 'i') interim = e.text; else { finals.push(e.text); interim = ''; }
    texts.push({ t: e.t_ms, text: [...finals, interim].filter(Boolean).join(' ').trim() });
  }
  const textAt = (t) => { let x = ''; for (const r of texts) if (r.t <= t) x = r.text; return x; };
  const speechEnd = c.clip.speech_end_ms;
  const tAuto = speechEnd + silenceMsFor(textAt(speechEnd));      // onAutoStop (VAD hết tiếng)
  const transcript = c.transcript || '';
  const finalRes = cancelEcho(transcript, fullWin);
  let confirmAt = null, cancelled = false, accepted, confirmText = null;
  if (c.tts_active) {
    for (const r of texts) {
      if (!r.text) continue;
      // Hẹn giờ xác nhận chỉ còn hiệu lực tới khi onAutoStop (clearTimeout) xảy ra.
      if (r.t > P.confirmMs && tAuto > P.confirmMs) break;
      if (P.interim(cancelEcho(r.text, winAt(r.t)), winAt(r.t))) { confirmAt = r.t; confirmText = r.text; break; }
    }
    if (confirmAt == null && tAuto > P.confirmMs) cancelled = true;   // timer -> live.cancel(), bỏ lượt
    const finalOk = !cancelled && P.final(finalRes, fullWin);
    if (confirmAt == null && finalOk) {
      const f = (c.finals || []).at(-1);
      confirmAt = f ? Math.max(f.t_ms, tAuto) : tAuto;
      confirmText = `[bản chốt] ${transcript}`;
    }
    accepted = confirmAt != null;            // AI bị dừng hẳn
    var delivered = finalOk ? finalRes.text : '';
  } else {
    accepted = finalRes.kept > 0;
    delivered = accepted ? finalRes.text : '';
  }
  const w = wordScore(transcript, delivered, c.expected_user);
  const ok = c.label === 'echo_only' ? !accepted : accepted && !!delivered && w.userLost === 0;
  return { id: c.case_id, cid: c.id, label: c.label, accepted, delivered, confirmAt, confirmText, cancelled, w, pass: ok, transcript, tAuto };
}

function loadRuns() {
  const dir = path.join(EVAL_DIR, 'live', 'runs');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort()
    .map((f) => ({ file: f, ...JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')) }));
}

const fmt = (a) => [pct(a.falseBarge) + ` (n=${a.nEcho})`, pct(a.missed) + ` (n=${a.nUser})`, pct(a.userWordLoss), pct(a.echoResidue), pct(a.strictPass)];
const COLS = ['nhóm', 'false-barge', 'missed-barge', 'user-word loss', 'echo residue', 'strict pass'];
const dist = (xs) => {
  const a = xs.filter((x) => x != null);
  return a.length ? `p50 ${Math.round(quantile(a, 0.5))} | p95 ${Math.round(quantile(a, 0.95))} | p99 ${Math.round(quantile(a, 0.99))}${a.length < 100 ? '*' : ''} | max ${Math.max(...a)} (n=${a.length})` : '—';
};

describe('echo eval — dataset có nhãn (bản chốt)', () => {
  const ds = loadJson('echo_cases.json');
  const rows = ds.cases.map((c) => scoreCase(c));
  const summary = {};

  it('in bảng + ghi kết quả', () => {
    const groups = [['real_gemini', rows.filter((r) => r.source === 'real_gemini')], ['synthetic', rows.filter((r) => r.source === 'synthetic')]];
    table('Echo — dataset có nhãn, policy hiện tại (cur)', COLS, groups.map(([g, rs]) => [g + ` (${rs.length})`, ...fmt(aggregate(rs))]));
    // Theo tag (chỉ synthetic: mỗi tag là một kiểu lỗi Gemini)
    const tags = [...new Set(rows.flatMap((r) => r.tags))].sort();
    table('Echo — strict pass theo tag (real+synthetic)', ['tag', 'n', 'pass', 'fail ids'],
      tags.map((t) => { const rs = rows.filter((r) => r.tags.includes(t)); return [t, rs.length, pct(rate(rs.filter((r) => r.pass).length, rs.length)), rs.filter((r) => !r.pass).map((r) => r.id).join(' ')]; }));
    const fails = rows.filter((r) => !r.pass);
    table('Echo — ca hỏng (cur)', ['id', 'label', 'gửi cho agent', 'user mất', 'ghi chú'],
      fails.map((r) => [r.id, r.label, JSON.stringify(r.delivered), r.w.userLost, (ds.cases.find((c) => c.id === r.id).note || '').slice(0, 60)]));
    // So sánh policy trên dataset (paired: cùng ca)
    table('Echo — so policy trên synthetic (paired)', ['policy', ...COLS.slice(1)],
      Object.keys(POLICIES).filter((p) => p === 'cur' || p === 'V2').map((p) => [p, ...fmt(aggregate(ds.cases.filter((c) => c.source === 'synthetic').map((c) => scoreCase(c, p))))]));
    summary.real_gemini = aggregate(groups[0][1]);
    summary.synthetic = aggregate(groups[1][1]);
    summary.synthetic_V2 = aggregate(ds.cases.filter((c) => c.source === 'synthetic').map((c) => scoreCase(c, 'V2')));
    summary.fail_ids = fails.map((r) => r.id);
    writeResult('echo_dataset', summary);
  });

  it('sàn hồi quy (lỏng)', () => {
    const s = aggregate(rows.filter((r) => r.source === 'synthetic'));
    expect(s.falseBarge).toBeLessThanOrEqual(0.35);
    expect(s.missed).toBeLessThanOrEqual(0.25);
    expect(s.userWordLoss).toBeLessThanOrEqual(0.25);
    // Ca real_gemini cốt lõi (48e3769) không được hỏng: echo-only sạch, echo+user giữ lời.
    expect(rows.find((r) => r.id === 'R01').pass).toBe(true);
    expect(rows.find((r) => r.id === 'R02').pass).toBe(true);
  });
});

describe('echo eval — live Gemini (phát lại dữ liệu thô)', () => {
  const runs = loadRuns();
  it.skipIf(!runs.length)('in bảng + ghi kết quả', () => {
    const summary = { runs: runs.map((r) => ({ file: r.file, run_id: r.meta.run_id, split: r.meta.split, attempted: r.meta.attempted, errored: r.meta.errored, src_hashes: r.meta.src_hashes })) };
    table('Live — các lần chạy (dữ liệu thô)', ['file', 'split', 'attempted', 'errored', 'liveStt.js lúc chạy'],
      runs.map((r) => [r.file, r.meta.split, r.meta.attempted, r.meta.errored, String(r.meta.src_hashes?.['voicego/frontend/src/services/liveStt.js'] || '').slice(0, 7)]));
    const splits = [...new Set(runs.map((r) => r.meta.split))];
    for (const split of splits) {
      const cases = runs.filter((r) => r.meta.split === split).flatMap((r) => r.cases);
      const ok = cases.filter((c) => !c.error);
      const first = ok.filter((c) => c.run === 1);       // không lặp: mỗi clip một lần
      const rowsFor = (p, wk) => first.map((c) => replayLive(c, p, wk));
      const prows = Object.keys(POLICIES).map((p) => [p, ...fmt(aggregate(rowsFor(p)))]);
      prows.push(['cur (cửa sổ nội suy)', ...fmt(aggregate(rowsFor('cur', 'echo_words_t_interp')))]);
      table(`Live ${split} — theo policy (n clip=${first.length}, lỗi session=${cases.length - ok.length})`, ['policy', ...COLS.slice(1)], prows);
      const cur = rowsFor('cur');
      table(`Live ${split} — chi tiết từng clip (cur vs V1c)`, ['clip', 'label', 'cur: dừng AI@ms', 'cur gửi', 'V1c: dừng AI@ms', 'V1c gửi', 'transcript'],
        first.map((c, i) => { const v = replayLive(c, 'V1c'); return [c.id, c.label, cur[i].confirmAt ?? (cur[i].cancelled ? 'huỷ' : '-'), JSON.stringify(cur[i].delivered), v.confirmAt ?? (v.cancelled ? 'huỷ' : '-'), JSON.stringify(v.delivered), JSON.stringify(c.transcript)]; }));
      // Độ trễ (phân phối, không phải trung bình — latency skill): p99 với n<100 không có ý nghĩa (*).
      const barge = (p) => rowsFor(p).filter((r) => r.label === 'user_barge').map((r) => r.confirmAt);
      const speechToFinal = ok.filter((c) => c.clip.speech_end_ms > 0 && c.finals?.length).map((c) => c.finals.at(-1).t_ms - c.clip.speech_end_ms);
      const afterEnd = ok.map((c) => c.timing?.app_done_after_end_ms);
      const firstFinal = ok.map((c) => c.timing?.first_final_after_end_ms).filter((x) => x != null);
      const beforeEnd = ok.filter((c) => (c.timing?.finals_before_end || 0) > 0).length;
      table(`Live ${split} — độ trễ (ms; * = n<100, p99 chỉ để tham khảo)`, ['đại lượng', 'phân phối'], [
        ['hết tiếng nói -> bản chốt cuối (Gemini tự chốt)', dist(speechToFinal)],
        ['audioStreamEnd -> app coi là xong lượt', dist(afterEnd)],
        ['audioStreamEnd -> bản chốt đầu tiên (nếu chốt SAU end)', dist(firstFinal)],
        ['lượt có bản chốt về TRƯỚC audioStreamEnd', `${beforeEnd}/${ok.length}`],
        ['VAD kêu -> xác nhận chen ngang (cur)', dist(barge('cur'))],
        ['VAD kêu -> xác nhận chen ngang (V1c)', dist(barge('V1c'))],
      ]);
      // Ổn định qua các lần lặp (pass@k vs pass^k)
      const rep = {};
      ok.forEach((c) => { (rep[c.id] ||= []).push(c); });
      const multi = Object.entries(rep).filter(([, xs]) => xs.length > 1);
      if (multi.length) {
        const stab = (p) => multi.map(([id, xs]) => {
          const rs = xs.map((c) => replayLive(c, p));
          return { id, k: rs.length, any: rs.some((r) => r.pass), all: rs.every((r) => r.pass), sameText: new Set(xs.map((c) => c.transcript)).size === 1, texts: [...new Set(xs.map((c) => c.transcript))] };
        });
        for (const p of ['cur', 'V1c']) {
          const st = stab(p);
          table(`Live ${split} — ổn định qua ${st[0].k} lần chạy (${p})`, ['clip', 'pass@k', 'pass^k', 'transcript giống nhau', 'các transcript'],
            st.map((s) => [s.id, s.any ? 1 : 0, s.all ? 1 : 0, s.sameText ? 'có' : 'KHÔNG', s.texts.map((t) => JSON.stringify(t)).join(' / ')]));
          summary[`${split}_stability_${p}`] = st;
        }
      }
      summary[split] = Object.fromEntries(Object.keys(POLICIES).map((p) => [p, aggregate(rowsFor(p))]));
      summary[split].cur_interp = aggregate(rowsFor('cur', 'echo_words_t_interp'));
      summary[split].latency = { speechToFinal, afterEnd, confirm_cur: barge('cur'), confirm_V1c: barge('V1c') };
      const fb = cur.filter((r) => r.label === 'echo_only' && r.accepted);
      table(`Live ${split} — false-barge (cur): chữ nào làm AI dừng`, ['clip', '@ms', 'chữ lúc xác nhận'], fb.map((r) => [r.cid, r.confirmAt, JSON.stringify(r.confirmText)]));
      summary[split].clips = cur.map((r) => ({ id: r.cid, label: r.label, pass: r.pass, confirmAt: r.confirmAt, confirmText: r.confirmText, delivered: r.delivered }));
    }
    writeResult('echo_live', summary);
    expect(runs.every((r) => r.meta.errored <= r.meta.attempted * 0.2)).toBe(true);   // tối đa 20% session lỗi
  });
});

export { replayLive, scoreCase, POLICIES, explainedByWindow, se };

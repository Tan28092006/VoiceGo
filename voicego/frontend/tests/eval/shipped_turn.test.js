// Eval chấm CODE ĐANG CHẠY, không chấm bản sao logic.
//
// Vì sao có file này: echo.test.js phát lại lượt nói bằng logic CHÉP LẠI trong chính file
// eval (cancelEcho + isBargeIn), nên khi useVoiceApp đổi cách quyết định (A4: assessTurn),
// dòng "cur" ở đó KHÔNG đổi — eval xanh mà không đo được thứ đã ship. File này phát lại
// đúng dữ liệu thô Gemini (eval/live/runs) qua đúng các hàm hook gọi: assessTurn,
// bargeTimeout, silenceMsFor từ src/services/liveStt.js, với hằng số thời gian ĐỌC TỪ
// useVoiceApp.js. Đổi hook mà không đổi được các con số này -> eval đỏ.
//
// Mô hình thời gian = useVoiceApp._listenWhisper, nhánh Gemini Live: lúc VAD kêu (t=0) AI
// đang đọc thì TẠM DỪNG giọng AI, chờ xác nhận; hết BARGE_CONFIRM_MS mà server còn nghe
// tiếng nói thì gia hạn một lần BARGE_EXTEND_MS; chốt lượt khi im quá silenceMsFor(chữ đã
// gỡ vọng). Không có Gemini call nào: chỉ đọc file đã lưu.
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';
import { assessTurn, bargeTimeout, silenceMsFor } from '../../src/services/liveStt.js';
import { EVAL_DIR, FRONTEND, tokens, overlap, minus, quantile, table, writeResult } from './_lib.js';

const HOOK_SRC = fs.readFileSync(path.join(FRONTEND, 'src', 'hooks', 'useVoiceApp.js'), 'utf8');
function hookDefault(param) {
  // const X = (() => { const v = Number(...get('<param>')); return v > 0 ? v : <N>; })();
  const m = HOOK_SRC.match(new RegExp(`get\\('${param}'\\)\\);\\s*return v > 0 \\? v : (\\d+);`));
  return m ? Number(m[1]) : null;
}
const CONFIRM_MS = hookDefault('bargeconfirm');
const EXTEND_MS = hookDefault('bargeextend');
const FRAME_MS = (4096 / 48000) * 1000;

function loadRuns() {
  const dir = path.join(EVAL_DIR, 'live', 'runs');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')));
}

function replayHook(c) {
  const wt = c.echo_words_t || [];
  const winAt = (t) => wt.filter(([, tt]) => tt <= t + 300).map(([w]) => w);
  const ev = [];
  (c.activity || []).forEach((a) => ev.push({ t: a.t_ms, o: 0, kind: 'a', type: a.type }));
  (c.interims || []).forEach((x) => ev.push({ t: x.t_ms, o: 1, kind: 'i', text: x.text }));
  (c.finals || []).forEach((x) => ev.push({ t: x.t_ms, o: 2, kind: 'f', text: x.text }));
  ev.sort((a, b) => a.t - b.t || a.o - b.o);
  const speechEnd = c.clip.speech_end_ms;
  const s = { finals: [], interim: '', active: false, saw: false };
  const turn = { pending: !!c.tts_active, extended: false, timerAt: c.tts_active ? CONFIRM_MS : Infinity, last: null };
  let confirmAt = null, falseAt = null, outcome = null;
  const text = () => [...s.finals, s.interim].filter(Boolean).join(' ').trim();
  const evidence = (t, txt) => ({
    text: txt != null ? txt : text(), echoWords: winAt(t), aiSpeakingAtStart: !!c.tts_active,
    hasFinal: s.finals.length > 0, interimPending: !!s.interim, serverActive: s.active,
    serverHeardSpeech: s.saw, localVoice: t < speechEnd + 250, sessionLost: false,
  });
  const decide = (t) => {
    if (!turn.pending) return;
    const a = assessTurn(evidence(t), 'interim');
    turn.last = a;
    if (a.verdict === 'user') { turn.pending = false; confirmAt = t; outcome = 'confirmed'; }
    else if (a.verdict === 'echo') { turn.pending = false; falseAt = t; outcome = 'false-alarm-fast'; }
  };
  const apply = (e) => {
    if (e.kind === 'a') {
      if (e.type === 'ACTIVITY_START') { s.active = true; s.saw = true; } else { s.active = false; decide(e.t); }
      return;
    }
    if (e.kind === 'i') s.interim = e.text.trim(); else { s.finals.push(e.text.trim()); s.interim = ''; }
    turn.last = assessTurn(evidence(e.t), 'interim');
    decide(e.t);
  };
  let ei = 0, tEnd = null;
  for (let t = 0; t < 20000; t += FRAME_MS) {
    while (ei < ev.length && ev[ei].t <= t) apply(ev[ei++]);
    if (turn.pending && t >= turn.timerAt) {
      const act = bargeTimeout(evidence(t), turn.extended);
      if (act === 'extend') { turn.extended = true; turn.timerAt = t + EXTEND_MS; }
      else { turn.pending = false; falseAt = t; outcome = act === 'hard-stop' ? 'hard-stop' : 'false-alarm-timer'; }
    }
    if (outcome && outcome.startsWith('false-alarm')) break;          // lượt bị bỏ, AI đọc tiếp
    const clean = turn.last ? turn.last.userText : '';
    if (t > speechEnd && t - Math.max(speechEnd, FRAME_MS) > silenceMsFor(clean)) { tEnd = t; break; }
  }
  let delivered = '';
  if (tEnd != null) {
    const lastF = (c.finals || []).at(-1);
    const tFinish = lastF ? Math.max(lastF.t_ms, tEnd) : tEnd + 350;
    while (ei < ev.length && ev[ei].t <= tFinish) apply(ev[ei++]);   // onText vẫn chạy trong lúc finish() chờ
    delivered = assessTurn(evidence(tFinish, c.transcript || ''), 'final').userText;
    if (turn.pending) {
      turn.pending = false;
      if (delivered) { confirmAt = tFinish; outcome = 'confirmed-final'; } else { falseAt = tFinish; outcome = 'false-alarm-endpoint'; }
    }
  }
  if (c.tts_active && confirmAt == null) delivered = '';
  return { accepted: c.tts_active ? confirmAt != null : !!delivered, confirmAt, delivered, falseAt, outcome };
}

function score(cases) {
  const rows = cases.map((c) => {
    const r = replayHook(c);
    const raw = tokens(c.transcript || ''), out = tokens(r.delivered), exp = tokens(c.expected_user);
    const inRaw = overlap(exp, raw), kept = overlap(exp, out);
    const w = { inRaw, lost: Math.max(0, inRaw - kept), echoRaw: minus(raw, exp).length, echoOut: minus(out, exp).length };
    const pass = c.label === 'echo_only' ? !r.accepted : r.accepted && !!r.delivered && w.lost === 0;
    return { c, r, w, pass };
  });
  const echo = rows.filter((x) => x.c.label === 'echo_only');
  const user = rows.filter((x) => x.c.label !== 'echo_only');
  const sum = (xs, f) => xs.reduce((a, x) => a + f(x), 0);
  const conf = rows.filter((x) => x.c.label === 'user_barge' && x.r.confirmAt != null).map((x) => x.r.confirmAt);
  const pause = echo.filter((x) => !x.r.accepted && x.r.falseAt != null).map((x) => x.r.falseAt);
  return {
    n: rows.length, nEcho: echo.length, nUser: user.length,
    falseBarge: echo.filter((x) => x.r.accepted).length,
    missed: user.filter((x) => !x.r.accepted || !x.r.delivered).length,
    userWordLoss: sum(user, (x) => x.w.inRaw) ? sum(user, (x) => x.w.lost) / sum(user, (x) => x.w.inRaw) : 0,
    strictPass: rows.filter((x) => x.pass).length / (rows.length || 1),
    confirmMs: { p50: quantile(conf, 0.5), p95: quantile(conf, 0.95), max: conf.length ? Math.max(...conf) : null, n: conf.length },
    echoPauseMs: { p50: quantile(pause, 0.5), max: pause.length ? Math.max(...pause) : null, n: pause.length },
    fails: rows.filter((x) => !x.pass).map((x) => `${x.c.id}:${x.r.outcome || ''}:${JSON.stringify(x.r.delivered)}`),
  };
}

const runs = loadRuns();
const bySplit = (split) => runs.filter((r) => r.meta && r.meta.split === split)
  .flatMap((r) => r.cases).filter((c) => !c.error && c.run === 1);

describe('shipped turn logic — phát lại dữ liệu thô Gemini qua assessTurn/bargeTimeout thật', () => {
  it('đọc được hằng số thời gian từ useVoiceApp.js (không lệch với hook)', () => {
    expect(CONFIRM_MS, 'không tìm thấy default của ?bargeconfirm trong useVoiceApp.js').toBeGreaterThan(0);
    expect(EXTEND_MS, 'không tìm thấy default của ?bargeextend trong useVoiceApp.js').toBeGreaterThan(0);
  });

  it.skipIf(!runs.length)('in bảng + sàn hồi quy (dev, holdout)', () => {
    const summary = {};
    const rows = [];
    for (const split of ['dev', 'holdout', 'latency']) {
      const cases = bySplit(split);
      if (!cases.length) continue;
      const a = score(cases);
      summary[split] = a;
      const r = (x) => (x == null ? '—' : Math.round(x));
      rows.push([split, `${a.falseBarge}/${a.nEcho}`, `${a.missed}/${a.nUser}`, `${(a.userWordLoss * 100).toFixed(1)}%`,
        `${(a.strictPass * 100).toFixed(1)}%`, `p50 ${r(a.confirmMs.p50)} p95 ${r(a.confirmMs.p95)} max ${r(a.confirmMs.max)} (n=${a.confirmMs.n})`]);
    }
    table(`shipped turn logic (confirm ${CONFIRM_MS} ms + extend ${EXTEND_MS} ms)`,
      ['split', 'false-barge', 'missed', 'user-word loss', 'strict pass', 'confirm latency'], rows);
    writeResult('shipped_turn', { confirmMs: CONFIRM_MS, extendMs: EXTEND_MS, summary });

    // Sàn LỎNG, đặt theo lần đo khi ship A4 (dev 1/9, holdout 3/9, missed 0/17, loss 0%):
    // chặn hồi quy rõ ràng, không đòi tốt hơn mức đã đo. Tập nhỏ (±16 điểm %), xem RESULTS.md.
    const dev = summary.dev, hold = summary.holdout;
    if (dev) {
      expect(dev.falseBarge, `dev false-barge; fails: ${dev.fails.join(' ')}`).toBeLessThanOrEqual(2);
      expect(dev.missed, 'dev: bỏ sót chen ngang thật').toBe(0);
      expect(dev.userWordLoss).toBeLessThanOrEqual(0.05);
    }
    if (hold) {
      expect(hold.falseBarge, `holdout false-barge; fails: ${hold.fails.join(' ')}`).toBeLessThanOrEqual(4);
      expect(hold.missed, 'holdout: bỏ sót chen ngang thật').toBe(0);
    }
  });
});

/**
 * Ghi thời gian từng chặng của MỘT lượt nói -> một dòng console `[turn] {...}` để
 * gom thành phân phối p50/p95/p99 (sách latency: chọn timeout/hedge từ phân phối đo
 * được, không đoán hằng số). Không gửi đi đâu, không ảnh hưởng luồng chính.
 *
 * Hợp đồng (dùng chung giữa nhánh nghe và _send):
 *  - startTurn(data)    : mở lượt mới lúc VAD xác nhận có tiếng nói. Lượt cũ còn mở
 *                         thì tự đóng với outcome 'next-turn' (khỏi bắt ai cũng phải endTurn).
 *  - mark(name, data)   : ghi mốc `name` = ms kể từ đầu lượt (chỉ lần ĐẦU mỗi tên),
 *                         gộp `data` vào các trường của lượt. Không có lượt mở -> bỏ qua.
 *  - endTurn(outcome, data) : đóng lượt, in ĐÚNG MỘT dòng, trả record (hoặc null).
 *  - currentTurnId()    : id lượt đang mở hoặc null.
 * Lượt không ai đóng thì tự đóng ('idle-flush') sau FLUSH_MS kể từ mốc cuối.
 *
 * Mốc phía nghe (useVoiceApp._listenWhisper): speech, bargePause, bargeExtend,
 * bargeConfirm, bargeFalseAlarm, endpoint, liveFinal, whisperStart, whisperEnd, text.
 */
const FLUSH_MS = 30000;
const clock = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

let cur = null;
let seq = 0;
let flushTimer = null;

function armFlush() {
  clearTimeout(flushTimer);
  flushTimer = setTimeout(() => endTurn('idle-flush'), FLUSH_MS);
}

export function startTurn(data = {}) {
  if (cur) endTurn('next-turn');
  cur = { id: ++seq, t0: clock(), wall: Date.now(), marks: {}, data: { ...data } };
  armFlush();
  return cur.id;
}

export function mark(name, data) {
  if (!cur) return;
  if (!(name in cur.marks)) cur.marks[name] = Math.round(clock() - cur.t0);
  if (data) Object.assign(cur.data, data);
  armFlush();
}

const span = (m, a, b) => (m[a] != null && m[b] != null ? m[b] - m[a] : undefined);

export function endTurn(outcome, data) {
  if (!cur) return null;
  clearTimeout(flushTimer);
  flushTimer = null;
  const t = cur.marks;
  const rec = {
    id: cur.id,
    at: new Date(cur.wall).toISOString(),
    outcome: outcome || 'done',
    ...cur.data,
    ...(data || {}),
    endpointToTextMs: span(t, 'endpoint', 'text'),
    liveFinalMs: span(t, 'endpoint', 'liveFinal'),
    whisperMs: span(t, 'whisperStart', 'whisperEnd'),
    bargeConfirmMs: span(t, 'bargePause', 'bargeConfirm'),
    bargeFalseAlarmMs: span(t, 'bargePause', 'bargeFalseAlarm'),
    t,
  };
  Object.keys(rec).forEach((k) => rec[k] === undefined && delete rec[k]);
  cur = null;
  try { console.log(`[turn] ${JSON.stringify(rec)}`); } catch (e) {}
  return rec;
}

export function currentTurnId() { return cur ? cur.id : null; }

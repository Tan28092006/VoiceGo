import { BACKEND_URL } from './config';  // '' = same-origin (dev) | URL Render (prod)

export async function checkHealth() {
  const res = await fetch(`${BACKEND_URL}/api/health`);
  return res.json();
}

// Trả cả {text, error}: 'error' có nghĩa Whisper THẬT SỰ lỗi (hết quota/mạng...),
// khác với text='' đơn thuần (chỉ là im lặng/nhiễu, Whisper vẫn chạy bình thường).
// Caller dùng 'error' để biết khi nào nên lùi sang Web Speech API của trình duyệt.
//
// Hạn chót 12s (server tự bỏ Groq sau 10s; đo thật tối đa ~3.5s): request treo giữa
// điện thoại và Render mà không có hạn thì processingRef khoá mãi, mic không mở lại.
// Quá hạn -> {text:'', error:'timeout'} để caller chạy nhánh dự phòng sẵn có.
export const STT_DEADLINE_MS = 12000;
export async function speechToText(audioBlob, filename = 'audio.wav') {
  const form = new FormData();
  form.append('file', audioBlob, filename);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), STT_DEADLINE_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/api/voice/stt`, { method: 'POST', body: form, signal: ctrl.signal });
    const data = await res.json();
    return { text: data.text || '', error: data.error || null };
  } catch (err) {
    if (ctrl.signal.aborted) return { text: '', error: 'timeout' };
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function textToSpeech(text, voice = 'banmai', speed = '') {
  const res = await fetch(`${BACKEND_URL}/api/voice/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice, speed }),
  });
  if (!res.ok) return null;
  return res.blob();
}

export async function agentChat(messages, pickup = null) {
  const res = await fetch(`${BACKEND_URL}/api/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, pickup }),
  });
  return res.json();
}

/**
 * Bộ tách SSE thuần (không đụng mạng, test được): feed(chữ) -> các sự kiện {type, data}
 * đã trọn. Dòng bắt đầu bằng ':' là chú thích (server dùng để đẩy header đi ngay).
 */
export function createSseParser() {
  let buf = '';
  const parseBlock = (block) => {
    let type = 'message';
    const data = [];
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue;
      const k = line.indexOf(':');
      const field = k < 0 ? line : line.slice(0, k);
      const val = k < 0 ? '' : line.slice(k + 1).replace(/^ /, '');
      if (field === 'event') type = val;
      else if (field === 'data') data.push(val);
    }
    if (!data.length) return null;
    try { return { type, data: JSON.parse(data.join('\n')) }; } catch (e) { return null; }
  };
  return {
    feed(chunk) {
      buf += String(chunk).replace(/\r\n?/g, '\n');
      const out = [];
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const ev = parseBlock(buf.slice(0, i));
        buf = buf.slice(i + 2);
        if (ev) out.push(ev);
      }
      return out;
    },
  };
}

/**
 * Bản STREAM của agentChat: POST /api/agent/chat_stream (SSE). Gọi onEvent(type, data)
 * cho từng sự kiện 'tools' | 'sentence' ngay khi tới; resolve bằng data của 'done'
 * (= đúng {reply, messages, ui} của agentChat). Ném lỗi khi HTTP lỗi, stream đứt trước
 * 'done' hoặc bị huỷ bằng `signal` (AbortController) -> bên gọi tự lùi về agentChat.
 */
// Hạn chót của stream (latency handbook: mọi chờ đợi phải có deadline trong ngân sách
// cả tác vụ). Byte đầu: Render free ngủ khi rảnh, khởi động lại mất ~30-50s -> cho 60s
// (lùi về /api/agent/chat sớm hơn cũng chẳng nhanh hơn, cùng một instance đang dậy).
// Sau byte đầu: server im tối đa trong lúc chạy tool (tra địa điểm có khi vài giây) ->
// 30s không có gì mới là coi như treo. Server gửi ': stream' ngay khi nhận request.
export const STREAM_FIRST_BYTE_MS = 60000;
export const STREAM_IDLE_MS = 30000;

export async function agentChatStream(messages, pickup = null, {
  signal, onEvent, firstByteMs = STREAM_FIRST_BYTE_MS, idleMs = STREAM_IDLE_MS,
} = {}) {
  const ctrl = new AbortController();
  const onOuterAbort = () => ctrl.abort();
  if (signal) { if (signal.aborted) ctrl.abort(); else signal.addEventListener('abort', onOuterAbort); }
  let timedOut = null;
  let timer = null;
  const arm = (ms, why) => {
    clearTimeout(timer);
    timer = setTimeout(() => { timedOut = why; ctrl.abort(); }, ms);
  };
  arm(firstByteMs, 'first byte');
  let reader = null;
  try {
    const res = await fetch(`${BACKEND_URL}/api/agent/chat_stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ messages, pickup }),
      signal: ctrl.signal,
    });
    if (!res.ok || !res.body) throw new Error(`chat_stream HTTP ${res.status}`);
    reader = res.body.getReader();
    const dec = new TextDecoder();
    const sse = createSseParser();
    for (;;) {
      const { value, done } = await reader.read();
      arm(idleMs, 'idle');
      const evs = done ? sse.feed(dec.decode() + '\n\n') : sse.feed(dec.decode(value, { stream: true }));
      for (const ev of evs) {
        if (ev.type === 'done') return ev.data;
        onEvent?.(ev.type, ev.data);
      }
      if (done) throw new Error('chat_stream: hết stream mà không có sự kiện done');
    }
  } catch (err) {
    if (timedOut) throw new Error(`chat_stream: quá hạn (${timedOut})`);
    throw err;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onOuterAbort);
    try { reader?.cancel().catch(() => {}); } catch (e) {}   // đã có 'done' / lỗi / bị huỷ -> nhả kết nối
  }
}

/**
 * Lịch sử chốt cho một lời đáp BỊ NGẮT (chen ngang / lượt mới / speak() khác chen vào).
 *
 * Chỉ giữ đúng những gì người dùng ĐÃ NGHE, đánh dấu " …" là bị cắt ngang (AI Agents in
 * Depth ch04, quy tắc 1+4: lời đã "phát ra" mới là đã ghi vào trajectory; phần đang sinh
 * dở mà chưa tới tai người dùng thì bỏ, bắt đầu vòng mới với sự kiện mới). Lý do không giữ
 * toàn văn: nếu câu "Bạn xác nhận đặt xe nhé?" bị cắt trước khi đọc tới, giữ toàn văn sẽ
 * làm LLM tưởng đã hỏi rồi và hiểu tiếng "ừ" chen ngang là đồng ý đặt xe.
 *
 * `base` = mốc lịch sử sau vòng tool cuối (sự kiện 'tools'; kết quả tool THẬT đã chạy, vd
 * đã báo giá, đã đặt xe — ch04 quy tắc 2: tác dụng phụ đã xảy ra không được xoá), hoặc
 * lịch sử đã gửi đi nếu lượt này chưa chạy tool nào. Luôn thêm một lời assistant (kể cả
 * "…" khi chưa nghe được chữ nào) để chuỗi role không kết thúc bằng tool/user.
 */
export function interruptedMessages(base, heard) {
  const h = String(heard || '').trim();
  return [...(base || []), { role: 'assistant', content: h ? `${h} …` : '…' }];
}

// Sau khi lời đáp bị ngắt, vẫn đọc nốt stream (im lặng) tối đa chừng này để biết MỌI tool
// đã chạy trong lượt (vd đặt xe chạy sau một câu dẫn); quá hạn thì huỷ và chốt theo mốc cuối.
export const DRAIN_AFTER_CUT_MS = 8000;

/**
 * Một lượt agent có STREAM + đọc từng câu. Thuần logic (fetch/hàng đợi đọc đều tiêm vào
 * được) để test không cần trình duyệt.
 *
 * deps:
 *  - createQueue(opts)       hàng đợi đọc (tts.createSpeechQueue)
 *  - onFirstSentence(ui)     câu đầu tới: ui = ui của mốc 'tools' gần nhất (= ui cuối lượt,
 *                            vì vòng sinh lời không gọi tool). Trả false = KHÔNG đọc các câu
 *                            (vd đã đặt xe: _send đọc câu cố định riêng).
 *  - onLateUi(ui)            mốc 'tools' tới SAU câu đầu (tool chạy sau một câu dẫn, kể cả khi
 *                            lời đáp đã bị ngắt): thao tác đã commit phải hiện/báo, không giấu.
 *  - onSentence(text, first) hiện chữ lên màn hình
 *  - onFirstStart()          loa bắt đầu phát câu đầu (mở mic cho chen ngang)
 *  - onInterrupted(messages) lời đáp bị ngắt -> lịch sử đã chốt (interruptedMessages)
 *  - stream / fallback       mặc định agentChatStream / agentChat
 *
 * Trả turn = {
 *   result:  Promise<{reply, messages, ui, streamed, uiApplied, legacy?, resync?} | null>
 *            null = lượt đã bị ngắt (lịch sử đi qua onInterrupted),
 *   speech:  Promise<{interrupted, spoken, partial}> | null  (khi đọc qua hàng đợi),
 *   settled: Promise — lịch sử của lượt đã CHỐT (xong bình thường hoặc đã commit sau ngắt),
 *   cut():   ngắt lượt (bỏ các câu chưa đọc) -> trả settled, isCut()
 * }
 *
 * Chốt lịch sử (khi nào lời đáp "commit" vào messages):
 *  - Kết quả tool commit ở MỐC 'tools' (server gửi sau khi tool trả kết quả thật).
 *  - Lời nói commit khi đã PHÁT RA LOA: xong trọn -> 'done' (toàn văn); bị ngắt -> chỉ phần
 *    đã nghe + " …". Bị ngắt thì vẫn đọc nốt stream im lặng (không nói thêm câu nào) để
 *    nhận mọi mốc 'tools' còn lại rồi mới chốt — ngắt lời không được giấu thao tác đã làm.
 *
 * Lùi/chạy lại (không bao giờ đọc một câu hai lần, không đặt xe hai lần):
 *  - Lỗi TRƯỚC câu đầu, chưa có sự kiện 'action' (chưa chạy thao tác ghi nào) -> gọi
 *    /api/agent/chat, từ mốc 'tools' nếu có (không chạy lại tool đã chạy).
 *  - Lỗi sau 'action' nhưng chưa có mốc của nó: kết quả đặt xe là UNKNOWN (có thể đã commit
 *    mà mất response). Gửi lại CÙNG lượt để đối soát (resync): server khoá book_ride theo
 *    lượt (agent._book_once) nên trả lại đúng chuyến đã đặt, không tạo chuyến mới.
 *  - Lỗi SAU câu đầu -> không gửi lại (sẽ sinh lời khác, đọc trùng): đọc nốt các câu đã
 *    nhận, lịch sử = mốc + đúng các câu đó.
 *  - Sự kiện 'sentence' trùng chỉ số i (gửi lặp) bị bỏ; sự kiện sau khi ngắt không được đọc.
 */
export function runAgentTurn(messages, pickup, deps = {}) {
  const {
    createQueue, onFirstSentence, onLateUi, onSentence, onFirstStart, onInterrupted,
    stream = agentChatStream, fallback = agentChat, drainMs = DRAIN_AFTER_CUT_MS,
  } = deps;
  const ctrl = new AbortController();
  const st = {
    ckpt: null, action: null, sentences: [], lastI: -1, q: null, speak: true, first: false,
    cut: false, heard: '', committed: false, finished: false, drainTimer: null,
  };
  const base = () => (st.ckpt && st.ckpt.messages) || messages;
  let resolveSettled;
  const settled = new Promise((r) => { resolveSettled = r; });
  const heardOf = (r) => (r ? [...(r.spoken || []), r.partial || ''].join(' ') : '');

  const commitCut = () => {
    if (st.committed) return;
    st.committed = true;
    clearTimeout(st.drainTimer);
    try { onInterrupted?.(interruptedMessages(base(), st.heard)); } catch (e) { console.error(e); }
    resolveSettled();
  };
  const interrupt = (heard) => {
    if (st.cut) return;
    st.cut = true;
    st.heard = heard || '';
    if (st.finished) { commitCut(); return; }
    // Stream chưa xong: im lặng đọc nốt (có hạn) để không mất mốc tool nào.
    st.drainTimer = setTimeout(() => { try { ctrl.abort(); } catch (e) {} }, drainMs);
  };

  const turn = {
    speech: null,
    settled,
    isCut: () => st.cut,
    cut: () => {
      if (!st.cut) {
        if (st.q && !st.q.closed) { st.q.cancel(); interrupt(heardOf(st.q.result)); }
        else if (st.q && st.q.result && st.q.result.interrupted) interrupt(heardOf(st.q.result));
        else if (!st.finished) interrupt(st.q ? st.q.spoken.join(' ') : '');
      }
      return settled;
    },
  };

  const onEvent = (type, data) => {
    if (type === 'action') { st.action = data || {}; return; }
    if (type === 'tools') {
      st.ckpt = data;
      if (st.first) { try { onLateUi?.((data && data.ui) || {}); } catch (e) { console.error(e); } }
      return;
    }
    if (st.cut || type !== 'sentence' || !data || !data.text) return;
    if (typeof data.i === 'number') {
      if (data.i <= st.lastI) return;          // trùng -> bỏ, không đọc lại
      st.lastI = data.i;
    }
    const first = !st.first;
    if (first) {
      st.first = true;
      st.speak = onFirstSentence ? onFirstSentence((st.ckpt && st.ckpt.ui) || {}) !== false : true;
      if (st.speak && createQueue) {
        st.q = createQueue({ onFirstStart });
        turn.speech = st.q.drained;
        st.q.drained.then((r) => { if (r && r.interrupted) interrupt(heardOf(r)); });
      }
    }
    st.sentences.push(data.text);
    if (st.speak) {
      try { onSentence?.(data.text, first); } catch (e) { console.error(e); }
      st.q?.push(data.text);
    }
  };

  turn.result = (async () => {
    try {
      const done = await stream(messages, pickup, { signal: ctrl.signal, onEvent });
      st.finished = true;
      if (st.cut) { commitCut(); return null; }
      st.q?.end();
      resolveSettled();
      return { ...done, streamed: st.first, uiApplied: st.first };
    } catch (err) {
      st.finished = true;
      if (st.cut) { commitCut(); return null; }
      if (!st.first) {
        const ck = st.ckpt;
        // 'action' tới sau mốc cuối = thao tác ghi đã bắt đầu mà chưa biết kết quả.
        const resync = !!(st.action && !(ck && ck.ms != null && st.action.ms != null && ck.ms >= st.action.ms));
        console.warn(`[agentStream] stream lỗi -> /api/agent/chat${resync ? ' (đối soát đặt xe)' : ''}:`, err && err.message);
        const r = await fallback(resync ? messages : (ck ? ck.messages : messages), pickup);
        resolveSettled();
        return { ...r, ui: { ...((ck && ck.ui) || {}), ...((r && r.ui) || {}) },
          streamed: false, uiApplied: false, legacy: true, resync };
      }
      console.warn('[agentStream] stream đứt giữa lời đáp -> đọc nốt các câu đã nhận:', err && err.message);
      st.q?.end();
      resolveSettled();
      const reply = st.sentences.join(' ');
      return { reply, messages: [...base(), { role: 'assistant', content: reply }],
        ui: (st.ckpt && st.ckpt.ui) || {}, streamed: true, uiApplied: true, partial: true };
    }
  })();
  turn.result.catch(() => resolveSettled());
  return turn;
}

export async function searchPlaces(query) {
  const res = await fetch(`${BACKEND_URL}/api/places/search?q=${encodeURIComponent(query)}`);
  return res.json();
}

export async function geocode(address) {
  const res = await fetch(`${BACKEND_URL}/api/geocode?address=${encodeURIComponent(address)}`);
  return res.json();
}

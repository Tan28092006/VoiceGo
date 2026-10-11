import { BACKEND_URL } from './config';
import { initSharedAudioContext } from './voiceRecorder';

// ONE reusable audio element. Mobile blocks audio started outside a user gesture;
// by reusing a single element that got unlocked by the greeting (played right
// after the user's tap), later socket-triggered speech (driver arrived, PIN)
// can still play. (A fresh `new Audio()` each time would be blocked on mobile.)
let el = null;
let genToken = 0;   // only the LATEST speak() is allowed to play (no overlap)
let curText = '';   // câu AI đang đọc
let pausedKind = null;   // pauseSpeech() đã tạm dừng cái gì: 'audio' | 'synth' | null
let synthPrimed = false;
let synth = null;   // lượt speechSynthesis đang đọc (xem synthSpeak)

// ── Giọng đọc: 'browser' (mặc định) = speechSynthesis của trình duyệt (Chrome: Google
// Tiếng Việt, Edge: Microsoft HoaiMy) — ra tiếng gần như NGAY vì không đi qua server;
// 'edge' = Edge TTS qua backend (~0.9-2.7s mới ra tiếng). Máy không có giọng vi thì
// nhánh 'browser' tự đọc bằng Edge (đọc tiếng Việt bằng giọng Anh thì nghe không hiểu).
let ttsEngine = 'browser';
export function setTtsEngine(v) { ttsEngine = v === 'edge' ? 'edge' : 'browser'; }

let viVoice = null;
function pickViVoice() {
  const ss = typeof window !== 'undefined' && window.speechSynthesis;
  if (!ss) return null;
  // Ưu tiên giọng neural online (Edge "Natural"/"Online"), rồi Google, rồi giọng máy.
  const rank = (v) => (/natural|online/i.test(v.name) ? 0 : /google/i.test(v.name) ? 1 : 2);
  viVoice = ss.getVoices().filter((v) => /^vi/i.test(v.lang)).sort((a, b) => rank(a) - rank(b))[0] || null;
  return viVoice;
}
if (typeof window !== 'undefined' && window.speechSynthesis) {
  pickViVoice();   // Chrome nạp danh sách giọng bất đồng bộ -> chọn lại khi có
  try { window.speechSynthesis.addEventListener('voiceschanged', pickViVoice); } catch (e) {}
}

// ── Dòng thời gian lời AI đã phát ra loa ────────────────────────────────────────
// Để LỌC TIẾNG VỌNG THEO THỜI GIAN: tiếng AI lọt vào mic chỉ có thể là mấy từ AI
// vừa phát ra quanh lúc đó, nên so chữ Gemini nghe được với đúng những từ ấy (xem
// spokenWordsBetween + cancelEcho trong liveStt.js) — thay cho bộ khử vọng của mic,
// thứ mà giọng trình duyệt trên Android nhiều khi không đi qua.
// Mỗi đoạn = một lần loa đọc liền một mạch. Giọng trình duyệt bắn sự kiện boundary
// từng từ -> có GIỜ THẬT của từng từ (marks); không có (Edge, engine không hỗ trợ)
// thì nội suy theo số ký tự với tốc độ đọc tự hiệu chỉnh.
const segs = [];
let curSeg = null;
const msPerChar = { browser: 75, edge: 70 };   // tự hiệu chỉnh theo máy sau mỗi câu đọc trọn
const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

function segStart(text, engine) {
  segEnd(false);
  curSeg = { start: now(), end: null, text: String(text || ''), engine, natural: false, pausedAt: null, marks: [] };
  segs.push(curSeg);
  while (segs.length > 30) segs.shift();
}
function segEnd(natural) {
  const s = curSeg;
  if (!s) return;
  curSeg = null;
  s.end = now();
  if (natural && s.text.length > 8) {
    s.natural = true;
    const r = (s.end - s.start) / s.text.length;
    if (r > 20 && r < 300) msPerChar[s.engine] = msPerChar[s.engine] * 0.7 + r * 0.3;
  }
}

/** Các từ AI ĐÃ phát ra loa trong khoảng [t0, t1] (mốc performance.now()). */
export function spokenWordsBetween(t0, t1) {
  const out = [];
  for (const s of segs) {
    if (s.start > t1 || (s.end != null && s.end < t0)) continue;
    const dur = s.natural ? s.end - s.start : s.text.length * msPerChar[s.engine];
    const stopAt = s.end != null ? s.end : (s.pausedAt != null ? s.pausedAt : Infinity);
    const re = /\S+/g;
    let m;
    while ((m = re.exec(s.text))) {
      // Có mốc boundary ở/trước từ này -> tính từ mốc thật gần nhất; không thì nội suy.
      let mk = null;
      for (const x of s.marks) { if (x[0] <= m.index) mk = x; else break; }
      const t = mk ? mk[1] + (m.index - mk[0]) * msPerChar[s.engine]
        : s.start + (m.index / Math.max(1, s.text.length)) * dur;
      if (t > stopAt || t > t1) break;
      if (t >= t0) out.push(m[0]);
    }
  }
  return out;
}

function audioEl() {
  if (!el) el = new Audio();
  return el;
}

/** Loa có đang phát tiếng AI ngay lúc này không. Bộ nhận giọng dùng để NÂNG ngưỡng
 *  trong lúc đọc, vì mic hứng lại tiếng của chính AI (nhất là máy tính dùng loa
 *  ngoài) và tiếng đó cũng là giọng nói liên tục nên không thể lọc bằng thời lượng. */
export function isSpeaking() {
  if (el && !el.paused && !el.ended) return true;
  const ss = window.speechSynthesis;
  return !!ss && ss.speaking && !ss.paused && !!synth && !synth.paused;
}

export function currentSpeechText() { return curText; }

/**
 * Chen ngang "mềm" (nhánh Gemini Live): TẠM DỪNG thay vì stop, để nếu hoá ra báo
 * nhầm (ho, tiếng xe, tiếng AI vọng lại) thì đọc tiếp đúng chỗ đang đọc. Trả true
 * nếu thật sự có tiếng đang phát để dừng.
 *
 * PHẢI im tiếng AI ngay: đo trên Gemini thật, khi tiếng AI còn chạy song song thì
 * lời người dùng có lúc bị nuốt mất hẳn khỏi bản chép -> không bao giờ xác nhận
 * được là chen ngang.
 */
export function pauseSpeech() {
  if (el && !el.paused && !el.ended) {
    try {
      el.pause();
      pausedKind = 'audio';
      if (curSeg) curSeg.pausedAt = now();
      return true;
    } catch (e) {}
  }
  // speechSynthesis.pause() không tin được (Android: không chạy; giọng Google online
  // trên Chrome: hay không resume). Nên tự làm: huỷ, nhớ đang đọc tới từ nào (sự kiện
  // boundary; không có thì đầu câu), lúc resume đọc lại từ đúng chỗ đó.
  if (synth && !synth.paused && !synth.settled) {
    synth.paused = true;
    synth.gen++;                     // utterance cũ bắn onerror('interrupted') -> bỏ qua
    clearTimeout(synth.guard);
    segEnd(false);
    try { window.speechSynthesis.cancel(); } catch (e) {}
    pausedKind = 'synth';
    return true;
  }
  return false;
}

/** Đọc tiếp sau pauseSpeech() (chỉ khi chưa bị stop()/speak() mới thay thế). */
export function resumeSpeech() {
  const kind = pausedKind;
  pausedKind = null;
  if (kind === 'audio' && el && el.paused && !el.ended && el.currentTime > 0) {
    if (curSeg && curSeg.pausedAt != null) { curSeg.start += now() - curSeg.pausedAt; curSeg.pausedAt = null; }
    el.play().catch(() => {});
    return;
  }
  if (kind === 'synth' && synth && synth.paused && !synth.settled) {
    synth.paused = false;
    synthQueue(synth, synth.idx, synth.charAt);
    synth.armGuard();
  }
}

// Call from a user gesture (login / tap) to unlock audio + speech on mobile.
export function unlockAudio() {
  try { initSharedAudioContext(); } catch (e) {} // Unlock mic context for mobile barge-in
  try {
    const a = audioEl();
    a.muted = true;
    const p = a.play();
    if (p && p.then) p.then(() => { try { a.pause(); a.currentTime = 0; } catch (e) {} a.muted = false; })
                       .catch(() => { a.muted = false; });
  } catch (e) {}
  if (window.speechSynthesis) {
    try { window.speechSynthesis.resume(); } catch (e) {}
    // iOS chỉ cho speechSynthesis nói nếu lần đầu nằm trong cú chạm -> nói một câu câm.
    if (!synthPrimed) {
      try {
        const u = new SpeechSynthesisUtterance(' ');
        u.volume = 0;
        window.speechSynthesis.speak(u);
        synthPrimed = true;
      } catch (e) {}
    }
  }
}

/**
 * speak(text, { onStart })
 * onStart chạy đúng lúc LOA BẮT ĐẦU PHÁT, không phải lúc gửi request. Khác nhau
 * đáng kể: TTS mất 0.4-2.7s mới ra tiếng, nên ai đếm thời gian từ lúc gọi speak()
 * sẽ lệch mất khoảng đó (dùng để tính lúc nào mới cho phép ngắt lời).
 */
export async function speak(text, opts = {}) {
  // KHÔNG gọi stop() ở đây: stop() làm removeAttribute('src') + load(), rồi mình gán
  // src mới ngay sau đó -> trình duyệt huỷ play() với AbortError ("interrupted by a
  // new load request"). Trên máy tính điều này làm câu trả lời im lặng ngẫu nhiên.
  // Chỉ cần vô hiệu lượt cũ + tạm dừng là đủ.
  const my = ++genToken;
  pausedKind = null;
  if (!text) return;
  curText = text;
  segEnd(false);
  const a = audioEl();
  try { a.pause(); } catch (e) {}
  const ss = window.speechSynthesis;
  const synthBusy = !!ss && (ss.speaking || ss.pending);
  endSynth();
  if (ss) { try { ss.cancel(); } catch (e) {} }

  if (ttsEngine === 'browser' && (viVoice || pickViVoice())) {
    // Chrome hay nuốt mất speak() gọi NGAY sau cancel() -> chờ một nhịp nếu vừa huỷ.
    if (synthBusy) await new Promise((r) => setTimeout(r, 60));
    if (my !== genToken) return;
    if (await synthSpeak(text, my, opts.onStart)) return;
    if (my !== genToken) return;
    console.warn('[TTS] giong trinh duyet khong ra tieng -> doc bang Edge');
  }

  const url = `${BACKEND_URL}/api/voice/tts_stream?text=${encodeURIComponent(text)}`;

  return new Promise((resolve) => {
    if (my !== genToken) { resolve(); return; }
    let settled = false;
    let started = false;      // loa đã ra tiếng cho lượt này chưa
    const done = () => { if (!settled) { settled = true; resolve(); } };
    // Không đọc được bằng file thì phải đọc bằng giọng trình duyệt, KHÔNG được coi
    // như đã đọc xong: bản trước nuốt lỗi play() rồi resolve luôn, nên lỗi biểu hiện
    // ra ngoài đúng kiểu "im lặng, không báo gì".
    const fallback = (why) => {
      if (settled || my !== genToken) return;
      // Nếu loa ĐÃ ra tiếng rồi thì đây là stream đứt giữa đường (câu dài -> stream
      // dài -> dễ đứt). Đọc lại từ đầu bằng giọng trình duyệt là tệ hơn: người dùng
      // nghe câu đó hai lần, lần sau bằng giọng máy đọc tiếng Việt sai bét. Chỉ đọc
      // bù khi CHƯA hề ra tiếng.
      if (started) {
        console.warn('[TTS] stream dut giua duong ->', why, '| da doc duoc phan dau, KHONG doc lai');
        done();
        return;
      }
      console.warn('[TTS] khong ra tieng ->', why, '| doc bang giong trinh duyet');
      settled = true;
      synthSpeak(text, my, opts.onStart).then(() => resolve());
    };

    a.onplaying = () => {
      if (my !== genToken) return;          // đã bị speak() mới thay thế
      if (!started) segStart(text, 'edge');
      started = true;
      try { opts.onStart?.(); } catch (e) {}
    };
    a.onended = () => { if (my === genToken) segEnd(true); done(); };
    a.onerror = () => {
      // stop() làm removeAttribute('src') + load(), việc đó bắn một sự kiện 'error'
      // KHÔNG ĐỒNG BỘ (empty src). Nó tới sau khi speak() mới đã gắn handler + gán
      // src, nên bị hiểu là "file hỏng" và rơi xuống giọng trình duyệt một cách oan.
      // Chỉ coi là lỗi thật khi src đang trỏ đúng URL của lượt này.
      const cur = a.currentSrc || a.src || '';
      if (!cur || !cur.includes('tts_stream')) {
        console.warn('[TTS] bo qua error cu (empty src), khong fallback');
        return;
      }
      fallback('audio error');
    };
    a.muted = false;
    a.src = url;

    const pr = a.play();
    if (pr && pr.catch) {
      pr.catch((err) => {
        const name = err && err.name;
        // AbortError = có lệnh load/pause chen ngang. Thử lại MỘT lần sau một nhịp
        // thay vì bỏ luôn — đây chính là ca "lúc đọc lúc không".
        if (name === 'AbortError' && my === genToken) {
          setTimeout(() => {
            if (settled || my !== genToken) return;
            a.play().catch((e2) => fallback(e2 && e2.name));
          }, 80);
          return;
        }
        fallback(name || 'play() rejected');
      });
    }
  });
}

export function browserSpeak(text) {
  return synthSpeak(text, genToken, null).then(() => {});
}

// Chrome tự cắt utterance đọc quá ~15s -> đọc TỪNG CÂU (hàng đợi của speechSynthesis
// tự nối liền), câu quá dài thì cắt tiếp ở dấu phẩy.
function splitForSynth(text) {
  const out = [];
  for (const s of String(text).split(/(?<=[.!?…])\s+/)) {
    if (!s.trim()) continue;
    if (s.length <= 180) { out.push(s); continue; }
    let cur = '';
    for (const part of s.split(/(?<=,)\s+/)) {
      if (cur && (cur.length + part.length + 1) > 180) { out.push(cur); cur = part; }
      else cur = cur ? `${cur} ${part}` : part;
    }
    if (cur) out.push(cur);
  }
  return out;
}

/** Kết thúc lượt speechSynthesis hiện tại (bị stop()/speak() mới thay): trả kết quả cho bên đang chờ. */
function endSynth() {
  const st = synth;
  if (!st) return;
  st.gen++;
  st.finish(true);
}

/**
 * Đọc bằng speechSynthesis. Resolve(true) khi đọc xong (hoặc bị stop()/speak() mới
 * cắt ngang), resolve(false) khi KHÔNG ra được tiếng nào -> bên gọi tự đọc bằng Edge.
 * Luôn resolve: Chrome thỉnh thoảng không bắn onend, mà chuỗi đọc PIN đang
 * `.then(() => speak(...))` -> không có hạn chờ là treo luôn, khách không nghe PIN.
 * Tạm dừng/đọc tiếp KHÔNG làm promise này kết thúc (xem pauseSpeech).
 */
function synthSpeak(text, my, onStart) {
  return new Promise((resolve) => {
    const ss = window.speechSynthesis;
    const parts = ss ? splitForSynth(text) : [];
    if (!parts.length) { resolve(!!ss); return; }
    const st = {
      parts, idx: 0, charAt: 0, my, onStart, gen: 0,
      started: false, settled: false, paused: false, guard: null, noStart: null,
    };
    st.finish = (ok) => {
      if (st.settled) return;
      st.settled = true;
      clearTimeout(st.guard); clearTimeout(st.noStart);
      if (synth === st) synth = null;
      resolve(ok);
    };
    st.armGuard = () => {
      clearTimeout(st.guard);
      const rest = st.parts.slice(st.idx).join(' ').length - st.charAt;
      st.guard = setTimeout(() => st.finish(true), 4000 + Math.max(0, rest) * 120);
    };
    st.armGuard();
    // Không ra tiếng sau 2.5s (speak() bị nuốt, engine treo) -> huỷ, cho bên gọi đọc Edge.
    st.noStart = setTimeout(() => {
      if (st.started || st.settled) return;
      st.gen++;
      st.finish(false);   // TRƯỚC cancel(): cancel bắn onerror('interrupted') -> sẽ thành "đã đọc xong"
      try { ss.cancel(); } catch (e) {}
    }, 2500);
    synth = st;
    synthQueue(st, 0, 0);
  });
}

/** Xếp hàng các câu từ câu `idx`, ký tự `charAt` trở đi (charAt > 0 khi đọc tiếp sau tạm dừng). */
function synthQueue(st, idx, charAt) {
  const ss = window.speechSynthesis;
  const gen = ++st.gen;
  const voice = viVoice || pickViVoice();
  for (let i = idx; i < st.parts.length; i++) {
    const base = i === idx ? charAt : 0;
    const text = st.parts[i].slice(base);
    if (!text.trim()) { if (i === st.parts.length - 1) st.finish(true); continue; }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'vi-VN';
    if (voice) u.voice = voice;
    u.rate = 1.0;
    u.onstart = () => {
      if (gen !== st.gen || st.settled) return;
      st.idx = i; st.charAt = base;
      segStart(text, 'browser');
      if (!st.started) {
        st.started = true;
        clearTimeout(st.noStart);
        if (st.my === genToken) { try { st.onStart?.(); } catch (e) {} }
      }
    };
    // Nhớ đang đọc tới từ nào -> tạm dừng xong đọc tiếp đúng từ đó, không đọc lại cả câu.
    u.onboundary = (e) => {
      if (gen !== st.gen || (e.name && e.name !== 'word')) return;
      st.charAt = base + (e.charIndex || 0);
      if (curSeg) curSeg.marks.push([e.charIndex || 0, now()]);   // giờ thật của từ này
    };
    u.onend = () => {
      if (gen !== st.gen || st.settled) return;
      segEnd(true);
      if (i === st.parts.length - 1) st.finish(true);
    };
    // interrupted/canceled = bị stop()/speak() mới cắt -> coi như xong, không đọc bù.
    u.onerror = (e) => {
      if (gen !== st.gen) return;
      segEnd(false);
      st.finish(st.started || e.error === 'interrupted' || e.error === 'canceled');
    };
    ss.speak(u);
  }
}

export function stop() {
  console.log('[TTS] stop() called. Halting audio playback.');
  genToken++;   // invalidate any in-flight speak()
  pausedKind = null;
  segEnd(false);
  if (el) {
    try {
      // CHỈ pause. Trước đây còn removeAttribute('src') + load() để cắt hẳn kết nối
      // stream, nhưng load() trên src rỗng bắn ra sự kiện 'error' không đồng bộ, đến
      // sau khi lượt speak() kế tiếp đã gắn handler -> lượt đó bị fallback oan sang
      // giọng trình duyệt. pause() là đủ để im tiếng ngay, và speak() sau đó gán src
      // mới nên stream cũ tự bị thay thế.
      el.pause();
      el.currentTime = 0;
    } catch (e) {}
  }
  endSynth();
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

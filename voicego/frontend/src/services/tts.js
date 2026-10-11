import { BACKEND_URL } from './config';
import { initSharedAudioContext } from './voiceRecorder';

// ONE reusable audio element. Mobile blocks audio started outside a user gesture;
// by reusing a single element that got unlocked by the greeting (played right
// after the user's tap), later socket-triggered speech (driver arrived, PIN)
// can still play. (A fresh `new Audio()` each time would be blocked on mobile.)
let el = null;
let genToken = 0;   // only the LATEST speak() is allowed to play (no overlap)
let curText = '';   // câu AI đang đọc — nhánh Gemini Live dùng để lọc tiếng vọng khi chen ngang
let softPaused = false;
let synthPrimed = false;

// ── Giọng đọc: 'browser' (mặc định) = speechSynthesis của trình duyệt (Chrome: Google
// Tiếng Việt, Edge: Microsoft HoaiMy) — ra tiếng gần như NGAY vì không đi qua server;
// 'edge' = Edge TTS qua backend (~0.9-2.7s mới ra tiếng). Máy không có giọng vi thì
// nhánh 'browser' tự đọc bằng Edge (đọc tiếng Việt bằng giọng Anh thì nghe không hiểu).
let ttsEngine = 'browser';
export function setTtsEngine(v) { ttsEngine = v === 'edge' ? 'edge' : 'browser'; }

// Android Chrome: speechSynthesis.pause() không chạy (giọng vẫn đọc tiếp hoặc bị huỷ
// hẳn) -> không tạm dừng được, xem pauseSpeech().
const IS_ANDROID = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent);
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
  return !!ss && ss.speaking && !ss.paused;
}

export function currentSpeechText() { return curText; }

/**
 * Chen ngang "mềm" (nhánh Gemini Live): TẠM DỪNG thay vì stop, để nếu hoá ra báo
 * nhầm (ho, tiếng xe, tiếng AI vọng lại) thì đọc tiếp đúng chỗ đang đọc. Trả true
 * nếu thật sự có tiếng đang phát để dừng.
 */
export function pauseSpeech() {
  if (isSpeaking()) { try { el.pause(); softPaused = true; return true; } catch (e) {} }
  if (window.speechSynthesis?.speaking && !window.speechSynthesis.paused) {
    // Android không pause được: cứ để AI đọc tiếp, nhưng vẫn báo "đã tạm dừng" để bên
    // gọi chờ Gemini xác nhận lời thật rồi mới stop hẳn — tiếng AI vọng vào mic bị
    // lọc nhờ so với câu đang đọc, báo nhầm thì AI chưa từng bị ngắt.
    if (IS_ANDROID) { softPaused = true; return true; }
    try { window.speechSynthesis.pause(); softPaused = true; return true; } catch (e) {}
  }
  return false;
}

/** Đọc tiếp sau pauseSpeech() (chỉ khi chưa bị stop()/speak() mới thay thế). */
export function resumeSpeech() {
  if (!softPaused) return;
  softPaused = false;
  if (el && el.paused && !el.ended && el.currentTime > 0) { el.play().catch(() => {}); return; }
  if (window.speechSynthesis?.paused) { try { window.speechSynthesis.resume(); } catch (e) {} }
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
  softPaused = false;
  if (!text) return;
  curText = text;
  const a = audioEl();
  try { a.pause(); } catch (e) {}
  const ss = window.speechSynthesis;
  const synthBusy = !!ss && (ss.speaking || ss.pending);
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
      started = true;
      try { opts.onStart?.(); } catch (e) {}
    };
    a.onended = done;
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

/**
 * Đọc bằng speechSynthesis. Resolve(true) khi đọc xong (hoặc bị stop()/speak() mới
 * cắt ngang), resolve(false) khi KHÔNG ra được tiếng nào -> bên gọi tự đọc bằng Edge.
 * Luôn resolve: Chrome thỉnh thoảng không bắn onend, mà chuỗi đọc PIN đang
 * `.then(() => speak(...))` -> không có hạn chờ là treo luôn, khách không nghe PIN.
 */
function synthSpeak(text, my, onStart) {
  return new Promise((resolve) => {
    const ss = window.speechSynthesis;
    const parts = ss ? splitForSynth(text) : [];
    if (!parts.length) { resolve(!!ss); return; }
    let settled = false;
    let started = false;
    let guard = null;
    let noStart = null;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      clearTimeout(guard); clearTimeout(noStart);
      resolve(ok);
    };
    guard = setTimeout(() => finish(true), 4000 + String(text).length * 120);
    // Không ra tiếng sau 2.5s (speak() bị nuốt, engine treo) -> huỷ, cho bên gọi đọc Edge.
    noStart = setTimeout(() => {
      if (started || settled) return;
      finish(false);   // TRƯỚC cancel(): cancel bắn onerror('interrupted') -> sẽ thành "đã đọc xong"
      try { ss.cancel(); } catch (e) {}
    }, 2500);
    const voice = viVoice || pickViVoice();
    parts.forEach((p, i) => {
      const u = new SpeechSynthesisUtterance(p);
      u.lang = 'vi-VN';
      if (voice) u.voice = voice;
      u.rate = 1.0;
      u.onstart = () => {
        if (started) return;
        started = true;
        clearTimeout(noStart);
        if (my === genToken) { try { onStart?.(); } catch (e) {} }
      };
      u.onend = () => { if (i === parts.length - 1) finish(true); };
      // interrupted/canceled = bị stop()/speak() mới cắt -> coi như xong, không đọc bù.
      u.onerror = (e) => finish(started || e.error === 'interrupted' || e.error === 'canceled');
      ss.speak(u);
    });
  });
}

export function stop() {
  console.log('[TTS] stop() called. Halting audio playback.');
  genToken++;   // invalidate any in-flight speak()
  softPaused = false;
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
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

import { BACKEND_URL } from './config';
import { initSharedAudioContext } from './voiceRecorder';

// ONE reusable audio element. Mobile blocks audio started outside a user gesture;
// by reusing a single element that got unlocked by the greeting (played right
// after the user's tap), later socket-triggered speech (driver arrived, PIN)
// can still play. (A fresh `new Audio()` each time would be blocked on mobile.)
let el = null;
let genToken = 0;   // only the LATEST speak() is allowed to play (no overlap)

function audioEl() {
  if (!el) el = new Audio();
  return el;
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
  if (window.speechSynthesis) { try { window.speechSynthesis.resume(); } catch (e) {} }
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
  if (!text) return;
  const a = audioEl();
  try { a.pause(); } catch (e) {}
  if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }

  const url = `${BACKEND_URL}/api/voice/tts_stream?text=${encodeURIComponent(text)}`;

  return new Promise((resolve) => {
    if (my !== genToken) { resolve(); return; }
    let settled = false;
    const done = () => { if (!settled) { settled = true; resolve(); } };
    // Không đọc được bằng file thì phải đọc bằng giọng trình duyệt, KHÔNG được coi
    // như đã đọc xong: bản trước nuốt lỗi play() rồi resolve luôn, nên lỗi biểu hiện
    // ra ngoài đúng kiểu "im lặng, không báo gì".
    const fallback = (why) => {
      if (settled || my !== genToken) return;
      console.warn('[TTS] phat file that bai ->', why, '| doc bang giong trinh duyet');
      settled = true;
      browserSpeak(text).then(resolve);
    };

    a.onplaying = () => {
      if (my !== genToken) return;          // đã bị speak() mới thay thế
      try { opts.onStart?.(); } catch (e) {}
    };
    a.onended = done;
    a.onerror = () => fallback('audio error');
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
  return new Promise((resolve) => {
    if (!window.speechSynthesis) { resolve(); return; }
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = 'vi-VN';
    utter.rate = 1.0;
    const voices = window.speechSynthesis.getVoices();
    const viVoice = voices.find(v => v.lang.startsWith('vi'));
    if (viVoice) utter.voice = viVoice;
    utter.onend = resolve;
    utter.onerror = resolve;
    window.speechSynthesis.speak(utter);
  });
}

export function stop() {
  console.log('[TTS] stop() called. Halting audio playback.');
  genToken++;   // invalidate any in-flight speak()
  if (el) { 
    try { 
      el.pause(); 
      el.currentTime = 0;
      el.removeAttribute('src');
      el.load();
    } catch (e) {} 
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

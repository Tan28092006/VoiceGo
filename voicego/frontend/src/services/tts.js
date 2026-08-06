import { BACKEND_URL } from './config';

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
  try {
    const a = audioEl();
    a.muted = true;
    const p = a.play();
    if (p && p.then) p.then(() => { try { a.pause(); a.currentTime = 0; } catch (e) {} a.muted = false; })
                       .catch(() => { a.muted = false; });
  } catch (e) {}
  if (window.speechSynthesis) { try { window.speechSynthesis.resume(); } catch (e) {} }
}

export async function speak(text) {
  stop();
  const my = genToken;
  if (!text) return;
  
  const url = `${BACKEND_URL}/api/voice/tts_stream?text=${encodeURIComponent(text)}`;
  
  return new Promise((resolve) => {
    if (my !== genToken) { resolve(); return; }
    const a = audioEl();
    const done = () => { resolve(); };
    a.onended = done;
    a.onerror = () => {
      // If streaming fails, fallback to browser TTS
      browserSpeak(text).then(resolve);
    };
    a.muted = false;
    a.src = url;
    const pr = a.play();
    if (pr && pr.catch) pr.catch(() => done());
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
  genToken++;   // invalidate any in-flight speak()
  if (el) { try { el.pause(); } catch (e) {} }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

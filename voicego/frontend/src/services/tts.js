import { textToSpeech } from './api';

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
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const blob = await textToSpeech(text);
      if (my !== genToken) return;            // a newer speak() superseded this
      if (blob && blob.size > 0) {
        const url = URL.createObjectURL(blob);
        return new Promise((resolve) => {
          if (my !== genToken) { URL.revokeObjectURL(url); resolve(); return; }
          const a = audioEl();
          const done = () => { URL.revokeObjectURL(url); resolve(); };
          a.onended = done;
          a.onerror = done;
          a.muted = false;
          a.src = url;
          const pr = a.play();
          if (pr && pr.catch) pr.catch(() => done());
        });
      }
    } catch (e) {
      if (my !== genToken) return;
      console.warn(`TTS attempt ${attempt + 1} failed:`, e);
    }
  }
  if (my === genToken) return browserSpeak(text);
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

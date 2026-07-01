// beacon.js — "find each other" locator for the last few metres.
//
// A blind rider can't spot their car; the sighted driver can't pick the rider
// out of a crowd. So the RIDER's phone becomes a beacon: a bright strobe the
// driver can SEE + a distinctive chirp the driver can HEAR + haptic buzz. The
// rider stays put in a safe spot (we never steer them into traffic); the driver
// homes in. Tempo speeds up as the driver gets closer (setBeaconIntensity).
//
// All web-only (PWA), no native app. Screen strobe + Web Audio work everywhere;
// vibration is Android-only (silently ignored elsewhere).

let overlay = null;
let audioCtx = null;
let loopTimer = null;
let running = false;
let periodMs = 850;     // strobe/beep period; shrinks as the driver approaches
let flashOn = false;

function ensureOverlay() {
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.setAttribute('aria-hidden', 'true');
  Object.assign(overlay.style, {
    position: 'fixed', inset: '0', zIndex: '2147483647',
    background: '#ffffff', opacity: '0', pointerEvents: 'none',
    transition: 'opacity 80ms linear',
  });
  document.body.appendChild(overlay);
  return overlay;
}

// One short two-tone chirp — recognisable and attention-grabbing.
function chirp() {
  if (!audioCtx) return;
  const now = audioCtx.currentTime;
  const gain = audioCtx.createGain();
  gain.connect(audioCtx.destination);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.9, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);
  const o = audioCtx.createOscillator();
  o.type = 'square';
  o.frequency.setValueAtTime(1100, now);
  o.frequency.setValueAtTime(1550, now + 0.14);   // jump to a second tone
  o.connect(gain);
  o.start(now);
  o.stop(now + 0.3);
}

function tick() {
  if (!running) return;
  const ov = ensureOverlay();
  flashOn = !flashOn;
  ov.style.background = flashOn ? '#ffffff' : '#00b14f';  // white ↔ Grab green
  ov.style.opacity = flashOn ? '1' : '0.15';
  if (flashOn) {
    chirp();
    if (navigator.vibrate) { try { navigator.vibrate(180); } catch (e) {} }
  }
  loopTimer = setTimeout(tick, periodMs);
}

export function startBeacon() {
  if (running) return;
  running = true;
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
  } catch (e) { audioCtx = null; }
  ensureOverlay();
  tick();
}

// Map driver→rider distance (metres) to strobe/beep tempo. Closer = faster.
export function setBeaconIntensity(meters) {
  if (!Number.isFinite(meters)) return;
  if (meters > 50) periodMs = 850;
  else if (meters > 25) periodMs = 600;
  else if (meters > 12) periodMs = 380;
  else if (meters > 5) periodMs = 220;
  else periodMs = 130;                    // basically on top of each other
}

export function stopBeacon() {
  running = false;
  if (loopTimer) { clearTimeout(loopTimer); loopTimer = null; }
  if (overlay) { overlay.style.opacity = '0'; }
  if (audioCtx) { try { audioCtx.close(); } catch (e) {} audioCtx = null; }
  periodMs = 850;
  flashOn = false;
}

export function isBeaconRunning() {
  return running;
}

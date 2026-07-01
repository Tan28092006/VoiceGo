import { BACKEND_URL } from './config';  // '' = same-origin (dev) | URL Render (prod)

export async function checkHealth() {
  const res = await fetch(`${BACKEND_URL}/api/health`);
  return res.json();
}

export async function speechToText(audioBlob, filename = 'audio.wav', engine = '') {
  const form = new FormData();
  form.append('file', audioBlob, filename);
  const qs = engine ? `?engine=${encodeURIComponent(engine)}` : '';
  const res = await fetch(`${BACKEND_URL}/api/voice/stt${qs}`, { method: 'POST', body: form });
  const data = await res.json();
  return data.text;
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

export async function agentChat(messages) {
  const res = await fetch(`${BACKEND_URL}/api/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  });
  return res.json();
}

export async function searchPlaces(query) {
  const res = await fetch(`${BACKEND_URL}/api/places/search?q=${encodeURIComponent(query)}`);
  return res.json();
}

export async function geocode(address) {
  const res = await fetch(`${BACKEND_URL}/api/geocode?address=${encodeURIComponent(address)}`);
  return res.json();
}

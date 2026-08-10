import { BACKEND_URL } from './config';  // '' = same-origin (dev) | URL Render (prod)

export async function checkHealth() {
  const res = await fetch(`${BACKEND_URL}/api/health`);
  return res.json();
}

// Trả cả {text, error}: 'error' có nghĩa Whisper THẬT SỰ lỗi (hết quota/mạng...),
// khác với text='' đơn thuần (chỉ là im lặng/nhiễu, Whisper vẫn chạy bình thường).
// Caller dùng 'error' để biết khi nào nên lùi sang Web Speech API của trình duyệt.
export async function speechToText(audioBlob, filename = 'audio.wav') {
  const form = new FormData();
  form.append('file', audioBlob, filename);
  const res = await fetch(`${BACKEND_URL}/api/voice/stt`, { method: 'POST', body: form });
  const data = await res.json();
  return { text: data.text || '', error: data.error || null };
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

export async function searchPlaces(query) {
  const res = await fetch(`${BACKEND_URL}/api/places/search?q=${encodeURIComponent(query)}`);
  return res.json();
}

export async function geocode(address) {
  const res = await fetch(`${BACKEND_URL}/api/geocode?address=${encodeURIComponent(address)}`);
  return res.json();
}

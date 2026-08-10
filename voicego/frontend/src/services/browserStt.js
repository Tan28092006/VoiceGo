/**
 * Web Speech API (SpeechRecognition) — nhận diện giọng nói MIỄN PHÍ, chạy ngay
 * trong trình duyệt, không qua server, không tốn quota của mình. Dùng làm lưới
 * đỡ khi Whisper (Groq) lỗi/hết quota — trước đây lưới đỡ là FPT nhưng FPT hết
 * dùng được (hết quota, không nạp lại).
 *
 * Khác với Whisper: không thể đưa audio ĐÃ ghi vào đây, phải NGHE TRỰC TIẾP qua
 * mic (browser tự quản lý VAD riêng của nó) — nên chỉ gọi khi Whisper thật sự lỗi
 * (có `error`), không gọi khi Whisper chạy ổn nhưng chỉ là im lặng/nhiễu (lúc đó
 * nghe lại qua đường ghi âm cũ vẫn đúng hơn).
 *
 * Độ phủ: Chrome/Edge (desktop + Android) hỗ trợ tốt; Safari/iOS gần như không.
 */
export function isBrowserSttSupported() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export function browserRecognize(lang = 'vi-VN', timeoutMs = 8000) {
  return new Promise((resolve) => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { resolve(''); return; }

    const rec = new SR();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;

    let done = false;
    let timer = null;
    const finish = (text) => {
      if (done) return;
      done = true;
      if (timer) clearTimeout(timer);
      try { rec.stop(); } catch (e) {}
      resolve(text || '');
    };

    rec.onresult = (e) => finish(e.results?.[0]?.[0]?.transcript || '');
    rec.onerror = () => finish('');
    rec.onend = () => finish('');
    timer = setTimeout(() => finish(''), timeoutMs);

    try { rec.start(); } catch (e) { finish(''); }
  });
}

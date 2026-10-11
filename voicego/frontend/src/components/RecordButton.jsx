import React from 'react';

// Small round mic FAB. Tap to start; tap while talking = "done", sends right away
// (no wait for silence). Resumes the SAME conversation (no restart from greeting).
// `voiceActive` = mic đang THỰC SỰ nghe thấy giọng (VAD vượt ngưỡng) -> đổi hẳn
// hình dạng nút để nhìn là biết, khỏi phải mở console trên điện thoại.
export default function RecordButton({ onToggle, recording, voiceActive }) {
  return (
    <button
      type="button"
      className={`record-fab ${recording ? 'recording' : ''} ${voiceActive ? 'hearing' : ''}`}
      onClick={onToggle}
      aria-label={voiceActive ? 'Đang nghe thấy giọng bạn' : (recording ? 'Đang nghe — chạm để gửi' : 'Chạm để nói')}
    >
      {voiceActive ? (
        <span className="mic-wave" aria-hidden="true"><i /><i /><i /><i /></span>
      ) : (
        <span className="mic-icon" aria-hidden="true">🎙️</span>
      )}
    </button>
  );
}

import React from 'react';

// Small round mic FAB. Tap to start, tap again to stop — resumes the SAME
// conversation (it does not restart the agent from the greeting).
export default function RecordButton({ onToggle, recording }) {
  return (
    <button
      type="button"
      className={`record-fab ${recording ? 'recording' : ''}`}
      onClick={onToggle}
      aria-label={recording ? 'Đang nghe — chạm để dừng' : 'Chạm để nói'}
    >
      <span className="mic-icon" aria-hidden="true">🎙️</span>
    </button>
  );
}

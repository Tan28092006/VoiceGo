import React from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/LiveTranscript.css';

export default function LiveTranscript() {
  const { state } = useApp();
  // Nghe thấy giọng nhưng chưa có chữ (STT chưa trả về) -> vẫn báo bằng chữ xanh
  // để người dùng biết máy đang bắt được tiếng mình, giống lúc tới lượt mình nói.
  if (!state.transcript && !state.voiceActive) return null;
  return (
    <div className={`live-transcript ${state.voiceActive ? 'hearing' : ''}`} aria-hidden="true">
      {state.transcript ? `"${state.transcript}"` : 'Đang nghe bạn nói…'}
    </div>
  );
}

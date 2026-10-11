import React from 'react';
import { useApp, saveSttEngine } from '../context/AppContext';
import '../styles/components/Header.css';

export default function Header({ onBack }) {
  const { state, dispatch } = useApp();
  const live = state.sttEngine === 'gemini-live';
  // Cờ chọn nhánh STT: Whisper (mặc định, gửi file) <-> Gemini Live (stream WebSocket).
  const toggleStt = () => {
    const next = live ? 'whisper' : 'gemini-live';
    saveSttEngine(next);
    dispatch({ type: 'SET_STT_ENGINE', payload: next });
  };
  return (
    <header className="voice-header">
      <div className="voice-title">
        {onBack && (
          <button className="voice-back" onClick={onBack} aria-label="Quay lại trang chủ">←</button>
        )}
        🎙️ VoiceGo
      </div>
      <div className="voice-meta">
        <button
          type="button"
          className={`stt-toggle ${live ? 'live' : ''}`}
          onClick={toggleStt}
          aria-pressed={live}
          aria-label={`Nhận giọng nói: ${live ? 'Gemini Live' : 'Whisper'}. Chạm để đổi`}
        >
          {live ? '⚡ Gemini Live' : '🎧 Whisper'}
        </button>
        <span className={`backend-dot ${state.backendOnline ? 'online' : 'offline'}`}>
          {state.backendOnline ? '⚡ Trực tuyến' : '⚡ Cục bộ'}
        </span>
      </div>
    </header>
  );
}

import React from 'react';
import { useApp, saveSttEngine, saveTtsEngine } from '../context/AppContext';
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
  const edgeVoice = state.ttsEngine === 'edge';
  // Cờ chọn giọng đọc: giọng trình duyệt (mặc định, ra tiếng ngay) <-> Edge TTS (qua server).
  const toggleTts = () => {
    const next = edgeVoice ? 'browser' : 'edge';
    saveTtsEngine(next);
    dispatch({ type: 'SET_TTS_ENGINE', payload: next });
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
          className={`engine-toggle ${live ? 'live' : ''}`}
          onClick={toggleStt}
          aria-pressed={live}
          aria-label={`Nhận giọng nói: ${live ? 'Gemini Live' : 'Whisper'}. Chạm để đổi`}
        >
          {live ? '⚡ Gemini Live' : '🎧 Whisper'}
        </button>
        <button
          type="button"
          className={`engine-toggle ${edgeVoice ? '' : 'live'}`}
          onClick={toggleTts}
          aria-pressed={!edgeVoice}
          aria-label={`Giọng đọc: ${edgeVoice ? 'Edge' : 'trình duyệt'}. Chạm để đổi`}
        >
          {edgeVoice ? '🔊 Giọng Edge' : '🔊 Giọng máy'}
        </button>
        <span className={`backend-dot ${state.backendOnline ? 'online' : 'offline'}`}>
          {state.backendOnline ? '⚡ Trực tuyến' : '⚡ Cục bộ'}
        </span>
      </div>
    </header>
  );
}

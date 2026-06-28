import React from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/Header.css';

export default function Header({ onBack }) {
  const { state } = useApp();
  return (
    <header className="voice-header">
      <div className="voice-title">
        {onBack && (
          <button className="voice-back" onClick={onBack} aria-label="Quay lại trang chủ">←</button>
        )}
        🎙️ VoiceGo
      </div>
      <div className="voice-meta">
        <span className={`backend-dot ${state.backendOnline ? 'online' : 'offline'}`}>
          {state.backendOnline ? '⚡ Trực tuyến' : '⚡ Cục bộ'}
        </span>
      </div>
    </header>
  );
}

import React from 'react';
import { useApp } from '../context/AppContext';
import LiveTranscript from './LiveTranscript';
import '../styles/components/GestureZone.css';

export default function GestureZone({ onToggle }) {
  const { state } = useApp();
  return (
    <section
      className="gesture-zone"
      aria-label="Khu vực hội thoại với trợ lý — chạm để nói"
      onClick={onToggle}
      role="button"
      tabIndex={0}
    >
      <div className="status-wrap" role="status" aria-live="assertive" aria-atomic="true">
        <div className="status-main">{state.status}</div>
        {state.substatus && <div className="status-sub">{state.substatus}</div>}
      </div>
      <LiveTranscript />
      <div className="confirm-hint">
        <span className="hint-text">
          Cứ nói tự nhiên: "đồng ý" để đặt · "ô tô" / "xe ôm" để chọn xe · "huỷ" để dừng
        </span>
      </div>
    </section>
  );
}

import React from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/AgentOverlay.css';   // .agent-overlay (fixed full-screen popup)
import '../styles/components/TripOverlay.css';

export default function TripOverlay({ onDismiss }) {
  const { state } = useApp();
  const visible = state.appState === 'trip_live';

  if (!visible) return null;

  const pinDigits = state.pin ? state.pin.split('') : [];
  // 3 stages: tìm tài xế -> đã có tài xế (đang đến) -> đã đến (hiện PIN)
  const title = !state.driver
    ? '🔎 Đang tìm tài xế…'
    : (state.pin ? '🚗 Tài xế đã đến!' : '🚗 Đã có tài xế, đang đến…');
  const sub = !state.driver
    ? 'Vui lòng chờ…'
    : (state.pin ? 'Đọc mã PIN cho tài xế để xác minh' : 'Tài xế đang trên đường đến đón bạn');

  return (
    <div className="agent-overlay" role="dialog" aria-modal="true" onClick={onDismiss}>
      <div className="agent-box" onClick={(e) => e.stopPropagation()}>
        {!state.driver && <div className="agent-spinner" aria-hidden="true" />}
        <div className="agent-title">{title}</div>
        {state.driver && (
          <div className="trip-driver" role="status" aria-live="polite">
            {state.driver.name} — {state.driver.plate}
          </div>
        )}
        {pinDigits.length > 0 && (
          <div className="pin-row" role="status" aria-live="polite">
            {pinDigits.map((d, i) => (
              <span key={i} className="pin-digit">{d}</span>
            ))}
          </div>
        )}
        <div className="agent-result" role="status" aria-live="assertive">{sub}</div>
      </div>
    </div>
  );
}

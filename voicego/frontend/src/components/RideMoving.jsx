import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/RideStatus.css';

const VND = (v) => (Number.isFinite(+v) ? (+v).toLocaleString('vi-VN') + 'đ' : '—');
const initial = (name) => {
  const w = String(name || 'A').trim().split(/\s+/);
  return (w[w.length - 1][0] || 'A').toUpperCase();
};

/** RideMoving — bottom sheet over the existing map while the trip is underway. */
export default function RideMoving() {
  const { state } = useApp();
  const [collapsed, setCollapsed] = useState(false);
  const q = state.quote || {};
  const d = state.driver || {};
  const dest = state.destination || {};
  const km = q.distanceKm ?? q.distance;
  const mins = q.durationMin;
  const price = q.priceVnd ?? q.price;

  return (
    <div className={`ride-sheet ${collapsed ? 'collapsed' : ''}`} role="status" aria-live="polite">
      <button
        type="button"
        className="ride-grip"
        onClick={() => setCollapsed((c) => !c)}
        aria-label={collapsed ? 'Mở thông tin chuyến đi' : 'Thu gọn thông tin chuyến đi'}
      >
        <span className="ride-handle" aria-hidden="true" />
        <span className="ride-eyebrow">🚗 Đang di chuyển{collapsed ? ' · chạm để xem' : ' · chạm để thu gọn'}</span>
      </button>
      <h2 className="ride-title">Tài xế đang đưa bạn đến điểm đến</h2>

      <div className="ride-metrics">
        <div><span>Quãng đường</span><strong>{km != null ? `${km} km` : '—'}</strong></div>
        <div><span>Dự kiến</span><strong>{mins != null ? `${mins} phút` : '—'}</strong></div>
        <div><span>Giá</span><strong>{VND(price)}</strong></div>
      </div>

      <div className="ride-route">
        <div className="rr"><span className="rr-dot red" /><div><small>Điểm đón</small><strong>{state.origin.name}</strong></div></div>
        <div className="rr-divider" aria-hidden="true" />
        <div className="rr"><span className="rr-dot green" /><div><small>Điểm đến</small><strong>{dest.address || dest.name || '—'}</strong></div></div>
      </div>

      {d.name && (
        <div className="ride-driver">
          <div className="rd-avatar" aria-hidden="true">{initial(d.name)}</div>
          <div className="rd-info"><strong>{d.name}</strong><span>{d.plate}</span></div>
          <button className="rd-icon" type="button" aria-label="Gọi tài xế">☎</button>
          <button className="rd-icon" type="button" aria-label="Nhắn tài xế">💬</button>
        </div>
      )}

      <div className="ride-acc"><span aria-hidden="true">♿</span><p>Tài xế đã nhận thông báo hỗ trợ tiếp cận và sẽ hỗ trợ bạn khi tới nơi.</p></div>
    </div>
  );
}

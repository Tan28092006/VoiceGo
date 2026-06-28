import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/RideStatus.css';

const VND = (v) => (Number.isFinite(+v) ? (+v).toLocaleString('vi-VN') + 'đ' : '—');

/**
 * RideArrived — trip-complete overlay: summary + accessibility rating (sent to the
 * backend /api/reports so visually-impaired riders crowdsource accessibility).
 */
export default function RideArrived({ onHome }) {
  const { state } = useApp();
  const q = state.quote || {};
  const dest = state.destination || {};
  const [stars, setStars] = useState(0);
  const [accessible, setAccessible] = useState(true);
  const [sent, setSent] = useState(false);

  const km = q.distanceKm ?? q.distance;
  const mins = q.durationMin;
  const price = q.priceVnd ?? q.price;

  const submitRating = async () => {
    if (!stars || sent) return;
    try {
      await fetch('/api/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: dest.name || 'Điểm đến',
          address: dest.address || dest.name || '',
          lat: dest.lat, lng: dest.lng,
          accessibility_score: stars,
          disability_accessible_entrance: accessible,
        }),
      });
    } catch (e) { /* best-effort */ }
    setSent(true);
  };

  const finish = async () => { await submitRating(); onHome?.(); };

  return (
    <div className="ride-arrived-overlay" role="dialog" aria-modal="true">
      <div className="ride-arrived-box">
        <div className="arrived-check" aria-hidden="true">✓</div>
        <p className="ride-eyebrow center">Đã tới nơi</p>
        <h2 className="arrived-title">Chuyến đi đã hoàn tất</h2>
        <p className="arrived-sub">Cảm ơn bạn đã dùng VoiceGo. Đánh giá mức độ tiếp cận của điểm đến để hỗ trợ cộng đồng người khuyết tật.</p>

        <div className="ride-metrics">
          <div><span>Quãng đường</span><strong>{km != null ? `${km} km` : '—'}</strong></div>
          <div><span>Thời gian</span><strong>{mins != null ? `${mins} phút` : '—'}</strong></div>
          <div><span>Tổng tiền</span><strong>{VND(price)}</strong></div>
        </div>

        <div className="rating-card">
          <p className="ride-eyebrow">Điểm tiếp cận</p>
          <h3>Điểm đến này có dễ tiếp cận không?</h3>
          <div className="stars" role="group" aria-label="Chọn từ 1 đến 5 sao">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button" aria-label={`${n} sao`}
                      className={n <= stars ? 'on' : ''} onClick={() => setStars(n)}>★</button>
            ))}
          </div>
          <button type="button" className="acc-toggle" onClick={() => setAccessible((v) => !v)}>
            <span>Lối vào có dốc / dễ tiếp cận</span>
            <strong className={accessible ? 'yes' : 'no'}>{accessible ? 'Có' : 'Không'}</strong>
          </button>
          {sent && <p className="rating-thanks">✓ Cảm ơn đánh giá của bạn!</p>}
        </div>

        <button className="ride-primary" onClick={finish}>Về trang chủ</button>
      </div>
    </div>
  );
}

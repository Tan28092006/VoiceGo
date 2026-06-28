import React from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/TripInfo.css';

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v
                   : (typeof v === 'string' && v.trim() !== '' && Number.isFinite(+v) ? +v : null));
const VND = (v) => { const n = num(v); return n != null ? n.toLocaleString('vi-VN') + 'đ' : null; };

/**
 * TripInfo — overlay on the map: pickup → destination + price/distance/time.
 * Shown only when a destination/quote exists. Never renders NaN.
 */
export default function TripInfo() {
  const { state } = useApp();
  const dest = state.destination;
  const q = state.quote;
  if (!dest && !q) return null;

  const name = (q && (q.name || q.address)) || dest?.address || dest?.name || 'Điểm đến';
  const price = q ? VND(q.priceVnd ?? q.price) : null;
  const kmN = q ? num(q.distanceKm ?? q.distance) : null;
  const minsN = q ? num(q.durationMin) : null;
  const km = kmN != null ? `${kmN} km` : null;
  const mins = minsN != null ? `${minsN} phút` : null;
  const veh = q?.vehicle === 'car' ? 'Ô tô' : (q?.vehicle === 'bike' ? 'Xe máy' : null);
  const meta = [veh, km, mins].filter(Boolean).join(' · ');
  const hasQuote = !!(price || meta);

  return (
    <div className="trip-info" role="status" aria-live="polite">
      <div className="trip-info-route">
        <div className="ti-row"><span className="ti-dot red" /><span className="ti-text">{state.origin.name}</span></div>
        <div className="ti-row"><span className="ti-dot green" /><span className="ti-text strong">{name}</span></div>
      </div>
      {dest?.accessible && (
        <div className="ti-access">♿ Điểm đến dễ tiếp cận cho người khiếm thị</div>
      )}
      {hasQuote && (
        <div className="trip-info-quote">
          {price && <span className="ti-price">{price}</span>}
          {meta && <span className="ti-meta">{meta}</span>}
        </div>
      )}
    </div>
  );
}

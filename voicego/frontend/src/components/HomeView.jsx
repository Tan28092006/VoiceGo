import React from 'react';
import '../styles/components/HomeView.css';

/**
 * HomeView — Grab-like landing screen (after login). The voice-search bar and the
 * Xe máy / Ô tô tiles start the voice booking agent. `onBook(vehicle)` switches to
 * the voice screen (optionally pre-selecting a vehicle).
 */
export default function HomeView({ user, onBook }) {
  const services = [
    { icon: '🛵', label: 'Xe máy', active: true, onClick: () => onBook('bike') },
    { icon: '🚕', label: 'Ô tô', active: true, onClick: () => onBook('car') },
    { icon: '🚙', label: 'Đặt trước' },
    { icon: '📦', label: 'Giao hàng' },
    { icon: '🍔', label: 'Đồ ăn' },
    { icon: '🍽️', label: 'Đi Ăn' },
    { icon: '🛍️', label: 'Đi chợ' },
    { icon: '🎁', label: 'Quà tặng' },
  ];

  return (
    <div className="home-shell">
      <main className="app-shell" aria-label="Trang chủ VoiceGo">
        <section className="hero-band">
          <div className="hero-greeting">Xin chào{user?.full_name ? `, ${user.full_name}` : ''} 👋</div>
          <button
            type="button"
            className="voice-search"
            onClick={() => onBook()}
            aria-label="Đặt chuyến xe bằng giọng nói"
          >
            <span className="search-icon" aria-hidden="true">🎙️</span>
            <span>Đặt chuyến bằng giọng nói</span>
          </button>
        </section>

        <section className="services" aria-label="Dịch vụ">
          {services.map((s) => (
            <button
              key={s.label}
              type="button"
              className={`service-item ${s.active ? 'active' : ''}`}
              onClick={s.onClick}
              aria-label={s.label}
            >
              <span className="service-icon">{s.icon}</span>
              <span>{s.label}</span>
            </button>
          ))}
        </section>

        <div className="pager" aria-hidden="true">
          <span className="pager-dot active" />
          <span className="pager-dot" />
        </div>

        <section className="wallet-card" aria-label="Ví liên kết">
          <div>
            <p>Ví liên kết</p>
            <strong>Viettel Money 0…</strong>
          </div>
          <span className="wallet-badge" aria-hidden="true">▯</span>
        </section>

        <section className="promos" aria-label="Ưu đãi hôm nay">
          <h1>Ưu đãi hôm nay</h1>
          <article className="promo-card">
            <img src="https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?auto=format&fit=crop&w=900&q=80" alt="Ưu đãi đồ uống" />
          </article>
          <article className="promo-card">
            <img src="https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=900&q=80" alt="Ưu đãi món ăn" />
          </article>
        </section>
      </main>

      <nav className="bottom-nav" aria-label="Điều hướng chính">
        <a className="nav-item active" href="#" onClick={(e) => e.preventDefault()}><span>🏠</span><span>Trang chủ</span></a>
        <a className="nav-item" href="#" onClick={(e) => e.preventDefault()}><span>🧭</span><span>Khám phá</span></a>
        <a className="nav-item" href="#" onClick={(e) => e.preventDefault()}><span>👤</span><span>Profile</span></a>
        <a className="nav-item" href="#" onClick={(e) => e.preventDefault()}><span>📋</span><span>Hoạt động</span></a>
        <a className="nav-item" href="#" onClick={(e) => e.preventDefault()}><span>💬</span><span>Tin nhắn</span></a>
      </nav>
    </div>
  );
}

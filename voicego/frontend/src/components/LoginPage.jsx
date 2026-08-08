import { useState, useEffect } from "react";
import { BACKEND_URL } from "../services/config";
import "../styles/components/LoginPage.css";

function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [slow, setSlow] = useState(false);   // backend đang khởi động (cold start)
  const [pending, setPending] = useState(null);  // nút nào đang chạy -> hiện spinner đúng nút

  // Warm-up: đánh thức backend Render NGAY khi mở trang, trong lúc người dùng còn
  // đang gõ email/mật khẩu — để lúc bấm "Đăng nhập" máy chủ đã ấm sẵn.
  useEffect(() => {
    fetch(`${BACKEND_URL}/api/health`).catch(() => {});
  }, []);

  const doLogin = async (em, pw, which = "form") => {
    setError("");
    setIsLoading(true);
    setPending(which);
    setSlow(false);
    // Nếu quá 4s chưa xong -> nhiều khả năng máy chủ free đang cold-start.
    const slowTimer = setTimeout(() => setSlow(true), 4000);

    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email: em, password: pw }),
      });

      const data = await res.json();

      if (data.success) {
        onLogin(data.data);
      } else {
        setError(data.message || "Đăng nhập thất bại");
      }
    } catch (err) {
      console.error(err);
      setError("Lỗi kết nối đến máy chủ");
    } finally {
      clearTimeout(slowTimer);
      setIsLoading(false);
      setSlow(false);
      setPending(null);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    doLogin(email, password);
  };

  // Đăng nhập demo 1 chạm — không cần gõ tài khoản (dành cho người xem CV/HR).
  const quickDemo = (role) => {
    const creds = role === "driver"
      ? { em: "driver.a@example.com", pw: "password123" }
      : { em: "minhanh.voicego@example.com", pw: "password123" };
    setEmail(creds.em);
    setPassword(creds.pw);
    doLogin(creds.em, creds.pw, role);
  };

  return (
    <div className="login-container">
      <div className="login-header">
        <div className="login-logo">
          <span role="img" aria-label="Xe hơi">
            🚕
          </span>
        </div>
        <h1 className="login-title">
          Voice<span>Go</span>
        </h1>
        <p className="login-subtitle">
          Đăng nhập để tiếp tục
        </p>
      </div>

      <div className="login-form-container">
        {/* Trải nghiệm nhanh — không cần tài khoản (cho người xem CV / HR) */}
        <div style={{ marginBottom: 18 }}>
          {/* Hiện NGAY khi bấm: máy chủ Render free ngủ sau 15' nên request đầu mất
              ~30s. Trước đây chỉ có cái nút bị mờ đi, người xem tưởng app hỏng. */}
          {isLoading && (
            <div className="login-booting" role="status" aria-live="polite">
              <span className="btn-spinner dark" aria-hidden="true" />
              <div>
                <strong>Đang đánh thức máy chủ…</strong>
                <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>
                  {slow
                    ? "Máy chủ miễn phí ngủ khi không dùng — lần đầu mất ~30 giây. Bạn chờ chút nhé."
                    : "Đang kết nối, vui lòng đợi…"}
                </div>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => quickDemo("passenger")}
            disabled={isLoading}
            className="login-button"
            style={{ background: "#00b14f", marginBottom: 10 }}
          >
            {pending === "passenger" ? (
              <><span className="btn-spinner" aria-hidden="true" />Đang đánh thức máy chủ…</>
            ) : "🎙️ Dùng thử ngay — Khách khiếm thị (demo)"}
          </button>
          <button
            type="button"
            onClick={() => quickDemo("driver")}
            disabled={isLoading}
            className="login-button"
            style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.25)" }}
          >
            {pending === "driver" ? (
              <><span className="btn-spinner" aria-hidden="true" />Đang đánh thức máy chủ…</>
            ) : "🚗 Vào vai Tài xế (demo)"}
          </button>
          <p style={{ textAlign: "center", fontSize: 12, color: "#9ca3af", margin: "12px 0 0" }}>
            Không cần đăng nhập — bấm “Dùng thử ngay” để trải nghiệm đặt xe bằng giọng nói.
            Chuyến đi tự hoàn tất nếu chưa có tài xế online.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "6px 0 16px", color: "#6b7280", fontSize: 12 }}>
          <span style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
          hoặc đăng nhập
          <span style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.12)" }} />
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {error && (
            <div className="login-error">
              {error}
            </div>
          )}

          {slow && !error && (
            <div className="login-error" style={{ background: "#fff7ed", color: "#9a3412" }}>
              Máy chủ đang khởi động (lần đầu có thể mất ~30 giây), vui lòng đợi…
            </div>
          )}

          <div className="form-group">
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Nhập email của bạn"
              required
            />
          </div>

          <div className="form-group">
            <label>Mật khẩu</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nhập mật khẩu"
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="login-button"
          >
            {isLoading ? (slow ? "Đang khởi động máy chủ…" : "Đang xử lý...") : "Đăng Nhập"}
          </button>
        </form>
      </div>
      
      <p className="login-footer">
        Dành cho tài xế và hành khách
      </p>
    </div>
  );
}

export default LoginPage;

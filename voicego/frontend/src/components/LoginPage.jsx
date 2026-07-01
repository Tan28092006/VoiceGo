import { useState, useEffect } from "react";
import { BACKEND_URL } from "../services/config";
import "../styles/components/LoginPage.css";

function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [slow, setSlow] = useState(false);   // backend đang khởi động (cold start)

  // Warm-up: đánh thức backend Render NGAY khi mở trang, trong lúc người dùng còn
  // đang gõ email/mật khẩu — để lúc bấm "Đăng nhập" máy chủ đã ấm sẵn.
  useEffect(() => {
    fetch(`${BACKEND_URL}/api/health`).catch(() => {});
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    setSlow(false);
    // Nếu quá 4s chưa xong -> nhiều khả năng máy chủ free đang cold-start.
    const slowTimer = setTimeout(() => setSlow(true), 4000);

    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, password }),
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
    }
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

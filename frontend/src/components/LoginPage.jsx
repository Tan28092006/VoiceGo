import { useState } from "react";

function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
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
      setIsLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-10 gap-8">
      {/* ── Logo / App Title ─────────────────────────────────────────── */}
      <div className="text-center mb-4 animate-fade-in-up">
        <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-grab-green/20 mb-4">
          <span className="text-4xl" role="img" aria-label="Xe hơi">
            🚕
          </span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white">
          Grab<span className="text-grab-green">Assist</span>
        </h1>
        <p className="mt-2 text-base sm:text-lg text-gray-400 font-medium max-w-xs mx-auto">
          Đăng nhập để tiếp tục
        </p>
      </div>

      <div className="w-full max-w-md">
        <form
          onSubmit={handleSubmit}
          className="bg-surface-card p-6 sm:p-8 rounded-2xl shadow-xl border border-white/10 flex flex-col gap-6"
        >
          {error && (
            <div className="bg-danger-bg border border-danger/50 text-white p-4 rounded-xl text-center animate-shake">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-surface-elevated text-white px-5 py-4 rounded-xl border-2 border-transparent focus:border-grab-green focus:outline-none transition-colors text-lg"
              placeholder="Nhập email của bạn"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Mật khẩu
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface-elevated text-white px-5 py-4 rounded-xl border-2 border-transparent focus:border-grab-green focus:outline-none transition-colors text-lg"
              placeholder="Nhập mật khẩu"
              required
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-grab-green hover:bg-grab-green-dark active:scale-[0.97] text-white font-bold text-xl py-4 rounded-xl transition-all shadow-lg shadow-grab-green/20 mt-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? "Đang xử lý..." : "Đăng Nhập"}
          </button>
        </form>
      </div>
      
      <p className="text-xs text-gray-600 text-center mt-4 max-w-xs">
        Dành cho tài xế và hành khách
      </p>
    </div>
  );
}

export default LoginPage;

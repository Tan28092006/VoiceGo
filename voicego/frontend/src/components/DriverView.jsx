import { useState, useCallback, useEffect } from "react";
import { io } from "socket.io-client";
import { SOCKET_URL } from "../services/config";

/**
 * DriverView.jsx – PIN Verification for drivers.
 */

function DriverView({ user }) {
  const [inputPin, setInputPin] = useState("");
  // "idle" | "offered" | "accepted" | "input" | "verifying" | "success" | "error"
  const [status, setStatus] = useState("idle");
  const [socket, setSocket] = useState(null);
  const [passengerName, setPassengerName] = useState(null);
  const [accessibility, setAccessibility] = useState('');

  const PIN_LENGTH = 4;

  useEffect(() => {
    const newSocket = io(SOCKET_URL);   // dev: same-origin proxy | prod: backend Render
    setSocket(newSocket);

    newSocket.on("connect", () => newSocket.emit("driver-online", { userId: user.id }));
    newSocket.on("new-ride", (data) => {
      if (navigator.vibrate) navigator.vibrate([120, 60, 120]);
      setAccessibility(data?.accessibility || "");
      setStatus((s) => (s === "idle" ? "offered" : s));
    });
    newSocket.on("ride-confirmed", (data) => {
      setPassengerName(data?.passengerName || "Hành khách");
      if (data?.accessibility) setAccessibility(data.accessibility);
      setStatus("accepted");
    });
    newSocket.on("pin-display", (data) => {
      setPassengerName(data?.passengerName || "Hành khách");
      if (data?.accessibility) setAccessibility(data.accessibility);
      setStatus("input");
    });
    newSocket.on("pin-verified", () => {
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      setStatus("success");
    });
    newSocket.on("pin-failed", () => {
      if (navigator.vibrate) navigator.vibrate([100, 50, 100, 50, 100]);
      setStatus("error");
      setTimeout(() => { setInputPin(""); setStatus("input"); }, 1200);
    });

    return () => { newSocket.disconnect(); };
  }, [user.id]);

  const handleAccept = () => {
    if (socket) { socket.emit("driver-accept", { userId: user.id }); setStatus("accepted"); }
  };
  const handleArrive = () => {
    if (socket) socket.emit("driver-arrive", { userId: user.id });
  };

  useEffect(() => {
    if (inputPin.length === PIN_LENGTH && socket) {
      setStatus("verifying");
      socket.emit("verify-pin", { pin: inputPin });
    }
  }, [inputPin, socket]);

  const handleDigit = useCallback(
    (digit) => {
      if (inputPin.length < PIN_LENGTH && status === "input") {
        setInputPin((prev) => prev + digit);
      }
    },
    [inputPin.length, status]
  );

  const handleDelete = useCallback(() => {
    if (status === "input") {
      setInputPin((prev) => prev.slice(0, -1));
    }
  }, [status]);

  const handleComplete = useCallback(() => {
    if (socket) socket.emit("trip-completed", { userId: user.id });
    setStatus("done");
  }, [socket, user.id]);

  const handleReset = useCallback(() => {
    setInputPin("");
    setStatus("idle");
    setPassengerName(null);
    setAccessibility("");
  }, []);

  // ─── Idle / Offered / Accepted ──────────────────────────────────────────
  if (status === "idle" || status === "offered" || status === "accepted") {
    const cfg = {
      idle:     { icon: "🚕", title: "Đang chờ cuốc xe…", desc: "Sẽ báo ngay khi có khách đặt.", btn: null },
      offered:  { icon: "🔔", title: "Có cuốc xe mới!", desc: "Khách đang chờ. Nhận cuốc để bắt đầu.", btn: { label: "Nhận cuốc", on: handleAccept } },
      accepted: { icon: "🚗", title: "Đang đến đón khách", desc: passengerName ? `Hành khách: ${passengerName}` : "Đang trên đường đến điểm đón.", btn: { label: "Tôi đã đến nơi", on: handleArrive } },
    }[status];
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8">
        <div className="text-center mb-6 animate-fade-in-up">
          <div className={`w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 ${status === "offered" ? "bg-grab-yellow/20 animate-pulse" : "bg-grab-green/20"}`}>
            <span className="text-4xl" role="img" aria-hidden="true">{cfg.icon}</span>
          </div>
          <h2 className="text-2xl font-bold text-white mb-2">{cfg.title}</h2>
          <p className="text-gray-400">{cfg.desc}</p>
        </div>
        {accessibility && (status === "offered" || status === "accepted") && (
          <div className="w-full max-w-md mb-6 px-5 py-4 rounded-2xl bg-grab-yellow/15 border-2 border-grab-yellow/50 text-center animate-fade-in-up">
            <div className="text-grab-yellow font-extrabold text-lg">♿ Chuyến chở người khuyết tật</div>
            <div className="text-white/90 text-sm font-medium mt-1">{accessibility}</div>
          </div>
        )}
        {cfg.btn && (
          <button
            onClick={cfg.btn.on}
            className="w-full max-w-md bg-grab-green hover:bg-grab-green-dark active:scale-[0.97] text-white font-bold text-xl py-5 rounded-2xl transition-all shadow-lg shadow-grab-green/20"
          >
            {cfg.btn.label}
          </button>
        )}
      </div>
    );
  }

  // ─── Success State ──────────────────────────────────────────────────────
  if (status === "success") {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 gap-6">
        <div className="animate-check-pop w-28 h-28 rounded-full bg-grab-green flex items-center justify-center shadow-lg shadow-grab-green/30">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="w-16 h-16 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={3}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>

        <div className="text-center animate-fade-in-up">
          <h2 className="text-2xl sm:text-3xl font-black text-grab-green">
            Xác nhận thành công!
          </h2>
          <p className="text-lg text-white font-semibold mt-2">
            Đang chở khách đến điểm đến
          </p>
        </div>

        <div
          className="animate-fade-in-up w-full max-w-sm bg-success-bg border-2 border-success-border
                      rounded-2xl p-6"
          style={{ animationDelay: "0.2s" }}
        >
          <div className="flex items-center gap-4">
            <span className="text-3xl" role="img" aria-hidden="true">👤</span>
            <div>
              <span className="block text-xs text-gray-400 font-medium uppercase tracking-wider">
                Hành khách
              </span>
              <span className="block text-xl font-black text-white mt-0.5">
                {passengerName}
              </span>
            </div>
          </div>
        </div>

        <button
          onClick={handleComplete}
          className="animate-fade-in-up mt-2 w-full max-w-sm py-5
                     bg-grab-green hover:bg-grab-green-dark active:scale-[0.97]
                     rounded-2xl text-white font-bold text-xl
                     transition-all duration-200 cursor-pointer shadow-lg shadow-grab-green/20"
          style={{ animationDelay: "0.35s" }}
        >
          🏁 Hoàn thành chuyến đi
        </button>
      </div>
    );
  }

  // ─── Done State (trip completed) ─────────────────────────────────────────
  if (status === "done") {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 gap-6">
        <div className="w-28 h-28 rounded-full bg-grab-green/20 flex items-center justify-center">
          <span className="text-5xl" role="img" aria-hidden="true">🎉</span>
        </div>
        <div className="text-center animate-fade-in-up">
          <h2 className="text-2xl sm:text-3xl font-black text-grab-green">Chuyến đi hoàn tất</h2>
          <p className="text-lg text-white font-semibold mt-2">Cảm ơn bạn đã hỗ trợ hành khách!</p>
        </div>
        <button
          onClick={handleReset}
          className="animate-fade-in-up mt-2 px-8 py-4 min-h-[64px]
                     bg-white/10 hover:bg-white/20 active:scale-95
                     rounded-2xl text-white font-bold text-lg transition-all duration-200 cursor-pointer"
        >
          🔄 Nhận chuyến mới
        </button>
      </div>
    );
  }

  // ─── Input State (with numpad) ──────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col items-center justify-between px-4 py-6">
      <div className="animate-fade-in-up w-full max-w-md bg-surface-card rounded-2xl p-5 border border-white/10">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-grab-green/20 flex items-center justify-center shrink-0">
            <span className="text-2xl" role="img" aria-hidden="true">👤</span>
          </div>
          <div>
            <span className="block text-xs text-gray-500 font-medium">Hành khách</span>
            <span className="block text-lg font-bold text-white">{passengerName}</span>
          </div>
        </div>
        <p className="text-sm text-gray-400 mt-3">
          Yêu cầu hành khách đọc mã PIN 4 chữ số để xác minh
        </p>
        {accessibility && (
          <div className="mt-3 px-3 py-2 rounded-xl bg-grab-yellow/15 border border-grab-yellow/40">
            <div className="text-grab-yellow font-bold text-sm">♿ Chuyến chở người khuyết tật</div>
            <div className="text-white/80 text-xs mt-0.5">{accessibility}</div>
          </div>
        )}
      </div>

      <div className="flex flex-col items-center gap-3 my-6">
        <p className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Nhập mã PIN
        </p>

        <div
          className={`flex gap-4 transition-transform duration-200 ${
            status === "error" ? "animate-[shake_0.4s_ease-in-out]" : ""
          }`}
          role="status"
          aria-live="polite"
        >
          {Array.from({ length: PIN_LENGTH }).map((_, i) => {
            const filled = i < inputPin.length;
            const isError = status === "error";
            return (
              <div
                key={i}
                className={`w-16 h-20 sm:w-18 sm:h-22 flex items-center justify-center
                           rounded-2xl border-3 transition-all duration-200
                           ${
                             isError
                               ? "border-danger bg-danger/10"
                               : filled
                               ? "border-grab-green bg-grab-green/10"
                               : "border-white/20 bg-surface-elevated"
                           }`}
              >
                {filled ? (
                  <span
                    className={`text-4xl sm:text-5xl font-black tabular-nums ${
                      isError ? "text-danger" : "text-white"
                    }`}
                  >
                    {inputPin[i]}
                  </span>
                ) : (
                  <div className="w-3 h-3 rounded-full bg-white/20" />
                )}
              </div>
            );
          })}
        </div>

        {status === "error" && (
          <p className="text-danger font-bold text-sm animate-fade-in-up">
            ❌ Sai mã PIN – Vui lòng thử lại
          </p>
        )}
      </div>

      <div className="animate-fade-in-up w-full max-w-sm" style={{ animationDelay: "0.15s" }}>
        <Numpad
          onDigit={handleDigit}
          onDelete={handleDelete}
          disabled={status !== "input"}
        />
      </div>
    </div>
  );
}

function Numpad({ onDigit, onDelete, disabled }) {
  const rows = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    ["", "0", "del"],
  ];

  return (
    <div className="grid grid-cols-3 gap-2.5" role="group" aria-label="Bàn phím số">
      {rows.flat().map((key, i) => {
        if (key === "") {
          return <div key={i} />;
        }

        if (key === "del") {
          return (
            <button
              key={i}
              onClick={onDelete}
              disabled={disabled}
              aria-label="Xóa chữ số cuối"
              className="h-16 sm:h-18 flex items-center justify-center rounded-xl
                         bg-white/5 hover:bg-white/10 active:scale-95 active:bg-white/15
                         transition-all duration-150 cursor-pointer
                         disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="w-7 h-7 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M3.59 7.41A2 2 0 015 6.5h14a2 2 0 012 2v7a2 2 0 01-2 2H5a2 2 0 01-1.41-.59l-3.3-3.3a1 1 0 010-1.42l3.3-3.3z"
                />
              </svg>
            </button>
          );
        }

        return (
          <button
            key={i}
            onClick={() => onDigit(key)}
            disabled={disabled}
            aria-label={`Số ${key}`}
            className="h-16 sm:h-18 flex items-center justify-center rounded-xl
                       bg-surface-elevated hover:bg-white/15 active:scale-95 active:bg-grab-green/20
                       transition-all duration-150 cursor-pointer
                       disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums">
              {key}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default DriverView;

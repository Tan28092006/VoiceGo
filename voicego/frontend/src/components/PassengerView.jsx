import { useState, useCallback, useEffect } from "react";
import { io } from "socket.io-client";
import { SOCKET_URL } from "../services/config";

/**
 * PassengerView.jsx – PIN Display for visually impaired passengers.
 */

function PassengerView({ user }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [tripData, setTripData] = useState(null);
  const [socket, setSocket] = useState(null);
  const [status, setStatus] = useState("waiting"); // "waiting" | "pin" | "success"

  useEffect(() => {
    // Initialize socket connection
    const newSocket = io(SOCKET_URL);
    setSocket(newSocket);

    // Tell server we are waiting
    newSocket.on("connect", () => {
      newSocket.emit("passenger-waiting", { userId: user.id });
    });

    // When driver arrives and PIN is generated
    newSocket.on("driver-arrived", (data) => {
      setTripData(data);
      setStatus("pin");
    });

    // When PIN is successfully verified by driver
    newSocket.on("pin-verified", () => {
      setStatus("success");
      // Optional success haptic
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    });

    // Pre-load voices for mobile Safari/Chrome
    if (window.speechSynthesis) {
      window.speechSynthesis.getVoices();
    }

    return () => {
      newSocket.disconnect();
    };
  }, [user.id]);

  const handleSpeak = useCallback(() => {
    if (navigator.vibrate) {
      navigator.vibrate([200, 100, 200]);
    }

    try {
      if (!tripData) return;
      window.speechSynthesis.cancel(); 

      const pinSpaced = tripData.pin.split("").join(" ");
      const speech = new SpeechSynthesisUtterance(
        `Mã xác nhận của bạn là ${pinSpaced}. Tài xế ${tripData.driverName}, biển số ${tripData.licensePlate}`
      );
      speech.lang = "vi-VN";
      speech.rate = 0.85; 
      speech.pitch = 1.0;

      speech.onstart = () => setIsPlaying(true);
      
      const resetState = () => {
        setIsPlaying(false);
        clearTimeout(window.fallbackTimeout);
      };
      
      speech.onend = resetState;
      speech.onerror = resetState;

      window.currentUtterance = speech;

      window.fallbackTimeout = setTimeout(() => {
        setIsPlaying(false);
      }, 5000);

      window.speechSynthesis.speak(speech);
    } catch (error) {
      console.error("TTS Error:", error);
      setIsPlaying(false);
    }
  }, [tripData]);

  if (status === "waiting") {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8">
        <div className="animate-pulse-glow w-24 h-24 rounded-full bg-grab-green/20 flex items-center justify-center mb-6">
          <span className="text-4xl" role="img" aria-hidden="true">⏳</span>
        </div>
        <h2 className="text-xl font-bold text-white mb-2">Đang chờ tài xế...</h2>
        <p className="text-gray-400 text-center max-w-xs">
          Vui lòng đợi tài xế đến và bắt đầu chuyến đi để nhận mã PIN.
        </p>
      </div>
    );
  }

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
            Đã xác minh!
          </h2>
          <p className="text-lg text-white font-semibold mt-2">
            Chúc bạn có chuyến đi an toàn.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-between px-6 py-8">
      {/* ── Top: Trip Info ──────────────────────────────────────────── */}
      <div
        className="animate-fade-in-up w-full max-w-md bg-surface-card rounded-2xl p-5
                    border border-white/10"
      >
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Thông tin chuyến xe
        </h2>
        <div className="space-y-2.5">
          <InfoRow icon="🧑‍✈️" label="Tài xế" value={tripData.driverName} />
          <InfoRow icon="🔢" label="Biển số" value={tripData.licensePlate} highlight />
        </div>
      </div>

      {/* ── Center: Giant PIN Display ──────────────────────────────── */}
      <div className="animate-fade-in-up flex flex-col items-center gap-4 my-8" style={{ animationDelay: "0.1s" }}>
        <p className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Mã PIN xác nhận
        </p>

        <div
          className="flex gap-3 sm:gap-4"
          role="status"
          aria-live="polite"
          aria-label={`Mã PIN là ${tripData.pin.split("").join(" ")}`}
        >
          {tripData.pin.split("").map((digit, i) => (
            <div
              key={i}
              className="w-18 h-24 sm:w-22 sm:h-28 flex items-center justify-center
                         bg-grab-yellow rounded-2xl shadow-lg shadow-grab-yellow/20"
            >
              <span className="text-6xl sm:text-7xl font-black text-gray-900 tabular-nums">
                {digit}
              </span>
            </div>
          ))}
        </div>

        <p className="text-xs text-gray-500 text-center max-w-xs mt-1">
          Đọc mã PIN này cho tài xế để xác minh chuyến đi
        </p>
      </div>

      {/* ── Bottom: TTS Button ─────────────────────────────────────── */}
      <div className="animate-fade-in-up w-full max-w-md" style={{ animationDelay: "0.2s" }}>
        <button
          onClick={handleSpeak}
          disabled={isPlaying}
          aria-label="Chạm vào đây để nghe đọc mã PIN bằng giọng nói tiếng Việt"
          className={`group w-full min-h-[96px] flex items-center justify-center gap-4
                     px-6 py-6 rounded-2xl shadow-lg
                     transition-all duration-200 cursor-pointer
                     focus-visible:ring-4 focus-visible:ring-white
                     ${
                       isPlaying
                         ? "bg-grab-green/80 shadow-grab-green/20"
                         : "bg-grab-green hover:bg-grab-green-dark active:scale-[0.97] shadow-grab-green/20 animate-pulse-glow"
                     }`}
        >
          {/* Speaker icon */}
          <div className="w-14 h-14 rounded-xl bg-white/20 flex items-center justify-center shrink-0">
            {isPlaying ? (
              /* Sound wave animation */
              <div className="flex items-end gap-1 h-7">
                <span className="w-1.5 bg-white rounded-full animate-bounce" style={{ height: "60%", animationDelay: "0ms" }} />
                <span className="w-1.5 bg-white rounded-full animate-bounce" style={{ height: "100%", animationDelay: "150ms" }} />
                <span className="w-1.5 bg-white rounded-full animate-bounce" style={{ height: "40%", animationDelay: "300ms" }} />
                <span className="w-1.5 bg-white rounded-full animate-bounce" style={{ height: "80%", animationDelay: "450ms" }} />
              </div>
            ) : (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="w-7 h-7 text-white"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.536 8.464a5 5 0 010 7.072M17.95 6.05a8 8 0 010 11.9M6.5 8.8l5.7-3.8a.6.6 0 01.9.5v13a.6.6 0 01-.9.5L6.5 15.2H4a1 1 0 01-1-1v-4.4a1 1 0 011-1h2.5z"
                />
              </svg>
            )}
          </div>

          <div className="text-left">
            <span className="block text-xl sm:text-2xl font-extrabold text-white">
              {isPlaying ? "Đang đọc mã PIN..." : "Chạm vào đây để nghe"}
            </span>
            <span className="block text-sm text-white/70 font-medium mt-0.5">
              {isPlaying ? "Vui lòng lắng nghe" : "đọc mã PIN bằng giọng nói"}
            </span>
          </div>
        </button>
      </div>
    </div>
  );
}

function InfoRow({ icon, label, value, highlight = false }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xl shrink-0" role="img" aria-hidden="true">
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <span className="block text-xs text-gray-500 font-medium">{label}</span>
        <span
          className={`block text-base font-bold truncate ${
            highlight ? "text-grab-yellow" : "text-white"
          }`}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

export default PassengerView;

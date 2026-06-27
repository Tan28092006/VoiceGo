/**
 * voice-app.js
 * VoiceGo — accessible, AGENT-DRIVEN voice ride booking.
 *
 * The backend runs a conversational agent (Groq function-calling) that decides
 * when to look up a destination, ask for clarification, or book — by calling
 * tools. The frontend just: captures speech (hold-to-talk) -> sends the running
 * conversation to /api/agent/chat -> speaks the reply -> applies UI side-effects
 * (pin the destination, show the booking). Gestures are voice-equivalent commands.
 *
 * Resilience: with no backend (e.g. static GitHub Pages), it degrades to an
 * on-device match of known places + the browser's own speech engine (no booking).
 */

const BACKEND_URL = (() => {
    const q = new URLSearchParams(location.search).get("backend");
    if (q) return q.replace(/\/$/, "");
    if (location.hostname === "localhost" || location.hostname === "127.0.0.1") {
        return "http://localhost:8000";
    }
    return "";
})();

// Pickup is fixed (the demo has no live GPS): International University, Thủ Đức.
const ORIGIN = { name: "Trường Đại học Quốc tế", lat: 10.8782, lng: 106.8012 };

class VoiceBookingApp {
    constructor() {
        this.recorder = new VoiceRecorder();
        this.busy = false;
        this.recording = false;
        this._starting = false;
        this._wantStop = false;
        this.messages = [];          // conversation history (sent to the agent each turn)
        this.origin = ORIGIN;
        this.gps = { lat: ORIGIN.lat, lng: ORIGIN.lng };
        this.audio = new Audio();
        this._streamTimer = null;
        this.sr = null;
        this.routeMap = (typeof RouteMap !== "undefined" && document.getElementById("route-map"))
            ? new RouteMap("route-map") : null;

        this.els = {
            status: document.getElementById("status"),
            substatus: document.getElementById("substatus"),
            recordBtn: document.getElementById("record-btn"),
            gestureZone: document.getElementById("gesture-zone"),
            backendDot: document.getElementById("backend-dot"),
            liveTranscript: document.getElementById("live-transcript"),
            agentOverlay: document.getElementById("agent-overlay"),
            agentLog: document.getElementById("agent-log"),
            agentResult: document.getElementById("agent-result"),
            destBox: document.getElementById("dest-box"),
            originBox: document.getElementById("origin-box"),
        };

        this._bindGestures();
        this.init();
    }

    init() {
        if (this.els.originBox) this.els.originBox.textContent = this.origin.name;
        this.announce("Chào bạn, tôi là VoiceGo.", "Chạm nút lớn bên dưới rồi nói điểm đến. Sau đó cứ trả lời bằng giọng nói.", true);
        this._checkBackend();
    }

    // ----- Status + speech ---------------------------------------------------
    announce(main, sub = "", speak = false) {
        if (this.els.status) this.els.status.textContent = main;
        if (this.els.substatus) this.els.substatus.textContent = sub;
        if (speak) this.speak(sub ? `${main} ${sub}` : main);
    }

    /** Speak via FPT Vietnamese TTS — the SAME engine for every line (greeting,
     *  questions, booking) so the voice never changes. Retries up to 3x before any
     *  browser fallback, so a transient blip doesn't switch to a different voice. */
    async speak(text) {
        if (!text) return;
        // Stop any audio still playing so lines don't overlap.
        try { this.audio.pause(); } catch (e) {}
        if (BACKEND_URL) {
            for (let attempt = 0; attempt < 3; attempt++) {
                try {
                    const res = await fetch(`${BACKEND_URL}/api/voice/tts`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ text }),
                        signal: AbortSignal.timeout(20000),
                    });
                    if (!res.ok) throw new Error("tts " + res.status);
                    const blob = await res.blob();
                    if (!blob || blob.size < 500) throw new Error("tts empty");
                    const audio = new Audio(URL.createObjectURL(blob));  // fresh element
                    this.audio = audio;
                    await new Promise((resolve) => {
                        audio.onended = resolve;
                        audio.onerror = resolve;
                        const p = audio.play();
                        if (p && p.catch) p.catch(() => resolve());
                    });
                    return;  // FPT success
                } catch (e) {
                    await this._sleep(300);  // brief backoff, then retry FPT
                }
            }
        }
        await this._browserSpeak(text);  // last resort only
    }

    _browserSpeak(text) {
        return new Promise((resolve) => {
            if (!("speechSynthesis" in window)) { resolve(); return; }
            const u = new SpeechSynthesisUtterance(text);
            u.lang = "vi-VN";
            // Prefer an actual Vietnamese voice so it doesn't read VN with an EN voice.
            const vi = (window.speechSynthesis.getVoices() || []).find(v => /vi(-|_)?/i.test(v.lang));
            if (vi) u.voice = vi;
            u.onend = resolve;
            u.onerror = resolve;
            window.speechSynthesis.cancel();
            window.speechSynthesis.speak(u);
        });
    }

    _vibrate(p) { if (navigator.vibrate) navigator.vibrate(p); }
    _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    async _checkBackend() {
        if (!BACKEND_URL) { this._setBackend(false); return; }
        try {
            const r = await fetch(`${BACKEND_URL}/api/health`, { signal: AbortSignal.timeout(2000) });
            this._setBackend(r.ok);
        } catch { this._setBackend(false); }
    }
    _setBackend(ok) {
        if (!this.els.backendDot) return;
        this.els.backendDot.textContent = ok ? "🟢 Agent VoiceGo" : "⚡ Ngoại tuyến";
        this.els.backendDot.className = "backend-dot " + (ok ? "online" : "offline");
    }

    // ----- Speech recognition (auto-endpointing: stops on its own when you pause) ---
    _setRecLabel(text) {
        const el = this.els.recordBtn && this.els.recordBtn.querySelector(".record-label");
        if (el) el.textContent = text;
    }

    _clearRecUI() {
        this.recording = false;
        if (this.els.recordBtn) this.els.recordBtn.classList.remove("recording");
        this._setRecLabel("Chạm để nói");
        if (this.els.liveTranscript) this.els.liveTranscript.textContent = "";
    }

    // Live caption (browser STT) — visual only; Whisper does the real transcription.
    _startCaption() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) return;
        try {
            this._cap = new SR();
            this._cap.lang = "vi-VN"; this._cap.interimResults = true; this._cap.continuous = true;
            this._cap.onresult = (e) => {
                let t = ""; for (const r of e.results) t += r[0].transcript;
                if (this.els.liveTranscript) this.els.liveTranscript.textContent = t ? `“${t}…”` : "";
            };
            this._cap.onerror = () => {};
            this._cap.start();
        } catch (e) { this._cap = null; }
    }
    _stopCaption() {
        if (this._cap) { try { this._cap.stop(); } catch (e) {} this._cap = null; }
    }

    /**
     * Tap once -> speak -> auto-stops on silence (VAD) -> sends audio to the server,
     * which transcribes with Groq Whisper (accurate Vietnamese). A browser caption
     * shows words live; Whisper is the authoritative text. FPT speaks the replies.
     */
    startListening() {
        if (this.busy || this.recording || this._starting) return;
        if (!BACKEND_URL) {
            this.announce("Chế độ ngoại tuyến.", "Cần chạy server agent để dùng giọng nói.", true);
            return;
        }
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SR) { this._listenBrowser(SR); return; }  // PRIMARY: browser Web Speech
        this._listenWhisper();                         // FALLBACK: record + Whisper
    }

    /**
     * PRIMARY input: the browser's Web Speech engine — most accurate for Vietnamese
     * (this is the live caption you see). Its final transcript is sent to the agent.
     * Auto-stops on silence.
     */
    _listenBrowser(SR) {
        this.recording = true;
        this._srErr = null;
        this._vibrate(40);
        if (this.els.recordBtn) this.els.recordBtn.classList.add("recording");
        this._setRecLabel("🎙️ Đang nghe…");
        this.announce("Đang nghe…", "Nói điểm đến — tôi tự nhận khi bạn ngừng nói.");
        if (this.els.liveTranscript) this.els.liveTranscript.textContent = "";

        let finalText = "";
        const sr = new SR();
        this.sr = sr;
        sr.lang = "vi-VN"; sr.interimResults = true; sr.continuous = false; sr.maxAlternatives = 1;
        sr.onresult = (e) => {
            let interim = "";
            for (const r of e.results) {
                if (r.isFinal) finalText += r[0].transcript;
                else interim += r[0].transcript;
            }
            const show = (finalText + interim).trim();
            if (this.els.liveTranscript) this.els.liveTranscript.textContent = show ? `“${show}…”` : "";
        };
        sr.onerror = (ev) => { this._srErr = ev.error; };
        sr.onend = async () => {
            this.sr = null;
            this._clearRecUI();
            const text = finalText.trim();
            if (text) { this._emptyCount = 0; this._send(text); return; }
            if (this._srErr === "not-allowed" || this._srErr === "service-not-allowed") {
                this._emptyCount = 0;
                this.announce("Cần quyền micro.", "Hãy cho phép micro rồi chạm nút thử lại.", true);
                return;
            }
            this._emptyCount = (this._emptyCount || 0) + 1;
            if (this._emptyCount <= 2) {
                const m = "Mình chưa nghe rõ.", s = "Bạn nói lại giúp tôi nhé.";
                this.announce(m, s, false);
                await this.speak(`${m} ${s}`);
                this._autoListen();
            } else {
                this._emptyCount = 0;
                this.announce("Mình vẫn chưa nghe được.", "Chạm nút khi bạn sẵn sàng nói nhé.", true);
            }
        };
        try { sr.start(); }
        catch (e) { this.sr = null; this._clearRecUI(); this.announce("Không bật được micro.", "Bạn thử lại nhé.", true); }
    }

    /** FALLBACK input: record audio + Groq Whisper (browsers without Web Speech). */
    async _listenWhisper() {
        this._starting = true;
        this._wantStop = false;
        this._vibrate(40);
        if (this.els.recordBtn) this.els.recordBtn.classList.add("recording");
        this._setRecLabel("🎙️ Đang nghe…");
        this.announce("Đang nghe…", "Nói điểm đến — tôi tự nhận khi bạn ngừng nói.");
        if (this.els.liveTranscript) this.els.liveTranscript.textContent = "";

        try {
            await this.recorder.start({ onAutoStop: () => this._finishRecording() });
        } catch (e) {
            this._starting = false;
            this._clearRecUI();
            this.announce("Không truy cập được micro.", "Hãy cho phép micro rồi chạm nút thử lại.", true);
            return;
        }
        this._starting = false;
        if (this._wantStop) { this._finishRecording(); return; }
        this.recording = true;
        this._startCaption();
        this._maxTimer = setTimeout(() => this._finishRecording(), 15000);
    }

    /** Tap again to end early (otherwise it ends automatically on silence). */
    stopListening() {
        if (this.sr) { try { this.sr.stop(); } catch (e) {} return; }  // browser path
        if (this._starting) { this._wantStop = true; return; }          // whisper starting
        this._finishRecording();                                         // whisper path
    }

    async _finishRecording() {
        if (!this.recording) return;
        this.recording = false;
        if (this._maxTimer) { clearTimeout(this._maxTimer); this._maxTimer = null; }
        const wav = this.recorder.stop();
        this._stopCaption();
        this._clearRecUI();
        this.announce("Đang nhận diện…", "");
        try {
            const fd = new FormData();
            fd.append("file", wav, "speech.wav");
            const res = await fetch(`${BACKEND_URL}/api/voice/stt`, {
                method: "POST", body: fd, signal: AbortSignal.timeout(30000),
            });
            const j = await res.json();
            const text = (j.text || "").trim();
            if (!text) {
                this._emptyCount = (this._emptyCount || 0) + 1;
                if (this._emptyCount <= 2) {
                    const m = "Mình chưa nghe rõ.", s = "Bạn nói lại giúp tôi nhé.";
                    this.announce(m, s, false);
                    await this.speak(`${m} ${s}`);
                    this._autoListen();
                } else {
                    this._emptyCount = 0;
                    this.announce("Mình vẫn chưa nghe được.", "Chạm nút khi bạn sẵn sàng nói nhé.", true);
                }
                return;
            }
            this._emptyCount = 0;
            this._send(text);
        } catch (e) {
            this.announce("Lỗi nhận diện giọng nói.", "Bạn thử lại hoặc chạm nút nói lại.", true);
        }
    }

    // ----- Agent conversation -----------------------------------------------
    async _send(text) {
        if (!text || this.busy) return;

        if (!BACKEND_URL) { this._localFallback(text); return; }

        this.busy = true;
        this.messages.push({ role: "user", content: text });
        this.announce("Đang xử lý…", `Bạn: “${text}”`);
        try {
            const res = await fetch(`${BACKEND_URL}/api/agent/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages: this.messages }),
                signal: AbortSignal.timeout(60000),
            });
            const data = await res.json();
            this.messages = data.messages || this.messages;
            const ui = data.ui || {};
            const reply = data.reply || "";

            // Phase 1: a place was resolved -> pin it (no route/price yet).
            if (ui.destination) this._applyDestination(ui.destination);
            // Phase 2: a quote was made -> draw the real route (distance/price confirmed).
            if (ui.quote) this._applyQuote(ui.quote);

            if (ui.booked) {
                await this._showBooked(ui.booked, reply);
                this.busy = false;
                this._resetTrip();
                return; // conversation done — no auto-listen
            }
            // User cancelled / ended -> say goodbye then STOP (no auto-listen).
            if (ui.ended) {
                this.announce(reply || "Đã huỷ.", "", false);
                this.busy = false;
                await this.speak(reply || "Đã huỷ chuyến. Cảm ơn bạn.");
                this._resetTrip();
                return;
            }
            // Speak the reply, then automatically listen again (hands-free).
            this.announce(reply || "…", "", false);
            this.busy = false;
            await this.speak(reply);
            this._autoListen();
        } catch (e) {
            this.busy = false;
            this.announce("Lỗi kết nối agent.", "Bạn thử lại giúp tôi nhé.", true);
        }
    }

    /** After the agent finishes speaking, listen again so the user just talks back. */
    async _autoListen() {
        if (this.busy || this.recording) return;
        await this._sleep(350);        // small gap so TTS tail isn't captured
        if (this.busy || this.recording) return;
        this.startListening();
    }

    _applyDestination(d) {
        if (this.els.destBox) {
            this.els.destBox.textContent = d.address || d.name;
            this.els.destBox.classList.remove("muted");
        }
        if (this.routeMap && d.lat != null) {
            this.routeMap.showPins(this.origin, { lat: d.lat, lng: d.lng, name: d.name, address: d.address });
        }
    }

    _applyQuote(q) {
        if (this.els.destBox && (q.address || q.name)) {
            this.els.destBox.textContent = q.address || q.name;
            this.els.destBox.classList.remove("muted");
        }
        if (this.routeMap && q.lat != null) {
            this.routeMap.showTrip(this.origin, { lat: q.lat, lng: q.lng, name: q.name, address: q.address }, q.geometry);
        }
    }

    async _showBooked(booked, reply) {
        this._showAgentOverlay();
        await this._typewrite(this.els.agentLog, reply || "Đang đặt xe…");
        const v = booked.vehicle === "car" ? "ô tô điện" : "xe ôm điện";
        const priceK = Math.round((booked.priceVnd || 0) / 1000);
        const driver = `Tài xế ${booked.driver} · ${booked.plate} · ${v} · `
            + `đón tại ${booked.pickup} sau ${booked.etaMin} phút · giá ${priceK} nghìn đồng.`;
        const alert = booked.driverAlertMessage ? `\nCảnh báo tài xế: ${booked.driverAlertMessage}` : "";
        const saved = booked.rideId ? `\nMã chuyến: ${booked.rideId}` : "";
        if (this.els.agentResult) this.els.agentResult.textContent = driver + alert + saved;
        const spinner = this.els.agentOverlay && this.els.agentOverlay.querySelector(".agent-spinner");
        if (spinner) spinner.style.display = "none";
        this.speak(`${reply} ${driver} ${booked.driverAlertMessage || ""}`);
        // Speak the agent's concise Vietnamese confirmation (FPT, same voice as the
        // whole flow). Driver details are shown visually.
        await this.speak(reply || driver);
    }

    /** Smooth typewriter (continuous like ChatGPT) into a visual element. */
    _typewrite(el, text) {
        return new Promise(resolve => {
            if (!el) { resolve(); return; }
            el.textContent = "";
            let i = 0;
            const tick = () => {
                const take = Math.max(1, Math.ceil((text.length - i) / 40));
                el.textContent = text.slice(0, i + take);
                i += take;
                el.scrollTop = el.scrollHeight;
                if (i < text.length) { this._streamTimer = setTimeout(tick, 18); }
                else { this._streamTimer = null; resolve(); }
            };
            tick();
        });
    }

    _showAgentOverlay() {
        if (!this.els.agentOverlay) return;
        if (this.els.agentLog) this.els.agentLog.textContent = "";
        if (this.els.agentResult) this.els.agentResult.textContent = "";
        const spinner = this.els.agentOverlay.querySelector(".agent-spinner");
        if (spinner) spinner.style.display = "";
        this.els.agentOverlay.classList.remove("hidden");
    }
    _hideAgentOverlay() {
        if (this._streamTimer) { clearTimeout(this._streamTimer); this._streamTimer = null; }
        if (this.els.agentOverlay) this.els.agentOverlay.classList.add("hidden");
    }

    _resetTrip() {
        this.messages = [];
        if (this.els.destBox) {
            this.els.destBox.textContent = "Chưa có — hãy nói điểm đến";
            this.els.destBox.classList.add("muted");
        }
    }

    // ----- On-device fallback when there is no backend ----------------------
    _localFallback(text) {
        if (typeof understandCommand !== "function") {
            this.announce("Chế độ ngoại tuyến.", "Cần chạy server agent để đặt xe.", true);
            return;
        }
        const u = understandCommand(text);
        if (u.needsRepeat || !u.place || !u.place.node) {
            this.announce(`Bạn nói: “${text}”.`, "Chế độ ngoại tuyến chỉ nhận vài địa điểm quen. Bạn thử tên khác nhé.", true);
            return;
        }
        const node = u.place.node;
        this._applyDestination({ name: u.place.name, lat: node.lat, lng: node.lng });
        const km = Graph.haversineDistance(this.origin.lat, this.origin.lng, node.lat, node.lng) / 1000;
        this.announce(`Đi ${u.place.name} (~${km.toFixed(1)} km).`,
            "Chế độ ngoại tuyến: cần server agent để đặt xe thật.", true);
    }

    // ----- Input bindings (voice-first: everything else is spoken to the agent) --
    _bindGestures() {
        const btn = this.els.recordBtn;
        if (btn) {
            // One tap to talk (tap again to end early). Confirm / change vehicle /
            // cancel are all done by VOICE — no extra gestures. After the agent
            // replies it auto-listens, so usually you only tap once at the start.
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                if (this.recording || this._starting) this.stopListening();
                else this.startListening();
            });
        }

        if (this.els.agentOverlay) {
            this.els.agentOverlay.addEventListener("click", () => {
                if (this.els.agentResult && this.els.agentResult.textContent) {
                    this._hideAgentOverlay();
                    this._resetTrip();
                    this.announce("Chuyến đi đã đặt xong.", "Chạm nút để đặt chuyến mới.", true);
                }
            });
        }
    }
}

document.addEventListener("DOMContentLoaded", () => { window.voiceApp = new VoiceBookingApp(); });

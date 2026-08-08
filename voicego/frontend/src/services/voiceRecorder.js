let sharedAudioContext = null;

// Mở trang với ?debug=1 để hiện đồng hồ RMS/ngưỡng ngay trên màn hình — điện thoại
// không xem được console, mà barge-in thì phải biết mic có thật sự nghe được hay không.
const DEBUG_VAD = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('debug') === '1';

function debugBadge(text) {
    if (!DEBUG_VAD) return;
    let d = document.getElementById('vad-debug');
    if (!d) {
        d = document.createElement('div');
        d.id = 'vad-debug';
        Object.assign(d.style, {
            position: 'fixed', bottom: '6px', left: '6px', zIndex: 2147483647,
            background: 'rgba(0,0,0,.78)', color: '#0f0', font: '12px monospace',
            padding: '4px 7px', borderRadius: '4px', pointerEvents: 'none',
        });
        document.body.appendChild(d);
    }
    d.textContent = text;
}

export function initSharedAudioContext() {
    if (!sharedAudioContext) {
        sharedAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (sharedAudioContext.state === 'suspended') {
        sharedAudioContext.resume().catch(() => {});
    }
    return sharedAudioContext;
}

export default class VoiceRecorder {
    constructor(targetRate = 16000) {
        this.targetRate = targetRate;
        this.audioContext = null;
        this.stream = null;
        this.source = null;
        this.processor = null;
        this.chunks = [];
        this.recording = false;
    }

    /**
     * opts.onAutoStop(): called once when speech is followed by ~silenceMs of
     * silence (voice activity detection) — enables hands-free "speak then it
     * stops by itself". opts.silenceMs (default 1300), opts.speechThreshold (RMS).
     */
    async start(opts = {}) {
        this.onAutoStop = opts.onAutoStop || null;
        this.onSpeechStart = opts.onSpeechStart || null;
        this.onVoice = opts.onVoice || null;   // (active:boolean) -> đèn báo nghe thấy giọng
        this.silenceMs = opts.silenceMs || 1300;
        this.noSpeechMs = opts.noSpeechMs || 6000;   // give up if nothing is said
        // Ba nút vặn của VAD. Chỉnh nhanh ngay trên điện thoại bằng query string
        // (?vadmult=6&vadframes=5) để khỏi phải build lại mỗi lần thử.
        const q = new URLSearchParams(window.location.search);
        const num = (k, d) => (Number(q.get(k)) > 0 ? Number(q.get(k)) : d);
        // Sàn tuyệt đối: dù nền có thấp cỡ nào cũng không nhận dưới mức này.
        this.speechThreshold = opts.speechThreshold || num('vadmin', 0.006);
        this.floorMult = opts.floorMult || num('vadmult', 5);   // vượt nền mấy lần mới tính
        // Số khung LIÊN TIẾP phải đủ to mới coi là đang nói (~85ms/khung). Đây là
        // nút chống-nhiễu quan trọng nhất: ho/cộp/va chạm chỉ kéo 150-250ms nên
        // không thể đạt 7 khung (~600ms), còn một câu nói thì vượt thừa.
        this.speechFrames = opts.speechFrames || num('vadframes', 8);
        this.warmupMs = opts.warmupMs || 400;     // để nền kịp học mức echo của TTS
        this._speechStarted = false;
        this._silenceStart = null;
        this._autoStopped = false;
        this._hits = 0;
        this._floor = null;
        this._voiceOn = false;
        this._peak = 0;
        this._quietSince = null;
        this._t0 = (typeof performance !== "undefined" ? performance.now() : 0);

        // MUST be created/resumed BEFORE any async 'await' to satisfy iOS Safari user gesture requirements
        if (!sharedAudioContext) {
            sharedAudioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (sharedAudioContext.state === 'suspended') {
            // Kick off resume immediately in the sync call stack
            sharedAudioContext.resume().catch(() => {});
        }
        this.audioContext = sharedAudioContext;

        if (!this.stream) {
            // AEC BẬT (không được nghe lại chính mình) nhưng NS/AGC TẮT: trên Android
            // Chrome hai cái đó mới là thứ gate mic xuống ~0 khi loa đang phát — đúng
            // thứ giết barge-in. AEC một mình vẫn khử phần lớn tiếng TTS vọng lại.
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: false,
                    autoGainControl: false,
                },
            });

            this.source = this.audioContext.createMediaStreamSource(this.stream);
            // ScriptProcessor is deprecated but the simplest cross-browser PCM tap.
            this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
            
            this.processor.onaudioprocess = (e) => {
                if (!this.recording) return;
                const data = e.inputBuffer.getChannelData(0);
                this.chunks.push(new Float32Array(data));

                // Khi CHƯA xác nhận là tiếng nói, chỉ giữ lại một đoạn "tiền ghi" ngắn
                // rồi vứt phần cũ hơn. Trước đây giữ tất từ lúc mic mở, nên file gửi
                // lên Whisper còn dính cả tiếng TTS đang phát (mic mở khi AI chưa đọc
                // xong) -> Whisper chép lại chính giọng AI và đưa ngược vào agent.
                // Đoạn giữ lại phải DÀI HƠN cửa sổ xác nhận (speechFrames), nếu không
                // sẽ cắt mất mấy từ đầu — chính là mấy từ đã kích hoạt nhận diện.
                if (!this._speechStarted) {
                    const keep = this.speechFrames + 4;      // ~950ms tiền ghi
                    if (this.chunks.length > keep) {
                        this.chunks.splice(0, this.chunks.length - keep);
                    }
                }

                if (this.onAutoStop && !this._autoStopped) {
                    let sum = 0;
                    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
                    const rms = Math.sqrt(sum / data.length);
                    const now = performance.now();

                    // Ngưỡng THÍCH NGHI: bám mức "nền" rồi đòi khung âm vượt hẳn lên. Một
                    // con số cố định không thể vừa phục vụ mic bị AEC gate (nền ~0.0005)
                    // vừa phục vụ mic rò tiếng TTS từ loa (nền ~0.01 -> tự cắt lời mình).
                    // Ngưỡng phải tính TỪ nền CŨ, trước khi cập nhật nền (xem dưới).
                    const threshold = Math.max(this.speechThreshold,
                        this._floor == null ? 0 : this._floor * this.floorMult);
                    const warming = now - this._t0 < this.warmupMs;   // chờ nền ổn định
                    const aboveFloor = rms > threshold;
                    // Giữ mức TO NHẤT nghe được trong lượt này. Đây là số quyết định:
                    // so peak (lúc nói) với floor (lúc im) là biết ngay ngưỡng phải đặt
                    // đâu, khỏi vặn mò từng nút.
                    if (rms > (this._peak || 0)) this._peak = rms;

                    // Nền = mức ồn ĐIỂN HÌNH, không phải mức nhỏ nhất. Min-tracking (bản
                    // trước) bám vào đáy: phòng ồn dao động 0.002-0.010 thì nền kẹt ở
                    // 0.002 -> ngưỡng 0.010 -> đỉnh nhiễu thường cũng vượt, và vì nhiễu
                    // liên tục nên tăng số khung cũng không cứu được.
                    // EMA lên CHẬM xuống NHANH: tiếng ồn kéo dài thì nền dâng theo (bớt
                    // nhạy), còn một câu nói ngắn không kịp kéo nền lên. Đóng băng nền khi
                    // đã xác định là đang nói, để giọng không làm hỏng ước lượng.
                    if (!this._speechStarted) {
                        if (this._floor == null) this._floor = rms;
                        else {
                            const a = rms > this._floor ? 0.02 : 0.10;
                            this._floor = this._floor * (1 - a) + rms * a;
                        }
                    }

                    if (!this._dbgAt || now - this._dbgAt > 200) {
                        this._dbgAt = now;
                        debugBadge(`rms ${rms.toFixed(4)} | PEAK ${(this._peak || 0).toFixed(4)}`
                            + ` | floor ${(this._floor || 0).toFixed(4)} | th ${threshold.toFixed(4)}`
                            + ` | ${this._hits || 0}/${this.speechFrames}`
                            + ` | ${this._speechStarted ? 'SPEAK' : (warming ? 'warm' : 'idle')}`);
                    }

                    // Đèn báo "đang nghe thấy giọng" cho UI. Chỉ gọi khi ĐỔI trạng thái
                    // (kèm 250ms giữ) -> không làm React render 12 lần/giây.
                    const loud = aboveFloor && !warming;
                    if (loud) this._quietSince = null;
                    else if (this._quietSince == null) this._quietSince = now;
                    const voiceOn = loud || (this._quietSince != null && now - this._quietSince < 250);
                    if (voiceOn !== this._voiceOn) {
                        this._voiceOn = voiceOn;
                        if (this.onVoice) { try { this.onVoice(voiceOn); } catch (err) {} }
                    }

                    if (loud) {
                        this._hits = (this._hits || 0) + 1;
                        this._silenceStart = null;
                        // Cần đủ số khung LIÊN TIẾP mới coi là nói, để tiếng ho/cộp/va
                        // chạm không cắt mất lời AI đang đọc.
                        if (!this._speechStarted && this._hits >= this.speechFrames) {
                            this._speechStarted = true;
                            if (this.onSpeechStart) {
                                try { this.onSpeechStart(); } catch (err) {}
                            }
                        }
                    } else {
                        // Trừ dần thay vì xoá sạch: người nói vẫn có nhịp ngắt hơi giữa
                        // các từ, xoá sạch thì không bao giờ gom đủ số khung. Tiếng ho
                        // đơn lẻ thì vẫn tiêu vì sau đó toàn khung im, trừ về 0.
                        this._hits = Math.max(0, (this._hits || 0) - 1);
                        if (this._speechStarted) {
                            if (this._silenceStart == null) this._silenceStart = now;
                            else if (now - this._silenceStart > this.silenceMs) {
                                this._autoStopped = true;
                                try { this.onAutoStop(); } catch (err) {}
                            }
                        } else if (now - this._t0 > this.noSpeechMs) {
                            // Nothing said at all -> give up so we can re-prompt.
                            this._autoStopped = true;
                            try { this.onAutoStop(); } catch (err) {}
                        }
                    }
                }
            };

            this.source.connect(this.processor);
            
            // ScriptProcessor chỉ chạy khi được nối tới destination, nhưng gain PHẢI = 0:
            // gain 0.01 trước đây đẩy tiếng mic ra loa -> tự tạo echo -> AEC/ducking siết
            // mic mạnh hơn, chính là vòng lặp làm barge-in chết.
            this.gainNode = this.audioContext.createGain();
            this.gainNode.gain.value = 0;
            this.processor.connect(this.gainNode);
            this.gainNode.connect(this.audioContext.destination);
        }

        this.chunks = [];
        this.recording = true;
    }

    stop() {
        this.recording = false;
        if (this._voiceOn) {                   // tắt đèn báo khi ngừng thu
            this._voiceOn = false;
            if (this.onVoice) { try { this.onVoice(false); } catch (err) {} }
        }
        const inputRate = this.audioContext ? this.audioContext.sampleRate : 44100;

        // Merge captured chunks
        let length = 0;
        this.chunks.forEach(c => length += c.length);
        const merged = new Float32Array(length);
        let offset = 0;
        this.chunks.forEach(c => { merged.set(c, offset); offset += c.length; });

        // We DO NOT stop the microphone stream or disconnect the nodes here.
        // Re-requesting getUserMedia while audio is playing on Android Chrome causes AEC breakage and silence.
        // Instead, we just keep the stream alive and toggle this.recording = false.

        // If the user didn't speak at all, don't return an audio blob (prevents silent backend STT calls)
        if (!this._speechStarted) {
            const info = `peak ${(this._peak || 0).toFixed(4)} | floor ${(this._floor || 0).toFixed(4)}`
                + ` | can > ${Math.max(this.speechThreshold, (this._floor || 0) * this.floorMult).toFixed(4)}`;
            console.log('[voiceRecorder] KHONG nhan dien duoc ->', info);
            debugBadge(`KHONG NGHE DUOC | ${info}`);
            return null;
        }
        const secs = length / inputRate;
        const preRoll = ((this.speechFrames + 4) * 4096) / inputRate;
        console.log(`[voiceRecorder] doan ghi ${secs.toFixed(2)}s `
            + `(gom ~${preRoll.toFixed(2)}s tien ghi TRUOC khi nhan dien + phan noi sau do)`);
        debugBadge(`gui STT: ${secs.toFixed(2)}s (tien ghi ${preRoll.toFixed(2)}s)`);

        const downsampled = this._downsample(merged, inputRate, this.targetRate);
        return this._encodeWav(downsampled, this.targetRate);
    }

    _downsample(buffer, inRate, outRate) {
        if (outRate >= inRate) return buffer;
        const ratio = inRate / outRate;
        const newLen = Math.round(buffer.length / ratio);
        const result = new Float32Array(newLen);
        let pos = 0;
        for (let i = 0; i < newLen; i++) {
            const next = Math.round((i + 1) * ratio);
            let sum = 0, count = 0;
            for (let j = Math.round(i * ratio); j < next && j < buffer.length; j++) {
                sum += buffer[j]; count++;
            }
            result[i] = count ? sum / count : 0;
            pos = next;
        }
        return result;
    }

    _encodeWav(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };

        writeStr(0, "RIFF");
        view.setUint32(4, 36 + samples.length * 2, true);
        writeStr(8, "WAVE");
        writeStr(12, "fmt ");
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);          // PCM
        view.setUint16(22, 1, true);          // mono
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        writeStr(36, "data");
        view.setUint32(40, samples.length * 2, true);

        let off = 44;
        for (let i = 0; i < samples.length; i++, off += 2) {
            const s = Math.max(-1, Math.min(1, samples[i]));
            view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
        return new Blob([view], { type: "audio/wav" });
    }
}

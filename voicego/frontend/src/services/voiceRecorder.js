let sharedAudioContext = null;

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
        this.silenceMs = opts.silenceMs || 1300;
        this.noSpeechMs = opts.noSpeechMs || 6000;   // give up if nothing is said
        this.speechThreshold = opts.speechThreshold || 0.001; // Extremely sensitive for AEC ducking
        this._speechStarted = false;
        this._silenceStart = null;
        this._autoStopped = false;
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
            this.stream = await navigator.mediaDevices.getUserMedia({ 
                audio: { 
                    echoCancellation: true, 
                    noiseSuppression: true, 
                    autoGainControl: true 
                } 
            });

            this.source = this.audioContext.createMediaStreamSource(this.stream);
            // ScriptProcessor is deprecated but the simplest cross-browser PCM tap.
            this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
            
            this.processor.onaudioprocess = (e) => {
                if (!this.recording) return;
                const data = e.inputBuffer.getChannelData(0);
                this.chunks.push(new Float32Array(data));

                if (this.onAutoStop && !this._autoStopped) {
                    let sum = 0;
                    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
                    const rms = Math.sqrt(sum / data.length);
                    const now = performance.now();
                    if (!this._lastLog || now - this._lastLog > 1000) {
                        console.log(`[voiceRecorder] RMS: ${rms.toFixed(5)} | Threshold: ${this.speechThreshold}`);
                        this._lastLog = now;
                    }
                    if (rms > this.speechThreshold) {
                        if (!this._speechStarted) {
                            this._speechStarted = true;
                            this._silenceStart = null;
                            if (this.onSpeechStart && !this._autoStopped) {
                                try { this.onSpeechStart(); } catch (err) {}
                            }
                        } else {
                            this._silenceStart = null;
                        }
                    } else if (this._speechStarted) {
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
            };

            this.source.connect(this.processor);
            
            // Mute the processor output so it doesn't feed back into the speaker and trigger AEC ducking
            // Use a tiny non-zero gain so iOS Safari doesn't optimize it away and stop processing
            this.gainNode = this.audioContext.createGain();
            this.gainNode.gain.value = 0.01;
            this.processor.connect(this.gainNode);
            this.gainNode.connect(this.audioContext.destination);
        }

        this.chunks = [];
        this.recording = true;
    }

    stop() {
        this.recording = false;
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
            return null;
        }

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

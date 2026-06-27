/**
 * voice-recorder.js
 * Records microphone audio and encodes it to 16kHz mono WAV — the format FPT.AI
 * ASR handles most reliably (MediaRecorder's default webm/opus is not accepted).
 *
 * Usage:
 *   const rec = new VoiceRecorder();
 *   await rec.start();           // begins capturing
 *   const wavBlob = await rec.stop();  // returns a WAV Blob
 */
class VoiceRecorder {
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
        this.silenceMs = opts.silenceMs || 1300;
        this.speechThreshold = opts.speechThreshold || 0.018;
        this._speechStarted = false;
        this._silenceStart = null;
        this._autoStopped = false;

        this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        this.source = this.audioContext.createMediaStreamSource(this.stream);
        // ScriptProcessor is deprecated but the simplest cross-browser PCM tap.
        this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
        this.chunks = [];
        this.recording = true;

        this.processor.onaudioprocess = (e) => {
            if (!this.recording) return;
            const data = e.inputBuffer.getChannelData(0);
            this.chunks.push(new Float32Array(data));

            if (this.onAutoStop && !this._autoStopped) {
                let sum = 0;
                for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
                const rms = Math.sqrt(sum / data.length);
                const now = performance.now();
                if (rms > this.speechThreshold) {
                    this._speechStarted = true;
                    this._silenceStart = null;
                } else if (this._speechStarted) {
                    if (this._silenceStart == null) this._silenceStart = now;
                    else if (now - this._silenceStart > this.silenceMs) {
                        this._autoStopped = true;
                        try { this.onAutoStop(); } catch (err) {}
                    }
                }
            }
        };

        this.source.connect(this.processor);
        this.processor.connect(this.audioContext.destination);
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

        // Tear down audio nodes / mic
        try { this.processor.disconnect(); } catch (e) {}
        try { this.source.disconnect(); } catch (e) {}
        if (this.stream) this.stream.getTracks().forEach(t => t.stop());
        if (this.audioContext) this.audioContext.close();

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

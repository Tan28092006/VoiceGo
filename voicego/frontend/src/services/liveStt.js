/**
 * Gemini Live STT (gemini-3.5-transcribe-live) — nhánh STT mới, bật bằng nút trên
 * Header hoặc env STT_ENGINE=gemini-live. Nhánh mặc định vẫn là Whisper.
 *
 * Trình duyệt mở WebSocket THẲNG tới Gemini bằng ephemeral token do backend cấp
 * (/api/voice/live-token), không đi vòng qua Render. Audio chỉ được gửi khi VAD ở
 * voiceRecorder đã xác nhận có tiếng nói (kèm ~950ms tiền ghi), nên tiếng TTS lúc
 * im lặng không bị chép lại và không tốn quota.
 *
 * Những gì đã đo thật (10/2026):
 *  - Mở kết nối mới tốn ~1.3-2s (token ~550ms + WS + setup) -> MỞ SẴN, giữ qua nhiều lượt.
 *  - Server tự đóng (1008) sau 60s không nhận audio -> gửi 100ms im lặng mỗi 5s.
 *  - Một session nghe được nhiều lượt; sau audioStreamEnd, bản chốt về sau ~350-470ms,
 *    đi kèm generationComplete -> đó là tín hiệu "xong lượt".
 *  - Server tự chốt từng ĐOẠN khi người nói ngừng giữa câu -> phải nối các đoạn lại.
 *  - interim là bản tích luỹ của đoạn hiện tại, và có dấu chấm khi model cho là câu
 *    đã trọn ("…Bến Thành nhé.") -> tín hiệu để cắt lượt sớm (xem silenceMsFor).
 */
import { BACKEND_URL } from './config';

const WS_BASE = 'wss://generativelanguage.googleapis.com/ws/'
  + 'google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained';
const KEEPALIVE_MS = 5000;          // < 60s idle timeout của server, đã test 5s giữ được
const ROTATE_MS = 9 * 60 * 1000;    // session tối đa 10 phút -> chủ động mở lại lúc rảnh
const IDLE_CLOSE_MS = 4 * 60 * 1000; // không ai nói 4 phút -> đóng hẳn, lần nói sau tự mở lại
const SETUP_TIMEOUT_MS = 8000;
const FRAME = 1600;                 // 100ms @16kHz — cỡ chunk Gemini khuyên dùng
const MAX_QUEUE = 150;              // ~15s audio chờ trong lúc đang kết nối
const SILENCE_B64 = b64(new Int16Array(FRAME));

function b64(int16) {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

export default class LiveStt {
  constructor() {
    this.ws = null;
    this.ready = false;
    this._opening = null;
    this._queue = [];
    this._openedAt = 0;
    this._lastAudioAt = 0;
    this._lastUseAt = Date.now();
    this._keepalive = null;
    this._rotateWanted = false;
    this._drainUntil = 0;
    this.onText = null;             // (fullText, isFinal) -> phụ đề + xác nhận chen ngang
    this._resetTurn();
    this.inTurn = false;
  }

  _resetTurn() {
    this.finals = [];
    this.interim = '';
    this.active = false;            // server VAD đang thấy tiếng nói (ACTIVITY_START chưa END)
    this.sawActivity = false;
    this._finish = null;
  }

  /** Toàn bộ chữ của lượt hiện tại: các đoạn đã chốt + đoạn đang nghe. */
  get text() {
    return [...this.finals, this.interim].filter(Boolean).join(' ').trim();
  }

  /** Mở (hoặc tái dùng) session. Trả true khi đã sẵn sàng nhận audio. */
  ensureOpen() {
    this._lastUseAt = Date.now();
    // Đang giữa một lượt thì KHÔNG xoay session dù đã tới hạn — xoay sau khi xong lượt.
    if (this.ready && this.ws && (!this._rotateWanted || this.inTurn)) return Promise.resolve(true);
    if (this._opening) return this._opening;
    if (this._rotateWanted) this.close();
    this._opening = this._open().then((ok) => {
      if (!ok) this._queue = [];   // audio xếp hàng của lần mở hỏng không được lọt sang session sau
      return ok;
    }).finally(() => { this._opening = null; });
    return this._opening;
  }

  async _open() {
    let tok;
    try {
      const res = await fetch(`${BACKEND_URL}/api/voice/live-token`, { method: 'POST' });
      tok = await res.json();
      if (!res.ok || !tok.token) throw new Error(tok.error || `HTTP ${res.status}`);
    } catch (err) {
      console.warn('[liveStt] khong lay duoc token:', err?.message || err);
      return false;
    }
    return new Promise((resolve) => {
      let settled = false;
      const settle = (ok) => { if (!settled) { settled = true; resolve(ok); } };
      const ws = new WebSocket(`${WS_BASE}?access_token=${encodeURIComponent(tok.token)}`);
      const timer = setTimeout(() => { console.warn('[liveStt] setup timeout'); try { ws.close(); } catch {} settle(false); }, SETUP_TIMEOUT_MS);
      ws.onopen = () => {
        ws.send(JSON.stringify({ setup: {
          model: `models/${tok.model}`,
          generationConfig: { responseModalities: ['TEXT'] },
          inputAudioTranscription: { languageCodes: ['vi-VN'], customVocabulary: tok.vocab || [] },
        } }));
      };
      ws.onmessage = async (ev) => {
        const raw = typeof ev.data === 'string' ? ev.data : await ev.data.text();
        let msg; try { msg = JSON.parse(raw); } catch { return; }
        if (msg.setupComplete) {
          clearTimeout(timer);
          this.ws = ws; this.ready = true; this._openedAt = Date.now(); this._rotateWanted = false;
          this._startKeepalive();
          const q = this._queue; this._queue = [];
          q.forEach((d) => this._sendB64(d));
          console.log('[liveStt] session san sang');
          settle(true);
          return;
        }
        if (ws === this.ws) this._onMessage(msg);
      };
      ws.onclose = (ev) => {
        clearTimeout(timer);
        settle(false);
        if (ws !== this.ws) return;
        console.warn('[liveStt] session dong:', ev.code, ev.reason);
        this.ws = null; this.ready = false; this._stopKeepalive();
        this._queue = [];
        this._resolveFinish();      // lượt đang chờ thì trả về những gì đã có
      };
      ws.onerror = () => {};       // onclose luôn chạy sau đó
    });
  }

  _onMessage(msg) {
    if (msg.goAway) { this._rotateWanted = true; return; }
    const va = msg.voiceActivity?.type;
    if (va === 'ACTIVITY_START') { this.active = true; this.sawActivity = true; }
    if (va === 'ACTIVITY_END') { this.active = false; this._maybeFinish(); }
    const sc = msg.serverContent;
    if (!sc) return;
    // Bản chốt MUỘN của lượt đã huỷ/hết giờ không được rơi vào lượt mới: bỏ qua tới
    // khi thấy generationComplete của lượt cũ (hoặc hết hạn chờ).
    if (this._drainUntil) {
      if (sc.generationComplete || Date.now() > this._drainUntil) this._drainUntil = 0;
      return;
    }
    if (!this.inTurn) return;
    if (sc.interimInputTranscription?.text != null) {
      this.interim = sc.interimInputTranscription.text.trim();
      try { this.onText?.(this.text, false); } catch {}
    }
    if (sc.inputTranscription?.text) {
      this.finals.push(sc.inputTranscription.text.trim());
      this.interim = '';
      try { this.onText?.(this.text, true); } catch {}
    }
    if (sc.generationComplete && this._finish) this._resolveFinish('done');
  }

  _sendB64(data) {
    try {
      this.ws.send(JSON.stringify({ realtimeInput: { audio: { data, mimeType: 'audio/pcm;rate=16000' } } }));
      this._lastAudioAt = Date.now();
    } catch {}
  }

  _startKeepalive() {
    this._stopKeepalive();
    this._keepalive = setInterval(() => {
      if (!this.ready) return;
      const now = Date.now();
      if (!this.inTurn && now - this._lastUseAt > IDLE_CLOSE_MS) { this.close(); return; }
      if (now - this._openedAt > ROTATE_MS) this._rotateWanted = true;
      // Mở lại sớm lúc RẢNH để không bị server cắt giữa câu ở phút thứ 10.
      if (this._rotateWanted && !this.inTurn) { this.close(); this.ensureOpen(); return; }
      if (now - this._lastAudioAt >= KEEPALIVE_MS - 50) this._sendB64(SILENCE_B64);
    }, KEEPALIVE_MS);
  }

  _stopKeepalive() { if (this._keepalive) { clearInterval(this._keepalive); this._keepalive = null; } }

  /** Bắt đầu một lượt nói (gọi khi VAD vừa xác nhận có tiếng). */
  begin() {
    this._resetTurn();
    this.inTurn = true;
    this._lastUseAt = Date.now();
    if (!this.ready) this.ensureOpen();
  }

  /** PCM 16kHz Int16 từ voiceRecorder. Chưa sẵn sàng thì xếp hàng chờ. */
  send(pcm16) {
    for (let i = 0; i < pcm16.length; i += FRAME) {
      const d = b64(pcm16.subarray(i, i + FRAME));
      if (this.ready) this._sendB64(d);
      else if (this._queue.length < MAX_QUEUE) this._queue.push(d);
    }
  }

  /**
   * Kết thúc lượt: gửi audioStreamEnd (= "chốt ngay", hybrid VAD) rồi chờ bản chốt.
   * Trả { text, failed }: failed=true nghĩa là session hỏng/không mở được -> caller
   * dùng Whisper với file WAV đã ghi; text='' + failed=false = im lặng/nhiễu thật.
   */
  finish(timeoutMs = 1500) {
    if (!this.inTurn) return Promise.resolve({ text: '', failed: false });
    const wasReady = this.ready;
    if (wasReady) { try { this.ws.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } })); } catch {} }
    else this._queue = [];          // lượt này sẽ đi Whisper; đừng để audio cũ gửi lên session sau
    return new Promise((resolve) => {
      this._finish = { resolve, failed: !wasReady };
      this._finish.timer = setTimeout(() => this._resolveFinish('timeout'), wasReady ? timeoutMs : 0);
      // Server chưa từng thấy tiếng nói -> nhiều khả năng chỉ là nhiễu, không có bản
      // chốt nào sắp về; đợi ngắn thôi thay vì đủ timeout.
      if (wasReady && !this.sawActivity && !this.text) {
        clearTimeout(this._finish.timer);
        this._finish.timer = setTimeout(() => this._resolveFinish('timeout'), 350);
      }
      this._maybeFinish();
    });
  }

  // Server đã chốt đoạn cuối (không còn đang nghe, không còn chữ tạm) -> xong ngay,
  // khỏi chờ generationComplete. Hay gặp khi người dùng ngừng lâu hơn VAD của server.
  _maybeFinish() {
    if (this._finish && !this.active && !this.interim && this.finals.length) this._resolveFinish('done');
  }

  _resolveFinish(reason) {
    const f = this._finish;
    if (!f) return;
    this._finish = null;
    clearTimeout(f.timer);
    if (reason === 'timeout' && this.ready) this._drainUntil = Date.now() + 2000;
    const text = this.text;
    this.inTurn = false;
    f.resolve({ text, failed: f.failed && !text });
  }

  /** Huỷ lượt đang nghe (tắt mic tay / chen ngang báo nhầm): bỏ kết quả. */
  cancel() {
    if (!this.inTurn) return;
    if (this.ready) {
      try { this.ws.send(JSON.stringify({ realtimeInput: { audioStreamEnd: true } })); } catch {}
      if (this.sawActivity) this._drainUntil = Date.now() + 2000;
    }
    this._queue = [];
    // Đang chờ finish() thì phải trả kết quả rỗng, không được bỏ treo: caller đang
    // await nó và giữ khoá processingRef tới khi có kết quả.
    const f = this._finish;
    if (f) { this._finish = null; clearTimeout(f.timer); f.resolve({ text: '', failed: false }); }
    this.inTurn = false;
    this._resetTurn();
  }

  close() {
    this._stopKeepalive();
    const ws = this.ws;
    this.ws = null; this.ready = false; this._queue = [];
    this._resolveFinish();
    if (ws) { try { ws.close(); } catch {} }
  }
}

// ── Heuristic cho 2 ca khó: DỪNG (khi nào coi là nói xong) và CHEN NGANG ────────

const norm = (s) => String(s || '').toLowerCase().normalize('NFC')
  .replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean);

// Từ/cụm cuối câu cho thấy người nói CHƯA nói xong ("cho mình đi tới…", "ừm…").
const HANGING = new Set(['tới', 'đến', 'về', 'ở', 'cho', 'và', 'với', 'là', 'của', 'thì', 'mà',
  'tại', 'sang', 'qua', 'gần', 'muốn', 'cần', 'nhưng', 'hoặc', 'hay', 'bằng', 'từ', 'ra', 'vô',
  'vào', 'đường', 'quận', 'phường', 'số', 'chợ', 'trường', 'ừm', 'ờ', 'ơ', 'à', 'ừ', 'hmm']);
const HANGING_2 = new Set(['muốn đi', 'cần đi', 'đi tới', 'đi đến', 'đi về', 'đi ra', 'đi vô',
  'đi vào', 'đặt xe', 'đi xe', 'đại học', 'bệnh viện']);

/**
 * Bao lâu im lặng thì coi là NÓI XONG, dựa trên chữ Gemini đang nghe được:
 *  - chưa có chữ          -> 950ms (như nhánh Whisper)
 *  - đuôi lơ lửng ("đi tới", "ừm") -> 1600ms, chờ người dùng nói tiếp
 *  - model đã đặt dấu chấm/hỏi (câu trọn) -> 550ms, cắt sớm cho nhanh
 *  - còn lại              -> 800ms
 * Lỡ cắt sớm cũng không mất chữ: phần nói sau thành lượt kế, agent vẫn hiểu.
 */
export function silenceMsFor(text) {
  const t = String(text || '').trim();
  const w = norm(t);
  if (!w.length) return 950;
  const last = w[w.length - 1];
  const last2 = w.slice(-2).join(' ');
  if (HANGING.has(last) || HANGING_2.has(last2)) return 1600;
  if (/[.?!…]$/.test(t)) return 550;
  return 800;
}

// ── KHỬ TIẾNG VỌNG THEO THỜI GIAN ───────────────────────────────────────────────
// Tiếng AI lọt vào mic chỉ có thể là mấy từ AI VỪA phát ra loa quanh lượt nói này
// (tts.js: spokenWordsBetween). Nên khớp chữ Gemini nghe được với ĐÚNG những từ đó
// rồi gỡ ra, phần còn lại mới là lời người dùng. Đo trên Gemini thật: tiếng vọng
// to thì Gemini chép nguyên câu AI rồi nối lời người dùng phía sau; tiếng vọng lẫn
// ở bất kỳ đâu chứ không chỉ ở đầu.
//  - So sau khi BỎ DẤU ("mười" ~ "mươi") và coi mọi cụm SỐ là một: Gemini viết
//    "ba mươi nghìn" thành "30.000", "năm phút" thành "5 phút".
//  - Chỉ gỡ những đoạn trùng >=3 từ liên tiếp: tiếng vọng là cả chuỗi từ liền nhau;
//    người dùng đáp "ô tô" ngay sau khi AI hỏi "...hay ô tô?" chỉ trùng 2 từ -> giữ.
const NUM_WORDS = new Set(['một', 'hai', 'ba', 'bốn', 'tư', 'năm', 'lăm', 'sáu', 'bảy', 'tám',
  'chín', 'mười', 'mươi', 'mốt', 'trăm', 'nghìn', 'ngàn', 'triệu', 'tỷ', 'tỉ', 'linh', 'lẻ']);
const FILLERS = new Set(['ừm', 'ờ', 'ơ', 'à', 'hmm', 'ừa', 'um', 'uh']);
// Một từ đơn lẻ còn sót sau khi gỡ tiếng vọng chỉ được tính là chen ngang nếu là lệnh
// ngắn hay gặp (so sau khi bỏ dấu): không, dừng/đúng, thôi, huỷ, khoan, chờ, đợi/đổi...
const COMMANDS = new Set(['khong', 'dung', 'thoi', 'huy', 'khoan', 'cho', 'doi', 'vang', 'u',
  'co', 'duoc', 'ok', 'okay', 'sai', 'roi', 'stop', 'het']);
const fold = (w) => w.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');

/** Tách câu thành các "đơn vị" để khớp: mỗi từ một đơn vị, cả cụm số liền nhau gộp một. */
function units(text) {
  const out = [];
  String(text || '').split(/\s+/).filter(Boolean).forEach((raw, ti) => {
    const w = norm(raw).join(' ');
    if (!w) return;
    const isNum = /^\d/.test(w) || NUM_WORDS.has(w);
    const key = isNum ? '#' : fold(w);
    const last = out[out.length - 1];
    if (isNum && last && last.key === '#') { last.tokens.push(ti); return; }
    out.push({ key, word: w, tokens: [ti] });
  });
  return out;
}

/**
 * Gỡ tiếng vọng khỏi `text`, biết `echoWords` là các từ AI đã phát ra loa trong
 * khoảng thời gian của lượt nói. Trả { text: phần còn lại, removed: số đơn vị đã gỡ,
 * kept: số từ có nghĩa còn lại (bỏ từ đệm), keptKeys, total }.
 */
export function cancelEcho(text, echoWords) {
  const raw = String(text || '').split(/\s+/).filter(Boolean);
  const A = units(text);
  const B = units((echoWords || []).join(' '));
  const removedTok = new Set();
  let removed = 0;
  if (A.length && B.length) {
    // LCS rồi lần ngược để lấy các cặp khớp (i trong câu nghe được, j trong lời AI).
    const n = A.length, m = B.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = 1; i <= n; i++) {
      for (let j = 1; j <= m; j++) {
        dp[i][j] = A[i - 1].key === B[j - 1].key ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
    const pairs = [];
    for (let i = n, j = m; i > 0 && j > 0;) {
      if (A[i - 1].key === B[j - 1].key) { pairs.push([i - 1, j - 1]); i--; j--; }
      else if (dp[i - 1][j] >= dp[i][j - 1]) i--;
      else j--;
    }
    pairs.reverse();
    // Gom thành đoạn liền nhau, cho phép hụt: tối đa 2 từ bên câu nghe được (Gemini
    // nghe 1 từ thành 2: "đồng" -> "đô la"), 1 từ bên lời AI (sót một từ). Đoạn >=3 cặp
    // = tiếng vọng: gỡ luôn cả từ nghe sai kẹp giữa.
    let run = [];
    const flush = () => {
      if (run.length >= 3) {
        for (let i = run[0][0]; i <= run[run.length - 1][0]; i++) {
          A[i].tokens.forEach((t) => removedTok.add(t));
          removed++;
        }
      }
      run = [];
    };
    for (const p of pairs) {
      const prev = run[run.length - 1];
      if (prev && (p[0] - prev[0] > 3 || p[1] - prev[1] > 2)) flush();
      run.push(p);
    }
    flush();
  }
  const keep = A.filter((u) => !u.tokens.some((t) => removedTok.has(t)));
  const meaningful = keep.filter((u) => !FILLERS.has(u.word));
  return {
    text: removed ? raw.filter((_, i) => !removedTok.has(i)).join(' ') : String(text || '').trim(),
    removed,
    kept: meaningful.length,
    keptKeys: meaningful.map((u) => u.key),
    total: A.length,
  };
}

/**
 * Sau khi gỡ tiếng vọng, phần còn lại có đủ để coi là người dùng CHEN NGANG THẬT
 * không: >=2 từ có nghĩa, hoặc 1 từ khi cả câu chỉ có 1-2 từ ("không", "dừng") hay
 * là lệnh ngắn. Một từ lẻ sót lại giữa cả tràng tiếng vọng = Gemini nghe sai, bỏ.
 */
export function isBargeIn(res) {
  if (!res || !res.kept) return false;
  if (res.kept >= 2) return true;
  return res.total <= 2 || COMMANDS.has(res.keptKeys[0]);
}

import { useCallback, useEffect, useRef } from 'react';
import { useApp, saveTtsEngine } from '../context/AppContext';
import * as api from '../services/api';
import { speak, stop as stopSpeech, unlockAudio, isSpeaking,
  pauseSpeech, resumeSpeech, currentSpeechText, setTtsEngine, spokenWordsBetween } from '../services/tts';
import { createSpeechQueue } from '../services/tts';   // _send: đọc từng câu của lời đáp đang stream
import VoiceRecorder from '../services/voiceRecorder';
import { connectSocket, emitPassengerWaiting, disconnectSocket } from '../services/socket';
import { startBeacon, stopBeacon, setBeaconIntensity } from '../services/beacon';
import { browserRecognize, isBrowserSttSupported } from '../services/browserStt';
import LiveStt, { silenceMsFor, assessTurn, bargeTimeout } from '../services/liveStt';
import { startTurn, mark as traceMark, endTurn, currentTurnId } from '../services/turnTrace';

export default function useVoiceApp() {
  const { state, dispatch } = useApp();
  const recorderRef = useRef(null);
  const busyRef = useRef(false);
  const socketRef = useRef(null);
  const recordingRef = useRef(false);   // mirror of state.recording (no stale guard)
  const messagesRef = useRef([]);       // latest conversation (no stale history)
  const userRef = useRef(null);         // logged-in user (id used for driver matching)
  const emptyRef = useRef(0);           // consecutive "heard nothing" count
  const startedRef = useRef(false);     // auto-start greeting only once
  const streamRef = useRef(null);       // timer for word-by-word text streaming
  const arrivedRef = useRef(false);     // announce PIN once per trip (guard double events)
  const pausedRef = useRef(false);      // user manually turned the mic OFF -> stop auto-listen
  const pickupRef = useRef(null);       // rider's live GPS {lat,lng}; null -> backend default
  const distBucketRef = useRef(null);   // last spoken proximity bucket (avoid TTS spam)
  const processingRef = useRef(false);  // đang STT/gọi agent -> KHÔNG được mở lại mic
  const agentTurnRef = useRef(null);    // _send: lượt agent đang stream/đọc (api.runAgentTurn) -> ngắt được
  const turnSeqRef = useRef(0);         // _send: số thứ tự lượt; hẹn giờ của lượt cũ thấy lệch -> bỏ qua
  const sttEngineRef = useRef(state.sttEngine);  // 'whisper' (mặc định) | 'gemini-live'
  const liveRef = useRef(null);         // session Gemini Live mở sẵn (chỉ khi bật nhánh mới)
  const bargeRef = useRef({ pending: false, timer: null, tts: '', t0: 0 });  // chen ngang chờ xác nhận
  const ttsEngineRef = useRef(state.ttsEngine);
  const echoCountRef = useRef(0);       // số lần bắt được tiếng AI vọng vào mic (giọng trình duyệt)

  // Sau khi AI bắt đầu đọc, chờ chừng này rồi mới mở mic (cho phép chen ngang).
  //  - Gemini Live: 1s. Báo nhầm chỉ làm AI khựng thoáng rồi đọc tiếp (Gemini phải
  //    xác nhận lời thật mới dừng hẳn), nên không cần khoá lâu. Giữ 1s vì bộ khử vọng
  //    của mic cần chừng đó để bắt kịp tiếng loa vừa phát, và mic dùng 1s này để học
  //    mức tiếng vọng (voiceRecorder: _echoPeak).
  //  - Whisper: 4s như cũ — nhánh này dừng HẲN AI ngay khi VAD kêu, không xác nhận được.
  // Vặn bằng ?bargein=2000 để thử trên máy thật, khỏi build lại.
  const BARGE_IN_ARM_Q = Number(new URLSearchParams(window.location.search).get('bargein'));
  const armMs = () => (BARGE_IN_ARM_Q > 0 ? BARGE_IN_ARM_Q
    : (sttEngineRef.current === 'gemini-live' ? 1000 : 4000));
  // P4: lúc AI đang đọc, nhánh Gemini Live xác nhận tiếng nói sau 5 khung (~425ms)
  // thay vì 8 (~680ms) -> AI im sớm hơn ~250ms. ?vadframestts=6 để chỉnh.
  const VAD_FRAMES_TTS = (() => {
    const v = Number(new URLSearchParams(window.location.search).get('vadframestts'));
    return v > 0 ? v : 5;
  })();
  // Nhánh Gemini Live: chen ngang lúc AI đang đọc chỉ TẠM DỪNG giọng AI; trong chừng
  // này ms mà Gemini không nghe ra chữ thật nào (khác tiếng AI vọng lại) thì coi như
  // báo nhầm, đọc tiếp. Vặn bằng ?bargeconfirm=2000.
  const BARGE_CONFIRM_MS = (() => {
    const v = Number(new URLSearchParams(window.location.search).get('bargeconfirm'));
    return v > 0 ? v : 1500;
  })();
  // Hết BARGE_CONFIRM_MS mà server VẪN đang nghe thấy tiếng nói -> gia hạn MỘT lần chừng
  // này (xác nhận thật chậm nhất đo trên Gemini thật: 1809ms, eval live V1c) thay vì vứt
  // lượt nói thật. ?bargeextend=
  const BARGE_EXTEND_MS = (() => {
    const v = Number(new URLSearchParams(window.location.search).get('bargeextend'));
    return v > 0 ? v : 700;
  })();

  // Latest-value refs so the hands-free loop callbacks can call each other
  // without stale closures.
  const startListeningRef = useRef(() => {});
  const sendRef = useRef(() => {});

  useEffect(() => { recordingRef.current = state.recording; }, [state.recording]);
  useEffect(() => { messagesRef.current = state.messages; }, [state.messages]);
  useEffect(() => { userRef.current = state.user; }, [state.user]);

  useEffect(() => { setTtsEngine(state.ttsEngine); ttsEngineRef.current = state.ttsEngine; }, [state.ttsEngine]);

  // Giọng trình duyệt cứ vọng vào mic -> TỰ đổi sang giọng Edge (thẻ <audio> đi qua bộ
  // khử vọng của mic, speechSynthesis trên Android thì nhiều khi không). Người khiếm
  // thị không thể tự nhận ra "AI đang tự cắt lời mình" rồi đi tìm nút trên Header,
  // nên app phải tự làm. Nhớ theo máy: lần sau mở app là đúng giọng luôn.
  const noteEcho = useCallback((where) => {
    console.warn('[echo] mic nghe lai giong AI:', where, '| giong =', ttsEngineRef.current);
    if (ttsEngineRef.current !== 'browser') return;
    echoCountRef.current += 1;
    if (echoCountRef.current < 2) return;
    console.warn('[echo] giong trinh duyet vong vao mic qua nhieu -> tu doi sang giong Edge');
    ttsEngineRef.current = 'edge';
    setTtsEngine('edge');
    saveTtsEngine('edge');
    dispatch({ type: 'SET_TTS_ENGINE', payload: 'edge' });
  }, [dispatch]);

  // Bật nhánh Gemini Live -> mở session NGAY (lúc đang đọc lời chào), vì mở mới tốn
  // ~1.3-2s; tắt -> đóng hẳn. Lượt đang nghe dở vẫn đi tiếp theo nhánh lúc nó bắt đầu.
  useEffect(() => {
    sttEngineRef.current = state.sttEngine;
    if (state.sttEngine === 'gemini-live') {
      if (!liveRef.current) liveRef.current = new LiveStt();
      liveRef.current.ensureOpen();
    } else if (liveRef.current) {
      liveRef.current.close();
      liveRef.current = null;
    }
  }, [state.sttEngine]);

  // Grab the rider's real GPS once so pickup = their current location (not a
  // hardcoded origin). If denied/unavailable, pickupRef stays null and the
  // backend falls back to its default pickup.
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude, lng = pos.coords.longitude;
        pickupRef.current = { lat, lng };
        // Move the pickup marker (🧍) on the map to the real GPS spot, not ĐH Quốc tế.
        dispatch({ type: 'SET_ORIGIN', payload: { name: 'Vị trí của bạn', lat, lng } });
      },
      (err) => { console.warn('Geolocation unavailable, using default pickup:', err?.message); },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    );
  }, [dispatch]);

  // Stream the agent reply word-by-word onto the stage (async, like ChatGPT) so
  // judges see the LLM "typing" while the TTS speaks.
  const _streamText = useCallback((text) => {
    if (streamRef.current) clearTimeout(streamRef.current);
    dispatch({ type: 'SET_STREAM', payload: '' });
    const words = String(text || '').split(/(\s+)/);   // keep whitespace tokens
    let i = 0, acc = '';
    const tick = () => {
      acc += words[i++];
      dispatch({ type: 'SET_STREAM', payload: acc });
      streamRef.current = i < words.length ? setTimeout(tick, 45) : null;
    };
    if (words.length) tick();
  }, [dispatch]);

  // Hands-free: after the agent speaks (or we hear nothing), reopen the mic.
  // delayMs lớn (armMs()) dùng khi AI vừa bắt đầu đọc: mở mic ngay lúc đó
  // thì mấy giây đầu rất dễ bị tiếng ồn cắt ngang câu trả lời.
  const _autoListen = useCallback((delayMs = 450) => {
    setTimeout(() => {
      // Không mở lại khi: đang xử lý lượt trước, đang thu, hoặc người dùng tự tắt mic.
      if (busyRef.current || processingRef.current || recordingRef.current || pausedRef.current) return;
      startListeningRef.current();
    }, delayMs);
  }, []);

  // ---- Speech-to-text (Whisper via backend, fallback) ----
  const _listenWhisper = useCallback(async () => {
    if (!recorderRef.current || typeof recorderRef.current.start !== 'function') {
      recorderRef.current = new VoiceRecorder();
    }
    const recorder = recorderRef.current;
    // Nhánh của LƯỢT NÀY, chốt lúc bắt đầu nghe (đổi nút giữa chừng không làm hỏng lượt).
    const live = sttEngineRef.current === 'gemini-live' ? liveRef.current : null;
    // MỘT đối tượng trạng thái cho MỖI lần nghe. Mọi bên đọc/ghi trạng thái chen ngang —
    // live.onText / live.onActivity, hẹn giờ xác nhận, onAutoStop (đang await finish /
    // Whisper), toggleListening / stopListening (qua bargeRef) — đều cầm đúng đối tượng của
    // lượt mình. Callback / hẹn giờ của lượt cũ đến muộn thấy !isCurrent() thì không được
    // dừng / đọc tiếp giọng AI hay đóng mic của lượt mới.
    clearTimeout(bargeRef.current.timer);
    bargeRef.current.pending = false;
    const turn = {
      pending: false,          // AI đang TẠM DỪNG chờ xác nhận chen ngang
      timer: null, extended: false,
      tts: '',                 // câu AI đang đọc lúc VAD kêu ('' = AI đã im)
      t0: performance.now(),   // mốc đầu âm thanh của lượt (gồm đoạn tiền ghi)
      voiceNow: false,         // VAD cục bộ đang nghe thấy giọng
      last: null,              // assessTurn('interim') gần nhất
      traceId: null,           // lượt turnTrace do lần nghe này mở (onSpeechStart)
    };
    bargeRef.current = turn;
    const isCurrent = () => bargeRef.current === turn;
    // Ghi thời gian lượt (turnTrace) — CHỈ vào lượt do lần nghe này mở. Không nghe thấy gì
    // thì không mở lượt, khỏi ghi nhầm mốc vào lượt _send còn đang mở.
    const tm = (name, data) => { if (turn.traceId != null && currentTurnId() === turn.traceId) traceMark(name, data); };
    const te = (outcome, data) => { if (turn.traceId != null && currentTurnId() === turn.traceId) endTurn(outcome, data); };
    // Từ AI đã phát ra loa quanh lượt nói này (từ đầu đoạn tiền ghi, nới 0.8s) = thứ
    // DUY NHẤT có thể là tiếng vọng.
    const echoWords = () => spokenWordsBetween(turn.t0 - 800, performance.now() + 300);
    // BẰNG CHỨNG của lượt tại lúc này -> assessTurn / bargeTimeout (liveStt.js) quyết định.
    // Mọi quyết định chen ngang / tiếng vọng / chữ gửi agent đi qua đúng hai hàm thuần đó.
    const evidence = (text) => ({
      text: text != null ? text : (live && live.inTurn ? live.text : ''),
      echoWords: echoWords(),
      aiSpeakingAtStart: !!turn.tts,
      hasFinal: !!(live && live.finals.length),
      interimPending: !!(live && live.interim),
      serverActive: !!(live && live.active),
      serverHeardSpeech: !!(live && live.sawActivity),
      localVoice: turn.voiceNow,
      sessionLost: !!live && (live.turnDropped || !live.ready),
    });
    // Chen ngang THẬT: dừng hẳn giọng AI.
    const confirmBarge = () => {
      if (!turn.pending) return;
      clearTimeout(turn.timer);
      turn.pending = false;
      tm('bargeConfirm', { barge: 'confirmed' });
      if (!isCurrent()) return;
      stopSpeech();
      dispatch({ type: 'SET_STATUS', payload: { main: '🎧 Nghe thấy bạn nói…', sub: '' } });
    };
    // BÁO NHẦM: bỏ đoạn ghi, AI đọc tiếp đúng chỗ dở, mở nghe lại.
    const falseAlarm = (kind) => {
      if (!turn.pending) return;
      clearTimeout(turn.timer);
      turn.pending = false;
      tm('bargeFalseAlarm', { barge: `false-alarm-${kind}` });
      te('false-alarm');
      if (!isCurrent()) return;
      console.log(`[Barge-in] bao nham (${kind}) -> doc tiep`);
      live.cancel();
      dispatch({ type: 'SET_TRANSCRIPT', payload: '' });
      recorder.stop();               // bỏ đoạn ghi này
      recordingRef.current = false;
      dispatch({ type: 'SET_RECORDING', payload: false });
      resumeSpeech();
      _autoListen(300);
    };
    // Có bằng chứng mới (chữ / server ngừng nghe tiếng) trong lúc AI đang tạm dừng.
    const decideInterim = () => {
      if (!turn.pending || !isCurrent()) return;
      const a = assessTurn(evidence(), 'interim');
      turn.last = a;
      if (a.verdict === 'user') confirmBarge();
      else if (a.verdict === 'echo') falseAlarm('fast');
    };
    // Hết hạn chờ xác nhận: bargeTimeout chọn hard-stop / extend / discard.
    const onBargeTimer = () => {
      if (!turn.pending || !isCurrent()) return;
      const act = bargeTimeout(evidence(), turn.extended);
      if (act === 'hard-stop') {        // session rớt: không xác nhận được nữa -> Whisper chốt
        console.warn('[Barge-in] session Gemini rot -> dung han TTS, chot bang Whisper');
        confirmBarge();
      } else if (act === 'extend') {
        turn.extended = true;
        tm('bargeExtend');
        console.log(`[Barge-in] server con nghe tieng -> cho them ${BARGE_EXTEND_MS}ms`);
        turn.timer = setTimeout(onBargeTimer, BARGE_EXTEND_MS);
      } else {
        falseAlarm('timer');           // không có chữ nào của người dùng: tiếng vọng / ho / xe chạy
      }
    };
    if (live) {
      live.ensureOpen();       // thường đã mở sẵn; hỏng thì lượt này tự lùi về Whisper
      live.onText = () => {
        if (!isCurrent()) return;
        const a = assessTurn(evidence(), 'interim');
        turn.last = a;
        // Phụ đề trực tiếp trong lúc nói (Whisper không có cái này) — đã gỡ tiếng vọng.
        if (a.res.kept) dispatch({ type: 'SET_TRANSCRIPT', payload: a.userText });
        decideInterim();
      };
      live.onActivity = (active) => { if (!active) decideInterim(); };
    }
    try {
      await recorder.start({
        silenceMs: 950,          // cut off a bit sooner -> lower latency
        // Gemini Live: thời điểm DỪNG theo chữ đang nghe ĐÃ GỠ VỌNG (câu trọn cắt sớm,
        // đuôi lơ lửng chờ thêm) + stream PCM ngay khi VAD xác nhận tiếng nói. Chữ thô
        // thì câu AI vọng vào (luôn có dấu chấm) làm lượt bị cắt sau 550ms.
        getSilenceMs: live ? () => silenceMsFor(live.inTurn && turn.last ? turn.last.userText : '') : null,
        onPcm: live ? (pcm) => live.send(pcm) : null,
        speechFramesTts: live ? VAD_FRAMES_TTS : 0,
        // Không nghe được gì thì bỏ cuộc sau 9s rồi mở lại. Trước để 20s: mỗi lần
        // trượt là màn hình đứng im 20 giây nên nhìn như treo hẳn.
        noSpeechMs: 9000,
        // Cho bộ nhận giọng biết AI có đang đọc hay không -> nó tự nâng ngưỡng lúc
        // đó, khỏi nghe lại tiếng của chính mình rồi tự cắt lời.
        isTtsPlaying: isSpeaking,
        // Đèn báo mic đang nghe thấy giọng -> nút mic đổi trạng thái + hiện chữ
        // "Đang nghe bạn nói…". Nhìn thấy được nên biết ngay VAD có ăn hay không.
        onVoice: (active) => {
          turn.voiceNow = active;
          dispatch({ type: 'SET_VOICE_ACTIVE', payload: active });
        },
        onSpeechStart: () => {
          // CHEN NGANG, nhánh Gemini Live: VAD năng lượng hay báo nhầm (ho, xe chạy,
          // tiếng AI vọng ra loa). Nên chỉ TẠM DỪNG giọng AI, để assessTurn quyết khi có
          // chữ (xem decideInterim / onBargeTimer). Session chưa sẵn sàng thì không xác
          // nhận được -> dừng cứng như nhánh Whisper.
          turn.tts = isSpeaking() ? currentSpeechText() : '';
          turn.t0 = performance.now() - recorder.preRollMs;   // âm thanh của lượt bắt đầu từ đây
          turn.traceId = startTurn({ engine: live ? 'gemini-live' : 'whisper', duringTts: !!turn.tts,
            preRollMs: Math.round(recorder.preRollMs) });
          tm('speech');
          if (live) {
            live.begin();
            if (turn.tts && live.ready && pauseSpeech()) {
              console.log('[Barge-in] tam dung TTS, cho Gemini xac nhan...');
              turn.pending = true;
              tm('bargePause');
              turn.timer = setTimeout(onBargeTimer, BARGE_CONFIRM_MS);
              dispatch({ type: 'SET_STATUS', payload: { main: '🎧 Nghe thấy bạn nói…', sub: '' } });
              return;
            }
          }
          console.log('[Barge-in] Speech detected! Stopping TTS...');
          if (turn.tts) tm('bargeHardStop', { barge: 'hard-stop' });
          stopSpeech(); // Barge-in: cut off AI immediately when user speaks
          dispatch({ type: 'SET_STATUS', payload: { main: '🎧 Nghe thấy bạn nói…', sub: '' } });
        },
        onAutoStop: async () => {
          clearTimeout(turn.timer);
          tm('endpoint', recorder.cappedTurn ? { cappedTurn: true } : undefined);
          const wavBlob = await recorder.stop();
          recordingRef.current = false;
          dispatch({ type: 'SET_RECORDING', payload: false });
          dispatch({ type: 'SET_VOICE_ACTIVE', payload: false });

          // Ghi âm quá ngắn (ho, cộp, người dùng im) -> nghe lại ngay, đừng gửi lên
          // STT làm gì. recorder.stop() trả null khi VAD chưa từng thấy tiếng nói.
          if (!wavBlob || wavBlob.size <= 1000) {
            if (live) live.cancel();
            if (turn.pending) { turn.pending = false; if (isCurrent()) resumeSpeech(); }
            te('too-short');
            // Mic không trả âm thanh nào (AudioContext treo: mở mic không có cú chạm, iOS
            // bị cuộc gọi ngắt). Tự mở lại cũng điếc y vậy, mà chạm lúc mic "đang nghe"
            // lại thành TẮT mic. Nên dừng vòng tự nghe, chờ MỘT cú chạm (cú chạm đó gọi
            // unlockAudio -> resume AudioContext rồi mở mic).
            if (recorder.noAudio && recorder.audioContext?.state !== 'running') {
              dispatch({ type: 'SET_STATUS', payload: { main: 'Micro chưa chạy', sub: 'Chạm vào màn hình để nói' } });
              return;
            }
            _autoListen();
            return;
          }

          // ĐÃ có ghi âm -> khoá mic cho tới khi xử lý xong hẳn. Không có cờ này thì
          // _autoListen ở nhánh khác có thể mở mic ngay giữa lúc đang STT/gọi agent.
          processingRef.current = true;
          dispatch({ type: 'SET_STATUS', payload: { main: 'Đang nhận diện giọng nói…', sub: '' } });
          let text = '';
          let liveText = '';      // chữ Gemini có được (có thể dở dang) -> lưới đỡ nếu Whisper cũng hỏng
          let useWhisper = !live;
          if (live) {
            const t0 = performance.now();
            const r = await live.finish();
            console.log(`[liveStt] chot luot sau ${Math.round(performance.now() - t0)}ms:`, r);
            tm('liveFinal', { finishReason: r.reason, liveFailed: !!r.failed });
            text = r.text;
            liveText = r.text || '';
            // Session hỏng/không mở được -> file WAV vẫn còn, gửi Whisper như cũ.
            if (r.failed) { console.warn('[liveStt] session hong -> Whisper'); useWhisper = true; }
          }
          if (useWhisper) try {
            tm('whisperStart');
            const r = await api.speechToText(wavBlob, 'speech.wav');
            tm('whisperEnd', r.error ? { whisperError: true } : undefined);
            text = r.text;
            // r.error = Whisper THẬT SỰ lỗi (hết quota/mạng...), khác với text='' đơn
            // thuần (im lặng/nhiễu). Chỉ lùi sang Web Speech API của trình duyệt (free,
            // không qua server) khi đúng là lỗi — lưới đỡ cũ (FPT) đã hết dùng được.
            if (!text && r.error && isBrowserSttSupported()) {
              console.warn('Whisper failed, fallback to browser STT:', r.error);
              dispatch({ type: 'SET_STATUS', payload: { main: 'Đang nghe (dự phòng)…', sub: '' } });
              text = await browserRecognize('vi-VN');
            }
          } catch (err) {
            console.warn('STT failed:', err);
            if (isBrowserSttSupported()) {
              text = await browserRecognize('vi-VN');
            }
          } finally {
            processingRef.current = false;   // dù hỏng cũng phải nhả khoá, không thì kẹt luôn
          }
          processingRef.current = false;     // nhánh Gemini Live không đi qua finally ở trên
          if (!text && liveText) text = liveText;   // nửa câu còn hơn mất cả lượt
          // Trong lúc chờ STT mà đã có lần nghe MỚI (tắt mic / bật lại) -> lượt này đã bị
          // thay: không gửi, không đụng giọng AI của lượt mới.
          if (!isCurrent()) { te('superseded'); return; }

          // Chữ chốt lượt -> assessTurn('final') (cả 2 nhánh STT: trước đây Whisper chép lại
          // tiếng vọng rồi gửi ngược vào agent như lời người dùng).
          if (text) {
            const a = assessTurn(evidence(text), 'final');
            if (a.res.removed) {
              console.log('[echo] go tieng vong:', JSON.stringify(text), '->', JSON.stringify(a.res.text), a.reason);
              // Nhánh Whisper dừng HẲN AI ngay khi VAD kêu, không có Gemini xác nhận ->
              // giọng trình duyệt cứ vọng thì AI tự cắt lời mình: lúc đó mới đổi sang
              // Edge. Nhánh Gemini Live giữ giọng trình duyệt (nhanh) vì đã lọc được.
              if (useWhisper && a.res.removed >= 3) noteEcho('whisper');
            }
            text = a.userText;
          }
          if (turn.pending) {
            // Nói xong TRƯỚC khi kịp xác nhận (câu rất ngắn: "không", "huỷ").
            if (text) confirmBarge();
            else {
              turn.pending = false; resumeSpeech();
              tm('bargeFalseAlarm', { barge: 'false-alarm-endpoint' });
              dispatch({ type: 'SET_TRANSCRIPT', payload: '' });
            }
          }

          if (text) {
            emptyRef.current = 0;
            // Lượt để MỞ: _send ghi tiếp mốc gọi agent / tiếng đầu tiên rồi tự đóng.
            tm('text', { textLen: text.length, sttUsed: useWhisper ? 'whisper' : 'gemini-live' });
            dispatch({ type: 'SET_TRANSCRIPT', payload: text });
            sendRef.current(text);
          } else {
            te('empty', { sttUsed: useWhisper ? 'whisper' : 'gemini-live' });
            // Không ra chữ (im lặng / nhiễu / STT lỗi) -> tự mở nghe tiếp, có nhắc
            // nhẹ sau vài lần trượt liên tiếp để người dùng biết mà nói lại.
            emptyRef.current += 1;
            if (emptyRef.current >= 3) {
              emptyRef.current = 0;
              dispatch({ type: 'SET_STATUS', payload: { main: 'Mình chưa nghe rõ', sub: 'Bạn nói lại giúp mình nhé' } });
            }
            _autoListen();
          }
        },
      });
    } catch (err) {
      console.warn('Recorder start failed:', err);
      recordingRef.current = false;
      dispatch({ type: 'SET_RECORDING', payload: false });
      dispatch({ type: 'SET_STATUS', payload: { main: 'Không bật được micro', sub: 'Cho phép micro rồi chạm màn hình' } });
    }
  }, [dispatch, _autoListen, noteEcho]);

  // ---- Start / stop listening ----
  const startListening = useCallback((stopTts = false) => {
    console.log('[startListening] trigger attempt. busy=', busyRef.current, 'recording=', recordingRef.current);
    if (busyRef.current || recordingRef.current) return;
    recordingRef.current = true;
    dispatch({ type: 'SET_RECORDING', payload: true });
    dispatch({ type: 'SET_STATUS', payload: { main: '🎙️ Đang nghe…', sub: 'Nói điểm đến của bạn' } });
    dispatch({ type: 'SET_TRANSCRIPT', payload: '' });
    if (stopTts === true) stopSpeech();
    // Always use Groq Whisper (record -> backend STT) on every device for
    // consistent, accurate Vietnamese recognition.
    _listenWhisper();
  }, [dispatch, _listenWhisper]);
  startListeningRef.current = startListening;

  const stopListening = useCallback(() => {
    const r = recorderRef.current;
    if (r) { try { r.stop(); } catch {} }
    liveRef.current?.cancel();
    const b = bargeRef.current;
    if (b.pending) { clearTimeout(b.timer); b.pending = false; stopSpeech(); }
    recordingRef.current = false;
    dispatch({ type: 'SET_RECORDING', payload: false });
  }, [dispatch]);

  // Tap anywhere (gesture zone / mic button) to start or stop — fallback to the
  // hands-free flow (e.g. if the browser blocked auto-start without a gesture).
  const toggleListening = useCallback(() => {
    unlockAudio();   // keep mobile audio unlocked on every tap
    // Đang nhận diện câu vừa gửi -> bỏ qua cú chạm (bấm đúp không được huỷ câu đó,
    // cũng không được mở mic chen vào giữa lúc đang xử lý).
    if (processingRef.current) return;
    if (recordingRef.current) {
      // Bấm nút lúc đang nói = NÓI XONG -> chốt và gửi ngay (không đợi im lặng, cũng
      // không phải tắt mic rồi đứng im). Bấm là chủ ý chen ngang, nên nếu AI đang tạm
      // dừng chờ xác nhận thì dừng hẳn luôn.
      const rec = recorderRef.current;
      if (rec?.heardSpeech) {
        const b = bargeRef.current;
        if (b.pending) { clearTimeout(b.timer); b.pending = false; stopSpeech(); }
        if (rec.finishNow()) return;
      }
      // Chưa nghe thấy tiếng nói nào -> không có gì để gửi: tắt mic như cũ.
      pausedRef.current = true;
      stopListening();
      dispatch({ type: 'SET_STATUS', payload: { main: 'Đã tắt micro', sub: 'Chạm nút để nói tiếp' } });
      return;
    }
    if (busyRef.current) { pausedRef.current = true; return; }
    // Manual ON -> resume the SAME conversation (memory intact).
    pausedRef.current = false;
    emptyRef.current = 0;
    startListening(true);
  }, [startListening, stopListening, dispatch]);

  // ---- Connection fallback ----
  // The LLM agent is the ONLY source of destinations. If it's unreachable we do
  // NOT guess a place locally (that produced wrong places like "Điện Biên Phủ" +
  // NaN price) — we just ask the user to retry.
  // PHẢI khai báo TRƯỚC _send: _send có nó trong dependency array, mà dep array được
  // đánh giá ngay lúc render -> đặt sau sẽ ném TDZ "Cannot access ... before
  // initialization" và làm trắng cả trang.
  const _localFallback = useCallback(() => {
    const msg = 'Xin lỗi, mình chưa kết nối được máy chủ. Bạn thử nói lại sau giây lát nhé.';
    dispatch({ type: 'SET_STATUS', payload: { main: 'Chưa kết nối được trợ lý', sub: 'Kiểm tra mạng rồi thử lại' } });
    _streamText(msg);
    speak(msg).catch(console.error);
  }, [dispatch, _streamText]);

  // Chỉ _send dùng: lời đáp stream tới từng câu -> gõ TIẾP câu mới sau các câu đã hiện
  // (`shown`), không gõ lại từ đầu như _streamText. Khai báo trước _send (dep array).
  const _streamAppend = useCallback((shown, more) => {
    if (streamRef.current) clearTimeout(streamRef.current);
    const words = String(more || '').split(/(\s+)/);
    let i = 0, acc = shown ? `${shown} ` : '';
    dispatch({ type: 'SET_STREAM', payload: acc });
    const tick = () => {
      acc += words[i++];
      dispatch({ type: 'SET_STREAM', payload: acc });
      streamRef.current = i < words.length ? setTimeout(tick, 45) : null;
    };
    if (words.length) tick();
  }, [dispatch]);

  // ---- Send a turn to the agent (or local fallback) ----
  const _send = useCallback(async (text) => {
    if (!text || busyRef.current) return;
    const seq = ++turnSeqRef.current;     // hẹn giờ của lượt cũ từ giờ tự bỏ qua
    busyRef.current = true;
    dispatch({ type: 'SET_BUSY', payload: true });
    dispatch({ type: 'SET_STATUS', payload: { main: '🤖 Đang xử lý…', sub: text } });
    // turnTrace: lượt đo do nhánh nghe mở (startTurn); _send chỉ ghi mốc + đóng ĐÚNG lượt
    // đó. Chen ngang thì nhánh nghe mở lượt mới -> mốc/đóng muộn của lượt này phải bỏ
    // qua, không được rơi vào lượt của câu người dùng vừa nói.
    let traceId = null;
    try { traceId = currentTurnId(); } catch (e) {}
    const mine = () => { try { return traceId != null && currentTurnId() === traceId; } catch (e) { return false; } };
    const tm = (name, data) => { if (mine()) { try { traceMark(name, data); } catch (e) {} } };
    const endMine = (outcome) => { if (mine()) { try { endTurn(outcome); } catch (e) {} } };
    // Lượt trước còn stream / còn câu chờ đọc (thường chen ngang đã stop() nó rồi) ->
    // ngắt hẳn, rồi CHỜ lịch sử của nó chốt (phần người dùng đã nghe + mọi kết quả tool
    // đã chạy, vd đã đặt xe) trước khi lượt này đọc messagesRef bên dưới. Thường xong
    // ngay; tối đa ~DRAIN_AFTER_CUT_MS khi stream cũ còn đang chạy tool.
    const prevTurn = agentTurnRef.current;
    agentTurnRef.current = null;
    if (prevTurn) {
      await Promise.race([prevTurn.cut(), new Promise((r) => setTimeout(r, api.DRAIN_AFTER_CUT_MS + 1000))]);
    }

    let keepListening = true;
    let released = false;
    // Nhả khoá đúng MỘT lần. Lời đáp stream thì nhả ngay khi có câu đầu (như bản cũ nhả
    // ngay khi có lời đáp), để mic mở được cho chen ngang trong lúc LLM viết tiếp.
    const release = () => {
      if (released) return;
      released = true;
      busyRef.current = false;
      dispatch({ type: 'SET_BUSY', payload: false });
    };
    // Mở mic sau delayMs, xét LÚC HẸN GIỜ CHẠY: chỉ khi lượt này vẫn là lượt mới nhất và
    // còn được nghe tiếp (không phải sau đặt xe / kết thúc). Hẹn giờ của lượt cũ (kể cả
    // lưới an toàn armMs()+5000) nhờ vậy không mở mic giữa một lượt sau (A#6).
    const listenLater = (delayMs) => setTimeout(() => {
      if (keepListening && turnSeqRef.current === seq) _autoListen(0);
    }, delayMs);
    // Lời đáp đọc xong TRỌN mới mở mic sau 150ms (P1). Bị chen ngang / speak() khác chen
    // vào thì hàng đợi báo interrupted -> không coi là "đọc xong".
    const afterSpeech = (drained) => drained.then((r) => {
      if (r.interrupted) { endMine('interrupted'); return; }
      tm('reply_spoken');
      endMine('ok');
      listenLater(150);
    });
    let bookedSpeech = null;
    let bookedApplied = false;          // ui.booked chỉ được áp (bắt đầu tìm tài xế, báo) MỘT lần

    try {
      // ALWAYS send to the LLM agent. (Don't gate on a one-shot health check —
      // a single transient failure must not silently downgrade to the tiny local
      // place matcher, which returns wrong places like "Tôn Đức Thắng".)
      const newMessages = [...messagesRef.current, { role: 'user', content: text }];
      messagesRef.current = newMessages;
      dispatch({ type: 'SET_MESSAGES', payload: newMessages });

      // Stream (/api/agent/chat_stream): đọc câu 1 trong lúc LLM còn viết câu 2. Stream
      // lỗi trước câu đầu -> runAgentTurn tự lùi về /api/agent/chat (result.legacy).
      let shown = '';
      tm('agent_request');
      const turn = api.runAgentTurn(newMessages, pickupRef.current, {
        createQueue: createSpeechQueue,
        // Mở mic armMs() sau khi LOA BẮT ĐẦU PHÁT câu đầu (onStart), không phải lúc gọi
        // speak() — TTS mất 0.4-2.7s mới ra tiếng nên đếm từ lúc gọi là khoá thiếu.
        onFirstStart: () => { tm('tts_first_sound'); listenLater(armMs()); },
        // Câu đầu tới: áp ui của mốc tool cuối (bản đồ/giá đổi cùng lúc với tiếng nói).
        onFirstSentence: (ui) => {
          tm('agent_first_sentence');
          const spoke = applyUi(ui);
          if (!spoke) release();
          return !spoke;           // đã đặt xe -> đọc câu cố định, bỏ lời agent (như cũ)
        },
        // Tool chạy SAU câu đầu (hiếm: LLM nói câu dẫn rồi mới gọi tool), kể cả khi lời
        // đáp đã bị ngắt: thao tác đã commit phải hiện ra và (đặt xe) phải được báo.
        onLateUi: (ui) => { if (ui && !(ui.booked && bookedApplied)) applyUi(ui); },
        onSentence: (s, first) => {
          if (first) { _streamText(s); shown = s; } else { _streamAppend(shown, s); shown = `${shown} ${s}`; }
        },
        // Lời đáp bị ngắt -> lịch sử = phần đã nghe (+ " …"), kết quả tool vẫn giữ.
        onInterrupted: (msgs) => {
          endMine('interrupted');
          messagesRef.current = msgs;
          dispatch({ type: 'SET_MESSAGES', payload: msgs });
        },
      });
      agentTurnRef.current = turn;

      const result = await turn.result;
      tm('agent_done', { agentStreamed: !!(result && result.streamed), agentLegacy: !!(result && result.legacy),
        agentResync: !!(result && result.resync), agentCut: !result });
      if (!result) { endMine('interrupted'); return; }   // bị ngắt giữa chừng: lịch sử chốt ở onInterrupted
      const { reply, messages: updatedMsgs, ui } = result;
      dispatch({ type: 'SET_BACKEND_ONLINE', payload: true });  // confirmed reachable

      if (!turn.isCut()) {
        if (updatedMsgs) { messagesRef.current = updatedMsgs; }
        dispatch({ type: 'SET_MESSAGES', payload: updatedMsgs || newMessages });
      }
      dispatch({ type: 'SET_STATUS', payload: { main: reply || 'Đã xử lý', sub: '' } });

      if (result.uiApplied) {
        if (turn.speech) afterSpeech(turn.speech);   // các câu đã/đang đọc qua hàng đợi
      } else {
        // Không có câu nào stream tới (đã lùi về /api/agent/chat): y như bản cũ, chỉ
        // khác là đọc qua hàng đợi để chen ngang không bị tính là "đọc xong".
        const spoke = applyUi(ui);
        if (reply && !spoke) {
          _streamText(reply);
          const q = createSpeechQueue({ onFirstStart: () => { tm('tts_first_sound'); listenLater(armMs()); } });
          q.push(reply);
          q.end();
          afterSpeech(q.drained);
        } else if (!bookedSpeech) endMine('ok');      // không có gì để đọc
      }
      if (bookedSpeech) { await bookedSpeech; tm('reply_spoken'); endMine('ok'); }   // như cũ: giữ khoá tới khi đọc xong câu đặt xe
    } catch (err) {
      console.error('Agent error -> local fallback:', err);
      endMine('error');
      dispatch({ type: 'SET_BACKEND_ONLINE', payload: false });
      _localFallback();
    } finally {
      release();
      // Lưới an toàn: bình thường mic được mở bởi onStart của câu đầu. Nhưng nếu TTS
      // hỏng hẳn (không có tiếng, onStart không bao giờ chạy) thì vẫn phải mở lại, không
      // thì cuộc hội thoại đứng luôn. Hẹn dài hơn để không tranh với onStart;
      // _autoListen tự bỏ qua nếu mic đã mở rồi.
      if (keepListening) listenLater(armMs() + 5000);
    }

    // Áp ui của lượt lên màn hình (luật cũ, nguyên văn). Trả true nếu đã tự đọc câu riêng
    // thay cho lời agent (đặt xe xong). Khai báo hàm (hoisted) nên dùng được ở trên.
    function applyUi(ui) {
      let spoke = false;
      const concrete = !!(ui && (ui.destination || ui.quote || ui.booked || ui.ended || ui.candidates));
      if (ui) {
        if (ui.candidates) {
          // Show the options ON THE MAP (numbered; accessible ones in green).
          dispatch({ type: 'SET_CANDIDATES', payload: ui.candidates });
          dispatch({ type: 'SET_DESTINATION', payload: null });
          dispatch({ type: 'SET_QUOTE', payload: null });
          dispatch({ type: 'SET_STATE', payload: 'destination_set' });
        }
        if (ui.destination) {
          dispatch({ type: 'SET_CANDIDATES', payload: null });   // a place was chosen
          dispatch({ type: 'SET_DESTINATION', payload: ui.destination });
          // New place => old quote/route belongs to the previous destination. Drop it
          // so the map never shows the old route while waiting for a fresh quote.
          // (If the agent re-quotes in the same turn, ui.quote below sets the new one.)
          dispatch({ type: 'SET_QUOTE', payload: null });
          dispatch({ type: 'SET_STATE', payload: 'destination_set' });
        }
        if (ui.quote) {
          dispatch({ type: 'SET_QUOTE', payload: ui.quote });
          dispatch({ type: 'SET_STATE', payload: 'confirming' });
        }
        if (ui.booked && !bookedApplied) {
          bookedApplied = true;
          // Hand off to the realtime driver search: show "Đang tìm tài xế" and
          // wait for a REAL driver (driver-arrived). Do NOT announce the agent's
          // auto-assigned driver here — that's what confusingly showed
          // "Tài xế Nguyễn Văn A" while no driver was online.
          keepListening = false;
          dispatch({ type: 'SET_BOOKING', payload: ui.booked });
          dispatch({ type: 'SET_DRIVER', payload: null });
          dispatch({ type: 'SET_PIN', payload: null });
          dispatch({ type: 'SET_STATE', payload: 'trip_live' });   // TripOverlay -> "Đang tìm tài xế…"
          _startRealtime(ui.booked);
          const m = 'Đã đặt xe. Đang tìm tài xế cho bạn, vui lòng chờ trong giây lát.';
          _streamText(m); bookedSpeech = speak(m);   // _send chờ promise này trước khi nhả khoá
          spoke = true;
        }
        if (ui.ended) {
          keepListening = false;           // user cancelled -> stop
          dispatch({ type: 'RESET_TRIP' });
        }
      }
      // No concrete place this turn (agent is asking / listing options / clarifying)
      // -> collapse the map + expand the agent. KEEP destination/quote data so the
      // ride screens (RideMoving) still have it after booking.
      if (!concrete) {
        dispatch({ type: 'SET_STATE', payload: 'listening' });
      }
      return spoke;
    }
  }, [dispatch, _autoListen, _localFallback, _streamText, _streamAppend]);
  sendRef.current = _send;

  // ---- Câu BẮT BUỘC phải nghe trọn (mã PIN) ----
  // Đọc qua hàng đợi câu (tts.createSpeechQueue) với mustHear: bị ngắt giữa chừng (người
  // dùng chen ngang, thông báo khoảng cách tài xế, lời đáp agent) thì các câu chưa nghe
  // trọn nằm trong result.unheard -> chờ tới lúc RẢNH (không ai đang nói, không xử lý
  // lượt nào, AI không đọc gì) rồi đọc lại, tối đa 3 lần. anyOf: các câu mustHear là
  // nhắc lại cùng một thông tin -> nghe trọn MỘT câu là đủ. Người khiếm thị không được
  // phép "lỡ" mã PIN chỉ vì một câu khác chen vào.
  const mustHearRef = useRef({ gen: 0, timer: null });
  const cancelMustHear = useCallback(() => {
    const m = mustHearRef.current;
    m.gen++;
    clearInterval(m.timer);
    m.timer = null;
  }, []);
  const sayMustHear = useCallback((items, { anyOf = false, tries = 0 } = {}) => {
    const m = mustHearRef.current;
    clearInterval(m.timer);
    m.timer = null;
    const gen = ++m.gen;
    const q = createSpeechQueue();
    items.forEach((it) => q.push(it.text, { mustHear: !!it.mustHear }));
    q.end();
    q.drained.then((r) => {
      if (gen !== m.gen || !r || !r.interrupted) return;
      const must = items.filter((it) => it.mustHear).map((it) => it.text);
      const heardOne = must.some((t) => (r.spoken || []).some((s) => s.includes(t)));
      const left = anyOf && heardOne ? [] : (r.unheard || []);
      if (!left.length) return;
      if (tries >= 3) { console.warn('[PIN] bi ngat qua 3 lan, thoi doc lai (cham man hinh de nghe lai)'); return; }
      console.log('[PIN] bi ngat truoc khi nghe tron -> cho ranh roi doc lai:', left);
      let quiet = 0;
      m.timer = setInterval(() => {
        if (gen !== m.gen) { clearInterval(m.timer); return; }
        const idle = !busyRef.current && !processingRef.current && !isSpeaking()
          && !(recordingRef.current && recorderRef.current?.heardSpeech);
        quiet = idle ? quiet + 1 : 0;
        if (quiet >= 2) {      // rảnh ~0.8s liền
          clearInterval(m.timer);
          m.timer = null;
          sayMustHear(left.map((text) => ({ text, mustHear: true })), { anyOf, tries: tries + 1 });
        }
      }, 400);
    });
  }, []);

  // ---- Booking overlay + realtime handoff ----
  const _showBooked = useCallback(async (booked, reply) => {
    dispatch({ type: 'SET_STATE', payload: 'booking' });
    if (reply) {
      const words = reply.split(' ');
      for (let i = 0; i < words.length; i++) {
        dispatch({ type: 'ADD_AGENT_LOG', payload: words.slice(0, i + 1).join(' ') });
        await new Promise(r => setTimeout(r, 50));
      }
    }
    _startRealtime(booked, reply);
  }, [dispatch]);

  const _startRealtime = useCallback(async (booked) => {
    // Join the driver-matching queue with the logged-in user's id. The realtime
    // server matches passengers by userId (same account as the login).
    const u = userRef.current || {};
    const userId = u.id || u._id || null;
    if (!userId) {
      console.warn('Realtime: no logged-in userId; skipping driver matching.');
      return;
    }
    arrivedRef.current = false;   // reset per-trip guard

    const socket = connectSocket({
      onDriverAccepted: (data) => {
        // Driver pressed "Nhận cuốc": confirm a driver is on the way + ETA (from
        // the route). PIN is NOT shown yet (only on arrival).
        const name = data.driverName || data.driver?.name || 'của bạn';
        const plate = data.licensePlate || data.driver?.plate || '';
        dispatch({ type: 'SET_STATE', payload: 'trip_live' });
        dispatch({ type: 'SET_DRIVER', payload: { name, plate } });
        dispatch({ type: 'SET_PIN', payload: null });
        if (navigator.vibrate) navigator.vibrate(150);
        const eta = booked?.etaMin || booked?.durationMin;
        const plateStr = plate.replace(/[^0-9A-Za-zĐđ]/g, '').split('').join(' ');
        speak(`Đã có tài xế nhận chuyến. Tài xế ${name}, biển số ${plateStr}.`
              + (eta ? ` Dự kiến đến điểm đón trong khoảng ${eta} phút.` : ''));
      },
      onDriverArrived: (data) => {
        if (arrivedRef.current) return;   // already announced PIN for this trip
        arrivedRef.current = true;
        const pin = String(data.pin || '');
        const name = data.driverName || data.driver?.name || 'của bạn';
        const plate = data.licensePlate || data.driver?.plate || '';
        dispatch({ type: 'SET_STATE', payload: 'trip_live' });
        dispatch({ type: 'SET_PIN', payload: pin });
        dispatch({ type: 'SET_DRIVER', payload: { name, plate } });
        if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
        // Turn the rider's phone into a locator BEACON (bright strobe + chirp +
        // buzz) so the sighted driver can find them. The rider stays put in a
        // safe spot — we never tell a blind rider to walk toward traffic.
        distBucketRef.current = null;
        startBeacon();
        const pinStr = pin.split('').join(' ');
        const plateStr = plate.replace(/[^0-9A-Za-zĐđ]/g, '').split('').join(' ');
        // Read the PIN TWICE on purpose (accessibility: visually-impaired riders
        // need to hear it clearly). The driver must still enter it correctly.
        // Câu PIN là mustHear: bị ngắt thì đọc lại khi rảnh (sayMustHear).
        const items = [{ text: `Tài xế đã đến gần. Tài xế ${name}, biển số ${plateStr}. Bạn cứ đứng yên ở chỗ an toàn, điện thoại đang phát tín hiệu để tài xế tìm thấy bạn.` }];
        if (pin) {
          items.push({ text: `Mã PIN của bạn là ${pinStr}.`, mustHear: true });
          items.push({ text: `Nhắc lại, mã PIN của bạn là ${pinStr}. Vui lòng đọc mã này cho tài xế để xác nhận.`, mustHear: true });
        }
        sayMustHear(items, { anyOf: true });
      },
      onDriverDistance: (data) => {
        const meters = Number(data?.meters);
        if (!Number.isFinite(meters)) return;
        setBeaconIntensity(meters);   // strobe/chirp faster as the driver nears
        // Reassurance only (never directional). Announce once per bucket so we
        // don't spam TTS on every GPS tick.
        const bucket = meters > 30 ? 'far' : meters > 12 ? 'near' : 'here';
        if (bucket !== distBucketRef.current) {
          distBucketRef.current = bucket;
          const msg = bucket === 'here'
            ? 'Tài xế đang ở ngay cạnh bạn. Cứ đứng yên, tài xế sẽ tới đón.'
            : bucket === 'near'
              ? `Tài xế còn cách bạn khoảng ${meters} mét, đang tới. Bạn đứng yên chỗ an toàn nhé.`
              : `Tài xế còn cách khoảng ${meters} mét.`;
          speak(msg);
        }
      },
      onPinVerified: () => {
        cancelMustHear();   // tài xế đã nhập đúng mã -> khỏi đọc lại PIN
        stopBeacon();
        dispatch({ type: 'SET_STATE', payload: 'in_progress' });   // -> RideMoving
        speak('Tài xế đã xác nhận đúng mã. Bạn đã lên xe an toàn. Xe đang khởi hành, chúc bạn đi đường bình an!');
      },
      onTripCompleted: () => {
        cancelMustHear();
        stopBeacon();
        dispatch({ type: 'SET_STATE', payload: 'completed' });      // -> RideArrived
        speak('Đã tới nơi, chuyến đi hoàn tất. Bạn có thể đánh giá mức độ tiếp cận của điểm đến để giúp cộng đồng.');
      },
    });
    socketRef.current = socket;
    // Tell the driver this is an accessibility ride (so they can assist).
    const DISAB = {
      visual_impairment: 'khiếm thị', wheelchair: 'dùng xe lăn',
      hearing_impairment: 'khiếm thính', elderly: 'người cao tuổi',
      temporary_injury: 'chấn thương tạm thời',
    };
    const dtype = userRef.current?.accessibility_profile?.disability_type;
    const accessibility = dtype
      ? `Hành khách ${DISAB[dtype] || 'cần hỗ trợ đặc biệt'} — vui lòng hỗ trợ lên/xuống xe`
      : '';
    const name = userRef.current?.full_name || 'Hành khách';
    const pk = pickupRef.current || {};
    // Send pickup GPS so the driver sees the distance to the (blind) rider.
    emitPassengerWaiting({ userId, accessibility, name, lat: pk.lat, lng: pk.lng });
  }, [dispatch, sayMustHear, cancelMustHear]);

  // ---- On mount: greet, then AUTO-OPEN the mic (no button needed) ----
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    let cancelled = false;
    (async () => {
      // Render free ngủ sau 15' -> lần gọi đầu có thể mất ~30-50s. Phải cho thấy
      // đang chạy chứ không để màn hình đứng im như bị treo.
      dispatch({ type: 'SET_BOOTING', payload: true });
      dispatch({ type: 'SET_STATUS', payload: {
        main: 'Đang kết nối máy chủ…', sub: 'Lần đầu có thể mất khoảng 30 giây' } });
      let online = false;
      let health = null;
      try { health = await api.checkHealth(); online = health?.status === 'ok'; } catch { online = false; }
      if (health?.stt_engine && !state.sttEnginePicked) {
        sttEngineRef.current = health.stt_engine;   // ngay: armMs() của lời chào đọc ref này
        dispatch({ type: 'SET_STT_ENGINE', payload: health.stt_engine });
      }
      if (health?.tts_engine && !state.ttsEnginePicked) {
        setTtsEngine(health.tts_engine);   // ngay, vì lời chào đọc trước khi effect kịp chạy
        dispatch({ type: 'SET_TTS_ENGINE', payload: health.tts_engine });
      }
      if (cancelled) return;
      dispatch({ type: 'SET_BOOTING', payload: false });
      dispatch({ type: 'SET_BACKEND_ONLINE', payload: online });
      const greet = 'Xin chào, tôi là trợ lý đặt xe, bạn muốn đến đâu?';
      dispatch({ type: 'SET_STATUS', payload: { main: 'Xin chào! Bạn muốn đến đâu?', sub: 'Hãy nói điểm đến của bạn' } });
      _streamText(greet);
      // Lời chào cũng là một câu AI đọc -> áp cùng luật: chỉ mở mic 4s sau khi LOA
      // bắt đầu phát, để tiếng ồn không cắt ngay câu chào. Kèm lưới an toàn nếu TTS
      // hỏng (không có tiếng thì onStart không chạy).
      speak(greet, {
        onStart: () => { if (!cancelled) _autoListen(armMs()); },
      }).then(() => { if (!cancelled) _autoListen(150); })   // P1: chào xong là nghe ngay
        .catch(console.error);
      if (cancelled) return;
      _autoListen(armMs() + 5000);
    })();
    return () => { cancelled = true; };
  }, [dispatch]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { cancelMustHear(); disconnectSocket(); stopSpeech(); stopBeacon(); liveRef.current?.close(); };
  }, [cancelMustHear]);

  // Re-read the current PIN aloud on demand. Blind riders just TAP the screen
  // (no button to find) — used while the driver-arrived PIN is showing.
  const repeatPin = useCallback(() => {
    const pin = state.pin;
    if (!pin) return;
    const pinStr = String(pin).split('').join(' ');
    const name = state.driver?.name || 'của bạn';
    const plate = (state.driver?.plate || '').replace(/[^0-9A-Za-zĐđ]/g, '').split('').join(' ');
    stopSpeech();
    speak(`Mã PIN của bạn là ${pinStr}. Tài xế ${name}${plate ? `, biển số ${plate}` : ''}. Vui lòng đọc mã này cho tài xế để xác nhận.`);
  }, [state.pin, state.driver]);

  return {
    state,
    startListening,
    stopListening,
    toggleListening,
    repeatPin,
    resetTrip: useCallback(() => { cancelMustHear(); stopBeacon(); disconnectSocket(); dispatch({ type: 'RESET_TRIP' }); }, [dispatch, cancelMustHear]),
  };
}

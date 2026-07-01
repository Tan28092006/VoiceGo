import { useCallback, useEffect, useRef } from 'react';
import { useApp } from '../context/AppContext';
import * as api from '../services/api';
import { speak, stop as stopSpeech, unlockAudio } from '../services/tts';
import VoiceRecorder from '../services/voiceRecorder';
import { connectSocket, emitPassengerWaiting, disconnectSocket } from '../services/socket';

// STT engine. TẠM THỜI mặc định FPT.AI (để test trên điện thoại); mở với
// ?stt=whisper để quay lại Groq Whisper. (Backend: fpt -> FPT trước, Groq fallback.)
const STT_ENGINE = new URLSearchParams(window.location.search).get('stt') || 'fpt';

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

  // Latest-value refs so the hands-free loop callbacks can call each other
  // without stale closures.
  const startListeningRef = useRef(() => {});
  const sendRef = useRef(() => {});

  useEffect(() => { recordingRef.current = state.recording; }, [state.recording]);
  useEffect(() => { messagesRef.current = state.messages; }, [state.messages]);
  useEffect(() => { userRef.current = state.user; }, [state.user]);

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
  const _autoListen = useCallback(() => {
    setTimeout(() => {
      // Don't reopen if busy, already listening, OR the user manually paused.
      if (busyRef.current || recordingRef.current || pausedRef.current) return;
      startListeningRef.current();
    }, 450);
  }, []);

  // ---- Speech-to-text (browser Web Speech, primary) ----
  const _listenBrowser = useCallback((SR) => {
    const recognition = new SR();
    recognition.lang = 'vi-VN';
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    let finalText = '';
    let silenceTimer = null;

    recognition.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      dispatch({ type: 'SET_TRANSCRIPT', payload: (finalText + interim).trim() });
      clearTimeout(silenceTimer);
      if (finalText) {
        try { recognition.stop(); } catch {}
      } else {
        silenceTimer = setTimeout(() => { try { recognition.stop(); } catch {} }, 2500);
      }
    };

    recognition.onerror = (e) => {
      console.warn('Speech recognition error:', e.error);
      recordingRef.current = false;
      dispatch({ type: 'SET_RECORDING', payload: false });
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        dispatch({ type: 'SET_STATUS', payload: { main: 'Cần quyền micro', sub: 'Cho phép micro rồi chạm màn hình để nói' } });
      }
    };

    recognition.onend = () => {
      recordingRef.current = false;
      dispatch({ type: 'SET_RECORDING', payload: false });
      const text = finalText.trim();
      if (text) {
        emptyRef.current = 0;
        sendRef.current(text);
      } else {
        // Heard nothing — keep listening hands-free, but cap retries so the mic
        // doesn't stay on forever in silence.
        emptyRef.current += 1;
        if (emptyRef.current <= 3) {
          _autoListen();
        } else {
          emptyRef.current = 0;
          dispatch({ type: 'SET_STATUS', payload: { main: 'Mình chưa nghe rõ', sub: 'Chạm vào màn hình để nói lại' } });
        }
      }
    };

    recorderRef.current = recognition;
    try {
      recognition.start();
    } catch (err) {
      console.warn('Speech recognition start failed:', err);
      recordingRef.current = false;
      dispatch({ type: 'SET_RECORDING', payload: false });
    }
  }, [dispatch, _autoListen]);

  // ---- Speech-to-text (Whisper via backend, fallback) ----
  const _listenWhisper = useCallback(async () => {
    if (!recorderRef.current || typeof recorderRef.current.start !== 'function') {
      recorderRef.current = new VoiceRecorder();
    }
    const recorder = recorderRef.current;
    try {
      await recorder.start({
        silenceMs: 950,          // cut off a bit sooner -> lower latency
        noSpeechMs: 7000,
        onAutoStop: async () => {
          const wavBlob = await recorder.stop();
          recordingRef.current = false;
          dispatch({ type: 'SET_RECORDING', payload: false });
          if (wavBlob && wavBlob.size > 1000) {
            dispatch({ type: 'SET_STATUS', payload: { main: 'Đang nhận diện giọng nói…', sub: '' } });
            try {
              const text = await api.speechToText(wavBlob, 'speech.wav', STT_ENGINE);
              if (text) { emptyRef.current = 0; dispatch({ type: 'SET_TRANSCRIPT', payload: text }); sendRef.current(text); }
              else { _autoListen(); }
            } catch { dispatch({ type: 'SET_STATUS', payload: { main: 'Lỗi nhận diện', sub: 'Chạm màn hình để thử lại' } }); }
          } else { _autoListen(); }
        },
      });
    } catch (err) {
      console.warn('Recorder start failed:', err);
      recordingRef.current = false;
      dispatch({ type: 'SET_RECORDING', payload: false });
      dispatch({ type: 'SET_STATUS', payload: { main: 'Không bật được micro', sub: 'Cho phép micro rồi chạm màn hình' } });
    }
  }, [dispatch, _autoListen]);

  // ---- Start / stop listening ----
  const startListening = useCallback(() => {
    if (busyRef.current || recordingRef.current) return;
    recordingRef.current = true;
    dispatch({ type: 'SET_RECORDING', payload: true });
    dispatch({ type: 'SET_STATUS', payload: { main: '🎙️ Đang nghe…', sub: 'Nói điểm đến của bạn' } });
    dispatch({ type: 'SET_TRANSCRIPT', payload: '' });
    stopSpeech();
    // Always use Groq Whisper (record -> backend STT) on every device for
    // consistent, accurate Vietnamese recognition.
    _listenWhisper();
  }, [dispatch, _listenWhisper]);
  startListeningRef.current = startListening;

  const stopListening = useCallback(() => {
    const r = recorderRef.current;
    if (r) { try { r.stop(); } catch {} }
    recordingRef.current = false;
    dispatch({ type: 'SET_RECORDING', payload: false });
  }, [dispatch]);

  // Tap anywhere (gesture zone / mic button) to start or stop — fallback to the
  // hands-free flow (e.g. if the browser blocked auto-start without a gesture).
  const toggleListening = useCallback(() => {
    unlockAudio();   // keep mobile audio unlocked on every tap
    if (recordingRef.current) {
      // Manual OFF -> stay off (suppress the hands-free auto-reopen).
      pausedRef.current = true;
      stopListening();
      dispatch({ type: 'SET_STATUS', payload: { main: 'Đã tắt micro', sub: 'Chạm nút để nói tiếp' } });
      return;
    }
    if (busyRef.current) { pausedRef.current = true; return; }
    // Manual ON -> resume the SAME conversation (memory intact).
    pausedRef.current = false;
    emptyRef.current = 0;
    startListening();
  }, [startListening, stopListening, dispatch]);

  // ---- Send a turn to the agent (or local fallback) ----
  const _send = useCallback(async (text) => {
    if (!text || busyRef.current) return;
    busyRef.current = true;
    dispatch({ type: 'SET_BUSY', payload: true });
    dispatch({ type: 'SET_STATUS', payload: { main: '🤖 Đang xử lý…', sub: text } });

    let keepListening = true;
    try {
      // ALWAYS send to the LLM agent. (Don't gate on a one-shot health check —
      // a single transient failure must not silently downgrade to the tiny local
      // place matcher, which returns wrong places like "Tôn Đức Thắng".)
      const newMessages = [...messagesRef.current, { role: 'user', content: text }];
      messagesRef.current = newMessages;
      dispatch({ type: 'SET_MESSAGES', payload: newMessages });

      const result = await api.agentChat(newMessages);
      const { reply, messages: updatedMsgs, ui } = result;
      dispatch({ type: 'SET_BACKEND_ONLINE', payload: true });  // confirmed reachable

      if (updatedMsgs) { messagesRef.current = updatedMsgs; }
      dispatch({ type: 'SET_MESSAGES', payload: updatedMsgs || newMessages });
      dispatch({ type: 'SET_STATUS', payload: { main: reply || 'Đã xử lý', sub: '' } });

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
        if (ui.booked) {
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
          _streamText(m); await speak(m);
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

      if (reply && !spoke) { _streamText(reply); await speak(reply); }
    } catch (err) {
      console.error('Agent error -> local fallback:', err);
      dispatch({ type: 'SET_BACKEND_ONLINE', payload: false });
      _localFallback(text);
    } finally {
      busyRef.current = false;
      dispatch({ type: 'SET_BUSY', payload: false });
      if (keepListening) _autoListen();      // hands-free: keep the conversation going
    }
  }, [dispatch, _autoListen]);
  sendRef.current = _send;

  // ---- Connection fallback ----
  // The LLM agent is the ONLY source of destinations. If it's unreachable we do
  // NOT guess a place locally (that produced wrong places like "Điện Biên Phủ" +
  // NaN price) — we just ask the user to retry.
  const _localFallback = useCallback(() => {
    const msg = 'Xin lỗi, mình chưa kết nối được máy chủ. Bạn thử nói lại sau giây lát nhé.';
    dispatch({ type: 'SET_STATUS', payload: { main: 'Chưa kết nối được trợ lý', sub: 'Kiểm tra mạng rồi thử lại' } });
    _streamText(msg);
    speak(msg);
  }, [dispatch]);

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
        const pinStr = pin.split('').join(' ');
        const plateStr = plate.replace(/[^0-9A-Za-zĐđ]/g, '').split('').join(' ');
        // Read the PIN TWICE on purpose (accessibility: visually-impaired riders
        // need to hear it clearly). The driver must still enter it correctly.
        speak(`Tài xế đã đến nơi đón. Tài xế ${name}, biển số ${plateStr}.`)
          .then(() => pin && speak(`Mã PIN của bạn là ${pinStr}.`))
          .then(() => pin && speak(`Nhắc lại, mã PIN của bạn là ${pinStr}. Vui lòng đọc mã này cho tài xế để xác nhận.`));
      },
      onPinVerified: () => {
        dispatch({ type: 'SET_STATE', payload: 'in_progress' });   // -> RideMoving
        speak('Tài xế đã xác nhận đúng mã. Bạn đã lên xe an toàn. Xe đang khởi hành, chúc bạn đi đường bình an!');
      },
      onTripCompleted: () => {
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
    emitPassengerWaiting({ userId, accessibility, name });   // server matches by userId
  }, [dispatch]);

  // ---- On mount: greet, then AUTO-OPEN the mic (no button needed) ----
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    let cancelled = false;
    (async () => {
      let online = false;
      try { online = (await api.checkHealth())?.status === 'ok'; } catch { online = false; }
      if (cancelled) return;
      dispatch({ type: 'SET_BACKEND_ONLINE', payload: online });
      const greet = 'Xin chào, tôi là trợ lý đặt xe, bạn muốn đến đâu?';
      dispatch({ type: 'SET_STATUS', payload: { main: 'Xin chào! Bạn muốn đến đâu?', sub: 'Hãy nói điểm đến của bạn' } });
      _streamText(greet);
      await speak(greet);
      if (cancelled) return;
      // The login click was the user gesture; start listening right after.
      startListeningRef.current();
    })();
    return () => { cancelled = true; };
  }, [dispatch]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { disconnectSocket(); stopSpeech(); };
  }, []);

  return {
    state,
    startListening,
    stopListening,
    toggleListening,
    resetTrip: useCallback(() => { disconnectSocket(); dispatch({ type: 'RESET_TRIP' }); }, [dispatch]),
  };
}

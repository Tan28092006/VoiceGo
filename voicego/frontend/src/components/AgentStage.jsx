import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../context/AppContext';
import '../styles/components/AgentStage.css';

/**
 * AgentStage — the always-visible AI agent panel. Streams the agent's reply
 * word-by-word (judges see the LLM "typing"). It's LARGE when no destination is
 * set, and shrinks to a small strip (still streaming) when the map takes over.
 */
export default function AgentStage({ compact }) {
  const { state } = useApp();
  const bodyRef = useRef(null);
  // Lượt của NGƯỜI DÙNG (đang nói / đang xử lý câu vừa nói): lời của họ lên màn giữa,
  // chữ to, thay cho câu cũ của AI. Lời AI mới tới (SET_STREAM) thì AI lại chiếm màn.
  const userTurn = state.stage === 'user' && !!state.transcript;
  const said = useTypedWords(userTurn ? state.transcript : '');

  // Keep the latest streamed text in view when compact (scrolls).
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [state.agentStream, said]);

  const text = userTurn ? said : (state.agentStream || state.status || '');

  return (
    <section className={`agent-stage ${compact ? 'compact' : ''}`} aria-label="Trợ lý giọng nói">
      <div className="agent-stage-head">
        <span className={`agent-orb ${state.busy ? 'thinking' : ''}`} aria-hidden="true" />
        <span className="agent-stage-title">AI Agent</span>
        {state.recording && <span className="agent-rec" aria-hidden="true">● đang nghe</span>}
      </div>

      <div className="agent-stage-body" ref={bodyRef} role="status" aria-live={userTurn ? 'off' : 'polite'}>
        {state.booting && <span className="agent-boot-spinner" aria-hidden="true" />}
        <p className={`agent-stage-text ${userTurn ? 'user' : ''}`}>{text}<span className="caret" /></p>
        {state.booting && state.substatus && (
          <p className="agent-boot-sub">{state.substatus}</p>
        )}
      </div>

      {state.transcript && !userTurn && (
        <div className="agent-stage-transcript" aria-hidden="true">“{state.transcript}…”</div>
      )}
    </section>
  );
}

/**
 * Hiện chữ dần từng từ (45ms/từ, cùng nhịp với _streamText của lời AI) đuổi theo
 * `target`. Gemini Live trả bản tạm cứ ~0.5s một lần, mỗi lần thêm 2-3 từ -> gõ dần
 * thì nhìn liền mạch như AI đang gõ, thay vì nhảy từng cục. Gemini sửa chữ cũ (vd
 * bỏ dấu chấm khi người dùng nói tiếp) -> lùi về phần chung rồi gõ tiếp từ đó.
 */
function useTypedWords(target) {
  const [shown, setShown] = useState('');
  const shownRef = useRef('');
  useEffect(() => {
    const want = String(target || '').split(/\s+/).filter(Boolean);
    let cur = shownRef.current ? shownRef.current.split(' ') : [];
    let i = 0;
    while (i < cur.length && i < want.length && cur[i] === want[i]) i++;
    cur = want.slice(0, i);
    const show = () => { shownRef.current = cur.join(' '); setShown(shownRef.current); };
    show();
    const t = setInterval(() => {
      if (cur.length >= want.length) { clearInterval(t); return; }
      cur.push(want[cur.length]);
      show();
    }, 45);
    return () => clearInterval(t);
  }, [target]);
  return shown;
}

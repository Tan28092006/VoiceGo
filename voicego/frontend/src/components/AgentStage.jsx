import React, { useEffect, useRef } from 'react';
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

  // Keep the latest streamed text in view when compact (scrolls).
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [state.agentStream]);

  const text = state.agentStream || state.status || '';

  return (
    <section className={`agent-stage ${compact ? 'compact' : ''}`} aria-label="Trợ lý giọng nói">
      <div className="agent-stage-head">
        <span className={`agent-orb ${state.busy ? 'thinking' : ''}`} aria-hidden="true" />
        <span className="agent-stage-title">AI Agent</span>
        {state.recording && <span className="agent-rec" aria-hidden="true">● đang nghe</span>}
      </div>

      <div className="agent-stage-body" ref={bodyRef} role="status" aria-live="polite">
        <p className="agent-stage-text">{text}<span className="caret" /></p>
      </div>

      {state.transcript && (
        <div className="agent-stage-transcript" aria-hidden="true">“{state.transcript}…”</div>
      )}
    </section>
  );
}

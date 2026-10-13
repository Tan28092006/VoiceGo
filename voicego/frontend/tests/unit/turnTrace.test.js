// Regression (Agent A, task A3): turnTrace emits exactly ONE `[turn] {json}` line per
// turn with stage marks relative to the turn start and derived spans
// (endpoint->text, endpoint->liveFinal, Whisper ms, barge pause->confirm/false-alarm).
// A new startTurn() flushes an open turn as 'next-turn'; an abandoned turn is flushed
// as 'idle-flush' after 30s without marks.
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';

let clock = 0;
let tt;
let logs = [];
beforeAll(async () => {
  vi.stubGlobal('performance', { now: () => clock });
  vi.resetModules();
  tt = await import('../../src/services/turnTrace.js');
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
afterAll(() => { vi.unstubAllGlobals(); });
const spyLog = () => {
  logs = [];
  vi.spyOn(console, 'log').mockImplementation((...a) => { logs.push(a.join(' ')); });
};
const turnLines = () => logs.filter((l) => l.startsWith('[turn] '));
const parse = (l) => JSON.parse(l.slice('[turn] '.length));

describe('turnTrace', () => {
  it('one line per turn with relative marks, fields and derived spans', () => {
    spyLog();
    clock = 1000;
    const id = tt.startTurn({ engine: 'gemini-live', duringTts: true });
    expect(tt.currentTurnId()).toBe(id);
    clock = 1000; tt.mark('speech');
    clock = 1010; tt.mark('bargePause');
    clock = 1800; tt.mark('bargeConfirm', { barge: 'confirmed' });
    clock = 2500; tt.mark('endpoint');
    clock = 2900; tt.mark('liveFinal', { finishReason: 'done' });
    clock = 2905; tt.mark('text', { textLen: 12 });
    clock = 9999; tt.mark('text');                       // only the FIRST mark of a name counts
    expect(turnLines()).toHaveLength(0);                 // nothing printed before endTurn
    const rec = tt.endTurn('replied');
    expect(turnLines()).toHaveLength(1);
    const j = parse(turnLines()[0]);
    expect(j).toEqual(rec);
    expect(j).toMatchObject({
      id, outcome: 'replied', engine: 'gemini-live', duringTts: true, barge: 'confirmed',
      finishReason: 'done', textLen: 12,
      endpointToTextMs: 405, liveFinalMs: 400, bargeConfirmMs: 790,
      t: { speech: 0, bargePause: 10, bargeConfirm: 800, endpoint: 1500, liveFinal: 1900, text: 1905 },
    });
    expect(j).not.toHaveProperty('whisperMs');          // spans without both marks are omitted
    expect(tt.currentTurnId()).toBe(null);
    expect(tt.endTurn('again')).toBe(null);             // no double line
    expect(turnLines()).toHaveLength(1);
  });

  it('mark() without an open turn is ignored; startTurn() flushes an open turn as next-turn', () => {
    spyLog();
    tt.mark('endpoint');
    expect(turnLines()).toHaveLength(0);
    clock = 0;
    tt.startTurn({ engine: 'whisper' });
    tt.mark('whisperStart');
    clock = 2300; tt.mark('whisperEnd');
    tt.startTurn({ engine: 'whisper' });
    expect(turnLines()).toHaveLength(1);
    expect(parse(turnLines()[0])).toMatchObject({ outcome: 'next-turn', whisperMs: 2300 });
    tt.endTurn('empty');
    expect(turnLines()).toHaveLength(2);
  });

  it('an abandoned turn is flushed once after 30s idle', () => {
    vi.useFakeTimers();
    spyLog();
    tt.startTurn({});
    vi.advanceTimersByTime(29000);
    tt.mark('text');                      // a mark re-arms the idle flush
    vi.advanceTimersByTime(29000);
    expect(turnLines()).toHaveLength(0);
    vi.advanceTimersByTime(1500);
    expect(turnLines()).toHaveLength(1);
    expect(parse(turnLines()[0]).outcome).toBe('idle-flush');
  });
});

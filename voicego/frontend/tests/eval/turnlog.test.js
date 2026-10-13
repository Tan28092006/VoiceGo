// Kiểm parser log `[turn]` (voicego/eval/turnlog_report.mjs) trên một mẫu TỰ VIẾT:
// lấy đúng JSON sau "[turn] " kể cả có tiền tố DevTools, đếm dòng hỏng, bỏ dòng trùng,
// chịu được trường lạ, tính phân phối theo chặng và tỉ lệ theo trường phân loại.
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect } from 'vitest';
import { EVAL_DIR } from './_lib.js';
import { parseTurnLog, summarize } from '../../../eval/turnlog_report.mjs';

describe('turnlog_report — parser', () => {
  const text = fs.readFileSync(path.join(EVAL_DIR, 'datasets', 'turnlog_sample.log'), 'utf8');
  it('tách bản ghi, đếm hỏng/trùng, tổng hợp', () => {
    const { records, bad, duplicates } = parseTurnLog(text);
    expect(records.length).toBe(5);
    expect(bad).toBe(1);
    expect(duplicates).toBe(1);
    const s = summarize(records);
    expect(s.timings.endpointToTextMs.n).toBe(4);
    expect(s.timings.endpointToTextMs.missing).toBe(1);
    expect(s.timings['t.endpoint'].p50).toBe(2000);
    expect(s.categories.finishReason.timeout.count).toBe(1);
    expect(s.categories.newField.x.count).toBe(1);        // trường lạ vẫn được đếm
    expect(s.timings.endpointToTextMs.p99Reliable).toBe(false);
  });
});

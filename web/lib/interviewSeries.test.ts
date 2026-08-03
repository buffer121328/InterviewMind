import assert from 'node:assert/strict';
import test from 'node:test';

import { groupInterviewSeries, isInterviewFinished } from './interviewSeries.ts';

const base = {
  title: '模拟面试',
  created_at: '2026-08-03T08:00:00',
  updated_at: '2026-08-03T08:00:00',
  mode: 'mock' as const,
  status: 'completed' as const,
  message_count: 4,
  question_count: 2,
  max_questions: 2,
  company_info: '示例公司',
};

test('groups linked rounds into one company series and keeps independent sessions separate', () => {
  const groups = groupInterviewSeries([
    { ...base, session_id: 'r2', series_id: 'series-1', parent_session_id: 'r1', round_index: 2 },
    { ...base, session_id: 'r1', series_id: 'series-1', round_index: 1 },
    { ...base, session_id: 'independent', round_index: 1 },
  ]);

  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].rounds.map((item) => item.session_id), ['r1', 'r2']);
  assert.equal(groups[1].rounds[0].session_id, 'independent');
});

test('completed status or exhausted question limit closes the interview', () => {
  assert.equal(isInterviewFinished('completed', 1, 20), true);
  assert.equal(isInterviewFinished('active', 20, 20), true);
  assert.equal(isInterviewFinished('active', 19, 20), false);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { formatResumeWorkspaceTitle } from './resumeHistoryTitle.ts';

test('resume workspace history title contains local minute precision and stable task label', () => {
    const title = formatResumeWorkspaceTitle('2026-07-28T14:05:00');

    assert.equal(title, '2026-07-28 14:05 —— 简历优化');
});

test('resume workspace history title falls back safely for invalid timestamps', () => {
    assert.equal(formatResumeWorkspaceTitle('not-a-date'), '简历优化');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { BOSS_EXPERIENCE_OPTIONS, BOSS_JOB_TYPE_LABEL, BOSS_NO_EXPERIENCE_NOTICE } from './bossCaptureFilters.ts';

test('exposes only the requested BOSS experience filters and full-time job type', () => {
    assert.deepEqual(BOSS_EXPERIENCE_OPTIONS, [
        { value: 'any', label: '不限' },
        { value: 'no_experience', label: '无经验' },
        { value: 'experience_unlimited', label: '经验不限' },
        { value: 'one_to_three', label: '1–3 年' },
    ]);
    assert.equal(BOSS_JOB_TYPE_LABEL, '全职');
    assert.match(BOSS_NO_EXPERIENCE_NOTICE, /完整 JD/);
});

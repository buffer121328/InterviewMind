import assert from 'node:assert/strict';
import test from 'node:test';

import { summarizeCompanySeriesProfile } from './companySeriesProfile.ts';

test('summarizes a persisted three-round company profile without confusing it with a single-round profile', () => {
    assert.deepEqual(summarizeCompanySeriesProfile({
        source_session_ids: ['round-1', 'round-2', 'round-3'],
        profile: {
            overall_assessment: '跨轮表现稳定。',
            key_strengths: ['Agent 方案设计'],
            key_weaknesses: ['评测闭环'],
        },
    }), {
        sourceRoundCount: 3,
        overallAssessment: '跨轮表现稳定。',
        strengths: ['Agent 方案设计'],
        weaknesses: ['评测闭环'],
    });
    assert.equal(summarizeCompanySeriesProfile({ overall_assessment: '单轮画像' }), null);
});

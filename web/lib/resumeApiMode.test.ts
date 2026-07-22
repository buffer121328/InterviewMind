import assert from 'node:assert/strict';
import test from 'node:test';

import { buildResumeOptimizePayload } from './api/resumePayloads.ts';

const apiConfig = {
    smart: { api_key: 'k', base_url: 'https://example.test', model: 'smart' },
    fast: { api_key: 'k', base_url: 'https://example.test', model: 'fast' },
};

test('buildResumeOptimizePayload preserves selected optimization mode', () => {
    const payload = buildResumeOptimizePayload({
        resume_content: 'resume',
        job_description: 'jd',
        include_overall_profile: true,
        mode: 'quality',
        api_config: apiConfig,
    });

    assert.equal(payload.mode, 'quality');
    assert.equal(payload.include_overall_profile, true);
});

test('buildResumeOptimizePayload defaults optimization mode to balanced', () => {
    const payload = buildResumeOptimizePayload({
        resume_content: 'resume',
        job_description: 'jd',
        api_config: apiConfig,
    });

    assert.equal(payload.mode, 'balanced');
    assert.deepEqual(payload.session_ids, []);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    buildAdvancedEvaluationRunRequest,
    MISSING_EVALUATION_MODEL_CONFIG_MESSAGE,
} from './evaluationRunRequest.ts';

const baseInput = {
    suiteId: 'suite-1',
    agentVersion: 'production',
    promptName: 'interview.planner',
    promptVersion: '3',
    baselineRunId: null,
    modelConfigHash: 'sha256:configured',
    repetitionCount: 2,
    maxConcurrency: 3,
    maxBudgetUsd: 5,
    caseIds: ['case-1'],
    includeJudges: true,
    humanReviewRate: 0.1,
};

test('advanced evaluation request carries the request-scoped governed model configuration', () => {
    const apiConfig = {
        smart: { credential_id: 'credential-smart', base_url: 'https://smart.example', model: 'smart' },
        fast: { credential_id: 'credential-fast', base_url: 'https://fast.example', model: 'fast' },
    };

    const payload = buildAdvancedEvaluationRunRequest({ ...baseInput, apiConfig });

    assert.equal(payload.include_judges, true);
    assert.equal(payload.api_config, apiConfig);
    assert.deepEqual(payload.case_ids, ['case-1']);
});

test('advanced evaluation request refuses to send an empty model configuration', () => {
    assert.throws(
        () => buildAdvancedEvaluationRunRequest({ ...baseInput, apiConfig: null }),
        { message: MISSING_EVALUATION_MODEL_CONFIG_MESSAGE },
    );
    assert.throws(
        () => buildAdvancedEvaluationRunRequest({ ...baseInput, apiConfig: {} }),
        { message: MISSING_EVALUATION_MODEL_CONFIG_MESSAGE },
    );
});

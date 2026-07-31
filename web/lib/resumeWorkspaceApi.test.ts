import test from 'node:test';
import assert from 'node:assert/strict';
import { isResumeWorkspaceResult, safeWorkspaceErrorMessage } from './resumeWorkspaceResult.ts';

const validWorkspaceResult = {
    success: true,
    competition_analysis: {},
    jd_matching: {},
    content_optimization: {},
    result_id: 42,
    review: { status: 'not_required', version: 1, items: [] },
    warnings: [],
};

test('accepts the backend terminal workspace result contract', () => {
    assert.equal(isResumeWorkspaceResult(validWorkspaceResult), true);
});

test('rejects succeeded workspace results missing review or required fields', () => {
    const { review: _review, ...incompleteResult } = validWorkspaceResult;
    assert.equal(_review.status, 'not_required');
    assert.equal(isResumeWorkspaceResult(incompleteResult), false);
    assert.equal(isResumeWorkspaceResult({ ...validWorkspaceResult, content_optimization: null }), false);
});

test('uses a safe bounded message for workspace failures', () => {
    assert.equal(safeWorkspaceErrorMessage({ error_message: { internal: 'details' } }, '任务未完成'), '任务未完成');
    assert.equal(safeWorkspaceErrorMessage({ error_message: '  failure\nreason  ' }, '任务未完成'), 'failure reason');
    assert.equal(safeWorkspaceErrorMessage({ error_message: 'x'.repeat(400) }, '任务未完成').length, 300);
});

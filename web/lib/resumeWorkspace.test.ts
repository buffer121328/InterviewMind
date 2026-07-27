import test from 'node:test';
import assert from 'node:assert/strict';
import { getResumeWorkspaceStage } from './resumeWorkspaceHelpers.ts';

test('maps unified resume stages to stable workspace states', () => {
    assert.equal(getResumeWorkspaceStage('competition_analysis'), 'competition_analysis');
    assert.equal(getResumeWorkspaceStage('jd_matching'), 'jd_matching');
    assert.equal(getResumeWorkspaceStage('content_optimization'), 'content_optimization');
    assert.equal(getResumeWorkspaceStage('saving_result'), 'saving_result');
    assert.equal(getResumeWorkspaceStage('retrying'), 'queued');
    assert.equal(getResumeWorkspaceStage('unknown'), 'complete');
});

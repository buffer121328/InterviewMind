import assert from 'node:assert/strict';
import test from 'node:test';

import type { EvaluationRun } from './api/evaluations.ts';
import {
    evaluationBatchStatus,
    evaluationRunModeLabel,
    recentEvaluationResultItems,
    recentEvaluationResultPage,
} from './recentEvaluationResults.ts';

function run(id: string, overrides: Partial<EvaluationRun> = {}): EvaluationRun {
    return {
        id,
        suite_id: 'suite',
        agent_run_id: null,
        smoke_batch_id: null,
        agent_name: 'interview_planner',
        agent_version: '1',
        prompt_name: null,
        prompt_version: null,
        model_config_hash: 'sha256:test',
        dataset_version: 'builtin.interview-planner:v1',
        status: 'succeeded',
        baseline_run_id: null,
        repetition_count: 1,
        include_judges: false,
        budget: {},
        summary: {},
        created_at: '2026-08-22T00:00:00Z',
        started_at: null,
        finished_at: null,
        ...overrides,
    };
}

test('recent results group one-click batches once and keep the selected Agent runs', () => {
    const items = recentEvaluationResultItems([
        run('batch-a', { smoke_batch_id: 'smoke-1' }),
        run('batch-b', { smoke_batch_id: 'smoke-1', agent_name: 'resume_analyzer' }),
        run('selected'),
        run('other', { agent_name: 'resume_analyzer' }),
    ], 'interview_planner');

    assert.equal(items.length, 2);
    assert.deepEqual(items.map(item => item.kind), ['batch', 'run']);
    assert.equal(items[0]?.kind === 'batch' ? items[0].runs.length : 0, 2);
});

test('recent results retain ten top-level items and expose the second five-item page', () => {
    const items = recentEvaluationResultItems(
        Array.from({ length: 12 }, (_, index) => run(`run-${index}`)),
        'interview_planner',
    );

    assert.equal(items.length, 10);
    assert.equal(recentEvaluationResultPage(items, 1).length, 5);
    assert.deepEqual(recentEvaluationResultPage(items, 2).map(item => item.id), [
        'run-5', 'run-6', 'run-7', 'run-8', 'run-9',
    ]);
});

test('evaluation result labels classify persisted and legacy quick-evaluation scopes', () => {
    assert.equal(evaluationRunModeLabel(run('quick', { budget: { mode: 'quick' } })), '快速冒烟');
    assert.equal(evaluationRunModeLabel(run('standard', { dataset_version: 'builtin.agent.standard:v1' })), '标准回归');
    assert.equal(evaluationRunModeLabel(run('release', { dataset_version: 'builtin.agent.release:v1' })), '发布检查');
    assert.equal(evaluationRunModeLabel(run('batch', { smoke_batch_id: 'smoke-1' })), '快速冒烟');
});

test('batch status keeps an active run visible until every child reaches a terminal state', () => {
    assert.equal(evaluationBatchStatus([run('done'), run('queued', { status: 'queued' })]), 'running');
    assert.equal(evaluationBatchStatus([run('done'), run('failed', { status: 'failed' })]), 'failed');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    evaluationReviewReasonLabel,
    paginateEvaluationScores,
    summarizeEvaluationOutput,
    summarizeEvaluationScores,
} from './evaluationCaseDetail.ts';

test('case detail groups deterministic rules into an easy-to-scan summary', () => {
    const summaries = summarizeEvaluationScores([
        { id: '1', case_run_id: 'run', metric_name: 'schema', value: 1, status: 'passed', source: 'deterministic', reason: null, severity: 'high', hard_gate: true, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        { id: '2', case_run_id: 'run', metric_name: 'approval', value: 0, status: 'failed', source: 'deterministic', reason: 'missing approval', severity: 'high', hard_gate: true, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        { id: '3', case_run_id: 'run', metric_name: 'semantic', value: null, status: 'pending', source: 'judge', reason: null, severity: 'medium', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
    ]);

    assert.deepEqual(
        summaries.map(({ source, label, passed, failed, review, hardGateFailures }) => ({ source, label, passed, failed, review, hardGateFailures })),
        [
            { source: 'deterministic', label: '确定性规则', passed: 1, failed: 1, review: 0, hardGateFailures: 1 },
            { source: 'judge', label: 'LLM Judge', passed: 0, failed: 0, review: 1, hardGateFailures: 0 },
        ],
    );
});

test('case detail summaries keep raw output content out of the default label', () => {
    assert.equal(summarizeEvaluationOutput('candidate private text'), '文本输出 · 22 字符');
    assert.equal(summarizeEvaluationOutput({ questions: [{ text: 'q1' }, { text: 'q2' }], metadata: {} }), '结构化输出 · 2 个字段，含 2 个问题');
    assert.equal(evaluationReviewReasonLabel('hard_gate_failure'), '硬门禁失败');
});

test('case detail paginates score rules in stable ten-rule pages and bounds stale pages', () => {
    const scores = Array.from({ length: 21 }, (_, index) => ({
        id: String(index + 1),
        case_run_id: 'run',
        metric_name: `rule-${index + 1}`,
        value: 1,
        status: 'passed',
        source: 'deterministic' as const,
        reason: null,
        severity: 'low',
        hard_gate: false,
        evidence_refs: [],
        metric_version: 'v1',
        created_at: '2026-08-20T00:00:00Z',
    }));

    const secondPage = paginateEvaluationScores(scores, 2);
    assert.equal(secondPage.totalPages, 3);
    assert.equal(secondPage.page, 2);
    assert.deepEqual(secondPage.scores.map((score) => score.metric_name), [
        'rule-11', 'rule-12', 'rule-13', 'rule-14', 'rule-15',
        'rule-16', 'rule-17', 'rule-18', 'rule-19', 'rule-20',
    ]);

    const boundedLastPage = paginateEvaluationScores(scores, 99);
    assert.equal(boundedLastPage.page, 3);
    assert.deepEqual(boundedLastPage.scores.map((score) => score.metric_name), ['rule-21']);
});

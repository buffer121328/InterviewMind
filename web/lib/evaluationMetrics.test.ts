import assert from 'node:assert/strict';
import test from 'node:test';
import { formatEvaluationRate, formatSignedRate, groupScoresBySource, overviewCards, runProgress } from './evaluationMetrics.ts';
import { passesGateThreshold } from './evaluationGates.ts';
import { deriveAnnotationState } from './evaluationAnnotations.ts';

test('evaluation rates and progress remain bounded', () => {
    assert.equal(formatEvaluationRate(0.875), '87.5%');
    assert.equal(formatEvaluationRate(null), '样本不足');
    assert.equal(formatSignedRate(-0.125), '-12.5%');
    assert.equal(formatSignedRate(null), '无基线');
    assert.equal(runProgress({ summary: { progress: 2 } } as never), 1);
});

test('evaluation scores remain separated by source', () => {
    const grouped = groupScoresBySource([
        { source: 'deterministic', metric_name: 'security' },
        { source: 'judge', metric_name: 'quality' },
        { source: 'human', metric_name: 'quality' },
    ] as never);
    assert.equal(grouped.deterministic.length, 1);
    assert.equal(grouped.judge.length, 1);
    assert.equal(grouped.human.length, 1);
});

test('overview exposes trace, tool, dependency and approval governance metrics', () => {
    const cards = overviewCards({
        run_count: 2,
        runtime_success_rate: 1,
        semantic_success_rate: 0.5,
        complete_success_rate: 0.5,
        hard_gate_pass_rate: 1,
        factual_support_rate: null,
        tool_call_accuracy: null,
        judge_human_agreement: null,
        pending_review_count: 1,
        regression_count: 0,
        p95_latency_ms: 120,
        token_delta_percent: null,
        trace_completeness_rate: 0.75,
        trace_incomplete_count: 1,
        tool_failure_rate: 0.25,
        tool_execution_success_rate: 0.75,
        tool_p95_duration_ms: 80,
        dependency_failure_rate: 0.5,
        external_io_timeout_rate: 0.25,
        retrieval_empty_rate: 0.5,
        external_effect_count: 2,
        external_effect_blocked_count: 1,
        approval_event_count: 3,
        approval_violation_count: 1,
        langfuse_reported_case_count: 1,
        langfuse_failed_case_count: 1,
    });
    const values = Object.fromEntries(cards.map((card) => [card.key, card.value]));

    assert.equal(values.trace, '75.0%');
    assert.equal(values['trace-missing'], '1');
    assert.equal(values['tool-failure'], '25.0%');
    assert.equal(values['tool-success'], '75.0%');
    assert.equal(values['dependency-failure'], '50.0%');
    assert.equal(values['dependency-timeout'], '25.0%');
    assert.equal(values['retrieval-empty'], '50.0%');
    assert.equal(values.approval, '3');
    assert.equal(values['approval-violations'], '1');
    assert.equal(values['langfuse-failed'], '1');
});

test('gate thresholds support higher, lower and exact comparisons', () => {
    assert.equal(passesGateThreshold(0.9, 0.8), true);
    assert.equal(passesGateThreshold(0.1, { value: 0.2, comparison: 'lte' }), true);
    assert.equal(passesGateThreshold(0, { value: 0, comparison: 'eq' }), true);
});

test('dual blind review conflicts until adjudicated', () => {
    const base = { metric_name: 'quality', blind: true, adjudication: false };
    assert.equal(deriveAnnotationState([
        { ...base, reviewer_key: 'A', value: true },
        { ...base, reviewer_key: 'B', value: false },
    ] as never), 'conflicted');
    assert.equal(deriveAnnotationState([
        { ...base, reviewer_key: 'A', value: true },
        { ...base, reviewer_key: 'B', value: false },
        { ...base, reviewer_key: 'adjudicator', value: true, adjudication: true },
    ] as never), 'adjudicated');
});

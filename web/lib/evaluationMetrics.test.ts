import assert from 'node:assert/strict';
import test from 'node:test';
import { formatEvaluationRate, formatSignedRate, groupScoresBySource, runProgress } from './evaluationMetrics.ts';
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

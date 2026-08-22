import assert from 'node:assert/strict';
import test from 'node:test';
import {
    buildEvaluationTrendPresentation,
    formatTrendLatency,
    formatTrendPercentage,
    selectTrendLatencyUnit,
} from './evaluationTrendPresentation.ts';

const trend = {
    run_id: 'run-1',
    created_at: '2026-08-20T09:42:00Z',
    environment: 'local',
    agent_name: 'interview_planner',
    agent_version: '1',
    prompt_name: 'interview.planner',
    prompt_version: 'v1',
    model_config_hash: 'model',
    dataset_version: 'v1',
    sample_count: 3,
    complete_success_rate: 0.75,
    p50_latency_ms: 40_000,
    p95_latency_ms: 80_000,
    token_total: 120_000,
    p50_tokens: 20_000,
    p95_tokens: 80_000,
} as const;

test('version trend presentation keeps quality percentages separate from minute-scale latency', () => {
    const presentation = buildEvaluationTrendPresentation([trend]);

    assert.equal(presentation.latencyUnit, '分钟');
    assert.deepEqual(presentation.qualityData, [{
        name: '08/20 17:42',
        success: 75,
        sample: 3,
    }]);
    assert.deepEqual(presentation.latencyData, [{
        name: '08/20 17:42',
        latency: 80_000,
        sample: 3,
    }]);
});

test('trend latency uses seconds below one minute and minutes at or above one minute', () => {
    assert.equal(selectTrendLatencyUnit([{ ...trend, p95_latency_ms: 1_500 }]), '秒');
    assert.equal(selectTrendLatencyUnit([trend]), '分钟');
    assert.equal(formatTrendLatency(1_500, '秒'), '1.5 秒');
    assert.equal(formatTrendLatency(80_000, '分钟'), '1.3 分钟');
});

test('trend presentation preserves unavailable values instead of plotting zeroes', () => {
    const presentation = buildEvaluationTrendPresentation([{
        ...trend,
        complete_success_rate: null,
        p95_latency_ms: null,
    }]);

    assert.equal(presentation.qualityData[0].success, null);
    assert.equal(presentation.latencyData[0].latency, null);
    assert.equal(formatTrendLatency(null, '秒'), '-');
    assert.equal(formatTrendPercentage(null), '-');
    assert.equal(presentation.hasQualityData, false);
    assert.equal(presentation.hasLatencyData, false);
});

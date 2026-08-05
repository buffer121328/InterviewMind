import assert from 'node:assert/strict';
import test from 'node:test';
import { describeModelMetricEvent, formatMetricRate, performanceCards } from './agentPerformance.ts';

test('preserves no-data semantics instead of claiming zero risk', () => {
    assert.equal(formatMetricRate(null), '暂无样本');
});

test('describes safe provider and fallback metadata', () => {
    const text = describeModelMetricEvent({ event_id: '1', run_id: 'r', trace_id: null, agent_name: 'a', task_type: 'interview_turn', stage: 'answer', event_type: 'llm.request.failed', is_degradation: true, timestamp: '', payload: { model_provider: 'openai', model_name: 'gpt', attempt: 2, fallback_index: 1, failure_type: 'timeout' } });
    assert.match(text, /fallback 1/);
});

test('builds all eight required overview cards', () => {
    const cards = performanceCards({ sample_event_count: 0, total_matching_events: 0, run_count: 0, run_success_rate: null, logical_call_count: 0, physical_request_count: 0, call_amplification: null, p50_model_duration_ms: null, p95_model_duration_ms: null, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_hit_rate: null, retry_rate: null, fallback_rate: null, timeout_rate: null, authoritative_context_sample_count: 0, authoritative_truncation_rate: null, overflow_strategy_counts: {}, definitions: {} });
    assert.equal(cards.length, 8);
});

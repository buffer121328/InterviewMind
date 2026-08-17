import assert from 'node:assert/strict';
import test from 'node:test';
import {
    buildModelCallTrendChart,
    formatMetricRate,
    getTaskHealthPresentation,
    hasModelCallTrendSamples,
    hasPerformanceTrendSamples,
    performanceCards,
    summarizeTaskHealth,
} from './agentPerformance.ts';
import type { AgentTaskHealth } from './api/agentRunTypes.ts';

function health(overrides: Partial<AgentTaskHealth> = {}): AgentTaskHealth {
    return {
        run_id: 'run-1',
        trace_id: 'trace-1',
        task_type: 'interview_report',
        agent_name: 'interview_report',
        task_status: 'succeeded',
        stage: 'session_report.narrative_composer',
        primary_stage: 'session_report.narrative_composer',
        outcome: 'succeeded',
        primary_issue: null,
        model_provider: 'openai',
        model_name: 'gpt-5',
        logical_call_count: 1,
        physical_attempt_count: 1,
        failed_attempt_count: 0,
        timeout_count: 0,
        retry_count: 0,
        fallback_count: 0,
        skipped_count: 0,
        context_protection_count: 0,
        created_at: '2026-08-15T08:43:41.000Z',
        finished_at: '2026-08-15T08:43:45.000Z',
        last_model_event_at: '2026-08-15T08:43:45.000Z',
        ...overrides,
    };
}

test('preserves no-data semantics instead of claiming zero risk', () => {
    assert.equal(formatMetricRate(null), '暂无样本');
});

test('uses a shared explicit data boundary for overview trend charts', () => {
    assert.equal(hasPerformanceTrendSamples([]), false);
    assert.equal(hasPerformanceTrendSamples([{
        date: '2026-08-17', logical_call_count: 1, physical_request_count: 1,
        retry_count: 0, fallback_count: 0, timeout_count: 0,
        p95_model_duration_ms: 120, input_tokens: 10, output_tokens: 4, total_tokens: 14,
    }]), true);
});

test('presents a recovered interview report as a completed business task, not a failed event', () => {
    const presentation = getTaskHealthPresentation(health({
        outcome: 'recovered',
        primary_issue: 'timeout',
        timeout_count: 2,
        retry_count: 1,
        fallback_count: 1,
        physical_attempt_count: 3,
        failed_attempt_count: 2,
    }));

    assert.equal(presentation.businessCategory, '文本面试');
    assert.equal(presentation.taskLabel, '面试报告');
    assert.equal(presentation.statusLabel, '自动恢复完成');
    assert.equal(presentation.stageLabel, '报告撰写');
    assert.match(presentation.disposition, /最终已完成/);
    assert.match(presentation.diagnostics.join(' '), /2 次超时/);
    assert.match(presentation.diagnostics.join(' '), /已切换备用模型/);
});

test('attributes a final failure to the business task and a stable root cause', () => {
    const presentation = getTaskHealthPresentation(health({
        task_type: 'resume_optimize',
        task_status: 'failed',
        outcome: 'failed',
        primary_issue: 'authentication',
        primary_stage: 'rewrite',
        failed_attempt_count: 1,
    }));

    assert.equal(presentation.businessCategory, '简历优化');
    assert.equal(presentation.taskLabel, '简历优化');
    assert.equal(presentation.statusLabel, '任务失败');
    assert.equal(presentation.primaryIssueLabel, '模型授权异常');
});

test('summarizes task outcomes and root causes by task rather than raw event count', () => {
    const summary = summarizeTaskHealth([
        health({ run_id: 'healthy', task_type: 'interview_turn' }),
        health({ run_id: 'recovered', outcome: 'recovered', primary_issue: 'timeout', timeout_count: 1, fallback_count: 1, physical_attempt_count: 2 }),
        health({ run_id: 'failed', task_type: 'resume_generation', task_status: 'failed', outcome: 'failed', primary_issue: 'authentication' }),
        health({ run_id: 'active', task_type: 'job_recommendation_capture', task_status: 'running', outcome: 'active', primary_issue: 'network' }),
    ]);

    assert.equal(summary.total, 4);
    assert.equal(summary.finalSucceeded, 2);
    assert.equal(summary.recovered, 1);
    assert.equal(summary.failed, 1);
    assert.equal(summary.active, 1);
    assert.equal(summary.attentionCount, 3);
    assert.deepEqual(summary.categoryDistribution, [
        { name: '文本面试', count: 2 },
        { name: '简历优化', count: 1 },
        { name: '岗位投递', count: 1 },
    ]);
    assert.deepEqual(summary.issueDistribution, [
        { name: '模型响应超时', count: 1 },
        { name: '模型授权异常', count: 1 },
        { name: '网络连接异常', count: 1 },
    ]);
    assert.deepEqual(summary.trend.map(point => point.count), [4]);
});

test('builds the actionable overview cards without implementation-only cache metrics', () => {
    const cards = performanceCards({ sample_event_count: 1, total_matching_events: 1, run_count: 1, run_success_rate: 1, logical_call_count: 1, physical_request_count: 1, call_amplification: 1, p50_model_duration_ms: 100, p95_model_duration_ms: 100, input_tokens: 120, output_tokens: 30, total_tokens: 150, cache_read_tokens: 0, cache_hit_rate: null, retry_rate: 0.1, fallback_rate: 0, timeout_rate: 0, authoritative_context_sample_count: 0, authoritative_truncation_rate: null, overflow_strategy_counts: {}, definitions: {} });
    assert.equal(cards.length, 8);
    assert.deepEqual(cards.map(([label]) => label), [
        '运行成功率', '模型 P50', '模型 P95', '调用放大',
        'Fallback', 'Timeout', 'Retry 率', 'Token 消耗',
    ]);
    assert.equal(cards.at(-2)?.[1], '10.0%');
    assert.equal(cards.at(-1)?.[1], '150');
});


test('turns safe named-model aggregates into readable chart series without dropping the other-model bucket', () => {
    const chart = buildModelCallTrendChart([
        {
            date: '2026-08-16', model_name: 'doubao-seed-1-6-250615', model_provider: 'volcengine',
            logical_call_count: 6, physical_request_count: 6, retry_count: 0, fallback_count: 0, timeout_count: 0,
            p95_model_duration_ms: 120, input_tokens: 20, output_tokens: 8, total_tokens: 28,
        },
        {
            date: '2026-08-16', model_name: '其他模型', model_provider: null,
            logical_call_count: 1, physical_request_count: 1, retry_count: 0, fallback_count: 0, timeout_count: 0,
            p95_model_duration_ms: null, input_tokens: 0, output_tokens: 0, total_tokens: null,
        },
        {
            date: '2026-08-17', model_name: 'doubao-seed-1-6-250615', model_provider: 'volcengine',
            logical_call_count: 2, physical_request_count: 2, retry_count: 0, fallback_count: 0, timeout_count: 0,
            p95_model_duration_ms: 100, input_tokens: 4, output_tokens: 2, total_tokens: 6,
        },
    ]);

    assert.equal(hasModelCallTrendSamples([]), false);
    assert.equal(hasModelCallTrendSamples([{
        date: '2026-08-16', model_name: 'doubao-seed-1-6-250615', model_provider: 'volcengine',
        logical_call_count: 1, physical_request_count: 1, retry_count: 0, fallback_count: 0, timeout_count: 0,
        p95_model_duration_ms: null, input_tokens: 0, output_tokens: 0, total_tokens: null,
    }]), true);
    assert.deepEqual(chart.series, [
        { key: 'model_0', label: 'doubao-seed-1-6-250615 · volcengine' },
        { key: 'model_1', label: '其他模型' },
    ]);
    assert.deepEqual(chart.data, [
        { date: '2026-08-16', model_0: 6, model_1: 1 },
        { date: '2026-08-17', model_0: 2, model_1: 0 },
    ]);
});

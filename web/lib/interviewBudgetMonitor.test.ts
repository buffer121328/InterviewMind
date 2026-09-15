import assert from 'node:assert/strict';
import test from 'node:test';

import {
    formatBudgetDuration,
    formatBudgetTokens,
    getBudgetFailureLabel,
    getBudgetSourceLabel,
    getBudgetStageLabel,
    getBudgetStatusLabel,
    getBudgetWarningLabel,
    getVisibleStageMetrics,
    isQueuedBudgetStatus,
} from './interviewBudgetMonitor.ts';
import type { InterviewBudgetStage } from './api/agentRunTypes.ts';

test('budget monitor formats context/reviewer labels and safe failure states', () => {
    assert.equal(getBudgetStageLabel('session_report.review.technical_depth'), '技术深度评审');
    assert.equal(getBudgetStageLabel('session_report.reviewer_context.job_fit'), '岗位匹配评审 · 上下文组装');
    assert.equal(getBudgetStageLabel('session_report.narrative_composer'), '报告叙事汇总');
    assert.equal(getBudgetStageLabel('interview_report.context_assembly'), '报告 · 上下文组装');
    assert.equal(getBudgetStageLabel('session_report.unknown_stage'), 'unknown stage');
    assert.equal(getBudgetFailureLabel('timeout'), '超时');
    assert.equal(getBudgetWarningLabel('context_protection'), '触发过上下文保护');
    assert.equal(getBudgetSourceLabel('job_description'), 'JD 岗位描述');
    assert.equal(getBudgetSourceLabel('resume'), '简历信息');
    assert.equal(getBudgetSourceLabel('qa_history'), 'QA 历史');
    assert.equal(getBudgetStatusLabel('failed'), '失败');
});

test('budget monitor keeps estimates visibly separate from provider usage', () => {
    assert.equal(formatBudgetTokens(null, 420), '约 420 tokens');
    assert.equal(formatBudgetTokens(380, 420), '380 tokens');
    assert.equal(formatBudgetTokens(null, null), '未返回 usage');
    assert.equal(formatBudgetDuration(1250), '1.3 s');
    assert.equal(formatBudgetDuration(null), '未返回');
});

test('queued work is distinguished from started model execution', () => {
    assert.equal(isQueuedBudgetStatus('queued'), true);
    assert.equal(isQueuedBudgetStatus('retrying'), true);
    assert.equal(isQueuedBudgetStatus('running'), false);
    assert.equal(isQueuedBudgetStatus('failed'), false);
});

test('context assembly only renders metrics backed by values', () => {
    const stage: InterviewBudgetStage = {
        stage: 'interview_report.context_assembly',
        kind: 'context',
        status: 'succeeded',
        event_count: 1,
        attempt_count: 1,
        completed_count: 1,
        failed_count: 0,
        skipped_count: 0,
        retry_count: 0,
        fallback_count: 0,
        input_chars: 7132,
        estimated_input_tokens: 1783,
        input_tokens: null,
        output_tokens: null,
        total_tokens: null,
        duration_ms: 0,
        model_duration_ms: 0,
        elapsed_ms: 0,
        deadline_ms: null,
        deadline_remaining_ms: null,
        failure_types: [],
        primary_failure: null,
        model_names: [],
        first_event_at: null,
        last_event_at: null,
    };

    assert.deepEqual(getVisibleStageMetrics(stage), [
        { label: '输入估算', value: '约 1,783 tokens' },
    ]);
    assert.equal(getVisibleStageMetrics({ ...stage, total_tokens: 80, model_duration_ms: 1250 }).length, 3);
});

test('reviewer stage pairs keep context assembly beside the matching review', async () => {
    const { getReviewerStagePairs } = await import('./interviewBudgetMonitor.ts');
    assert.deepEqual(getReviewerStagePairs()[0], {
        key: 'technical_depth',
        label: '技术深度评审',
        contextStage: 'session_report.reviewer_context.technical_depth',
        reviewStage: 'session_report.review.technical_depth',
    });
    assert.equal(getReviewerStagePairs().length, 4);
});

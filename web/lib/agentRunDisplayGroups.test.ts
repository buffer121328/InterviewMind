import assert from 'node:assert/strict';
import test from 'node:test';

import {
    getAgentRunCategory,
    getAgentRunGroupStatusLabel,
    getAgentRunStatusLabel,
    getInterviewSessionProgressLabel,
    groupAgentRunsForDisplay,
    summarizeResumeRunResult,
} from './agentRunDisplayGroups.ts';
import type { AgentRun } from './api/agentRunTypes.ts';

/** Creates the smallest valid AgentRun fixture for presentation-only grouping tests. */
function run(overrides: Partial<AgentRun>): AgentRun {
    return {
        run_id: 'run-1', agent_name: 'agent', agent_version: '1', task_type: 'resume_workspace', title: '任务',
        status: 'succeeded', stage: 'complete', plan: [], attempts: 1, max_attempts: 3, can_retry: false, can_cancel: false,
        created_at: '2026-07-27T00:00:00Z', updated_at: '2026-07-27T00:00:00Z', ...overrides,
    };
}

test('getAgentRunCategory maps every internal task type to one user-facing category', () => {
    assert.deepEqual([
        getAgentRunCategory('interview_start'),
        getAgentRunCategory('interview_turn'),
        getAgentRunCategory('interview_report'),
        getAgentRunCategory('voice_interview_turn'),
        getAgentRunCategory('resume_optimize'),
        getAgentRunCategory('resume_workspace'),
        getAgentRunCategory('resume_generation'),
        getAgentRunCategory('job_assets'),
    ], ['text-interview', 'text-interview', 'text-interview', 'voice-interview', 'resume-optimization', 'resume-optimization', 'resume-optimization', 'job-delivery']);
});

test('groupAgentRunsForDisplay separates user categories and dates', () => {
    const groups = groupAgentRunsForDisplay([{ runs: [
        run({ task_type: 'resume_optimize', updated_at: '2026-07-27T04:00:00Z' }),
        run({ run_id: 'interview', task_type: 'interview_turn', updated_at: '2026-07-26T04:00:00Z' }),
        run({ run_id: 'voice', task_type: 'voice_interview_turn', updated_at: '2026-07-26T04:00:00Z' }),
        run({ run_id: 'assets', task_type: 'job_assets', updated_at: '2026-07-20T04:00:00Z' }),
    ] }], new Date('2026-07-27T12:00:00Z'));

    assert.deepEqual(groups.map(group => `${group.categoryLabel}:${group.dateLabel}`), ['文本面试:昨天', '语音面试:昨天', '简历优化:今天', '岗位投递:过去7天']);
});

test('interview run labels distinguish one generated response from the whole interview lifecycle', () => {
    const activeTurn = run({
        task_type: 'interview_turn',
        status: 'succeeded',
        session_id: 'session-1',
        session_status: 'active',
        session_question_count: 0,
        session_max_questions: 5,
    });

    assert.equal(getAgentRunStatusLabel(activeTurn), '本次回复已生成');
    assert.equal(getInterviewSessionProgressLabel(activeTurn), '面试进行中 · 当前第 1/5 题');
    assert.equal(getAgentRunGroupStatusLabel('text-interview', 'succeeded'), '生成任务已结束');
});

test('interview session progress reports completion only from the linked session status', () => {
    const completedTurn = run({
        task_type: 'interview_turn',
        session_id: 'session-1',
        session_status: 'completed',
        session_question_count: 5,
        session_max_questions: 5,
    });
    const legacyTurn = run({ task_type: 'interview_turn', session_id: 'session-legacy' });

    assert.equal(getInterviewSessionProgressLabel(completedTurn), '整场面试已完成 · 5/5 题');
    assert.equal(getInterviewSessionProgressLabel(legacyTurn), '本状态仅表示本次生成任务，不代表整场面试完成');
});

test('summarizeResumeRunResult exposes bounded stage metadata without raw resume passages', () => {
    const summary = summarizeResumeRunResult({
        result_id: 42,
        competition_analysis: { overall_score: 86, strengths: ['量化项目成果'] },
        jd_matching: { overall_match_score: 78, missing_keywords: ['Kubernetes'] },
        content_optimization: { match_score: 78, key_improvements: ['补充项目指标'], change_items: [{ original_text: 'private resume text' }] },
        generated_resume_id: 9,
    });

    assert.equal(summary?.resultId, '42');
    assert.match(summary?.stages[2]?.detail || '', /补充项目指标/);
    assert.doesNotMatch(JSON.stringify(summary), /private resume text/);
    assert.deepEqual(summary?.artifact, { id: '9', name: null });
});

test('summarizeResumeRunResult uses professional-generation stages for resume_generation', () => {
    const summary = summarizeResumeRunResult({
        generated_resume_id: 2,
        generated_resume_title: '郭成- AI应用开发简历',
        generation_session_id: 'generation-1',
    }, 'resume_generation');

    assert.equal(summary.stages.length, 1);
    assert.equal(summary.stages[0]?.label, '专业简历生成');
    assert.match(summary.stages[0]?.detail || '', /事实核查/);
    assert.doesNotMatch(JSON.stringify(summary), /未返回该阶段/);
    assert.deepEqual(summary.artifact, { id: '2', name: '郭成- AI应用开发简历' });
});

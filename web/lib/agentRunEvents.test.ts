import assert from 'node:assert/strict';
import test from 'node:test';

import { applyAgentRunEvent, buildInteractiveExecutionPlan, parseAgentRunEventEnvelope } from './agentRunEvents.ts';
import type { AgentRun } from './api/agentRunTypes.ts';

test('parseAgentRunEventEnvelope accepts current schema version', () => {
    const event = parseAgentRunEventEnvelope({
        event_id: 'evt-1',
        run_id: 'run-1',
        sequence: 3,
        type: 'run.completed',
        stage: 'succeeded',
        payload: { ok: true },
        schema_version: 1,
        timestamp: '2026-01-01T00:00:00.000Z',
    });

    assert.equal(event?.run_id, 'run-1');
    assert.equal(event?.schema_version, 1);
    assert.deepEqual(event?.payload, { ok: true });
});

test('parseAgentRunEventEnvelope accepts JSON string content', () => {
    const event = parseAgentRunEventEnvelope(JSON.stringify({
        run_id: 'run-1',
        type: 'run.started',
        payload: {},
        schema_version: 1,
    }));

    assert.equal(event?.run_id, 'run-1');
    assert.equal(event?.type, 'run.started');
});

test('parseAgentRunEventEnvelope rejects unknown future schema versions', () => {
    const event = parseAgentRunEventEnvelope({
        run_id: 'run-1',
        type: 'run.completed',
        payload: {},
        schema_version: 999,
    });

    assert.equal(event, null);
});

test('parseAgentRunEventEnvelope rejects malformed content', () => {
    assert.equal(parseAgentRunEventEnvelope('{not json'), null);
    assert.equal(parseAgentRunEventEnvelope({ type: 'run.started' }), null);
});

test('parseAgentRunEventEnvelope preserves prompt version on run.created', () => {
    const event = parseAgentRunEventEnvelope({
        event_id: 'evt-2',
        run_id: 'run-1',
        sequence: 1,
        type: 'run.created',
        payload: {
            task_type: 'interview_start',
            agent_name: 'interview_starter',
            agent_version: '1',
            prompt_name: 'interview.planner',
            prompt_version: '1',
        },
        schema_version: 1,
        timestamp: '2026-01-01T00:00:00.000Z',
    });

    assert.equal(event?.type, 'run.created');
    assert.equal(event?.payload.prompt_version, '1');
    assert.equal(event?.payload.prompt_name, 'interview.planner');
});

test('parseAgentRunEventEnvelope rejects unknown event types', () => {
    const event = parseAgentRunEventEnvelope({
        run_id: 'run-1',
        type: 'run.future.changed',
        payload: {},
        schema_version: 1,
    });

    assert.equal(event, null);
});

test('parseAgentRunEventEnvelope accepts governance audit events', () => {
    for (const type of ['tool.execution', 'guardrail.input', 'guardrail.output'] as const) {
        const event = parseAgentRunEventEnvelope({
            run_id: 'run-1',
            type,
            payload: { status: 'completed' },
            schema_version: 1,
        });

        assert.equal(event?.type, type);
    }
});


test('buildInteractiveExecutionPlan maps active stages to UI plan state', () => {
    const plan = buildInteractiveExecutionPlan([{
        event_id: 'evt-3',
        run_id: 'run-1',
        sequence: 2,
        type: 'run.stage.changed',
        stage: 'generating_response',
        payload: {},
        schema_version: 1,
        timestamp: '2026-01-01T00:00:01.000Z',
    }]);

    assert.deepEqual(plan.map(step => [step.id, step.status]), [
        ['save_answer', 'completed'],
        ['analyze_answer', 'completed'],
        ['generate_response', 'running'],
        ['update_progress', 'pending'],
    ]);
});

test('buildInteractiveExecutionPlan marks terminal events', () => {
    const completed = buildInteractiveExecutionPlan([{
        event_id: 'evt-4',
        run_id: 'run-1',
        sequence: 3,
        type: 'run.completed',
        stage: 'succeeded',
        payload: {},
        schema_version: 1,
        timestamp: '2026-01-01T00:00:02.000Z',
    }]);
    const failed = buildInteractiveExecutionPlan([{
        event_id: 'evt-5',
        run_id: 'run-1',
        sequence: 3,
        type: 'run.failed',
        stage: 'generating_response',
        payload: { message: 'failed' },
        schema_version: 1,
        timestamp: '2026-01-01T00:00:02.000Z',
    }]);

    assert.deepEqual(completed.map(step => step.status), ['completed', 'completed', 'completed', 'completed']);
    assert.equal(failed.find(step => step.id === 'generate_response')?.status, 'failed');
});

test('stage events immediately complete prior report stages for the live monitor', () => {
    const run: AgentRun = {
        run_id: 'report-1', status: 'running', stage: 'assembling_evidence', attempts: 1, max_attempts: 3,
        can_cancel: true, can_retry: false, created_at: '2026-01-01T00:00:00.000Z', updated_at: '2026-01-01T00:00:00.000Z',
        agent_name: 'interview_reporter', agent_version: '1', task_type: 'interview_report' as const, title: '生成面试报告',
        plan: [
            { id: 'loading_session', title: '读取面试问答', status: 'completed' },
            { id: 'assembling_evidence', title: '整理面试证据', status: 'running' },
            { id: 'generating_assessment', title: '生成综合评估', status: 'pending' },
        ],
    };
    const next = applyAgentRunEvent(run, {
        event_id: 'evt-report-2', run_id: 'report-1', sequence: 3, type: 'run.stage.changed',
        stage: 'generating_assessment', payload: {}, schema_version: 1, timestamp: '2026-01-01T00:00:02.000Z',
    });

    assert.deepEqual(next.plan.map(step => step.status), ['completed', 'completed', 'running']);
});

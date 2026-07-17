import assert from 'node:assert/strict';
import test from 'node:test';

import { getStreamEventCategory, parseStreamEvent, reduceExecutionPlanStreamEvent } from './streamEvents.ts';

test('parseStreamEvent parses chat plan payloads', () => {
    const event = parseStreamEvent({
        type: 'plan',
        content: JSON.stringify({
            run_id: 'run-1',
            steps: [{ id: 'queued', title: '等待执行资源', status: 'running' }],
        }),
    });

    assert.equal(event?.type, 'plan');
    if (!event || event.type !== 'plan') throw new Error('expected plan event');
    assert.equal(Array.isArray(event.content), false);
    assert.equal((event.content as Record<string, unknown>).run_id, 'run-1');
});

test('parseStreamEvent parses step updates and state updates', () => {
    const step = parseStreamEvent({
        type: 'step_update',
        content: JSON.stringify({ id: 'save_answer', status: 'completed' }),
    });
    const state = parseStreamEvent({
        type: 'state_update',
        content: JSON.stringify({ question_count: 2, max_questions: 5 }),
    });

    assert.equal(step?.type, 'step_update');
    if (!step || step.type !== 'step_update') throw new Error('expected step_update event');
    assert.equal(step.content.id, 'save_answer');
    assert.equal(step.content.status, 'completed');

    assert.equal(state?.type, 'state_update');
    if (!state || state.type !== 'state_update') throw new Error('expected state_update event');
    assert.equal(state.content.question_count, 2);
    assert.equal(state.content.max_questions, 5);
});

test('parseStreamEvent parses voice and domain delta events', () => {
    const progress = parseStreamEvent({ type: 'progress', current: 3, total: 8 });
    const done = parseStreamEvent({ type: 'done', text: '完成' });
    const error = parseStreamEvent({ type: 'error', message: '失败' });
    const run = parseStreamEvent({ type: 'run', run_id: 'run-1' });

    assert.deepEqual(progress, { type: 'progress', current: 3, total: 8 });
    assert.deepEqual(done, { type: 'done', content: '完成' });
    assert.deepEqual(error, { type: 'error', content: '失败' });
    assert.deepEqual(run, { type: 'run', run_id: 'run-1' });
});

test('parseStreamEvent rejects malformed events', () => {
    assert.equal(parseStreamEvent({ type: 'step_update', content: '{}' }), null);
    assert.equal(parseStreamEvent({ type: 'progress', current: '3' }), null);
    assert.equal(parseStreamEvent({ type: 'agent_run_event', content: '{not json' }), null);
    assert.equal(parseStreamEvent({ type: 'unknown', content: {} }), null);
});


test('parseStreamEvent parses audit events and classifies event categories', () => {
    const audit = parseStreamEvent({ type: 'audit', action: 'settings.changed', actor: 'user', content: { target: 'model_pool' } });
    const plan = parseStreamEvent({ type: 'plan', content: [{ id: 'queued', title: '等待', status: 'running' }] });
    const text = parseStreamEvent({ type: 'text', content: 'hello' });
    const run = parseStreamEvent({
        type: 'agent_run_event',
        content: {
            run_id: 'run-1',
            type: 'run.started',
            payload: {},
            schema_version: 1,
        },
    });

    assert.deepEqual(audit, { type: 'audit', action: 'settings.changed', actor: 'user', content: { target: 'model_pool' } });
    if (!audit || !plan || !text || !run) throw new Error('expected parsed events');
    assert.equal(getStreamEventCategory(audit), 'audit_event');
    assert.equal(getStreamEventCategory(plan), 'ui_delta');
    assert.equal(getStreamEventCategory(text), 'domain_event');
    assert.equal(getStreamEventCategory(run), 'run_event');
});


test('reduceExecutionPlanStreamEvent applies plan and step deltas', () => {
    const planEvent = parseStreamEvent({
        type: 'plan',
        content: JSON.stringify({
            run_id: 'run-1',
            steps: [
                { id: 'save_answer', title: '保存回答', status: 'running' },
                { id: 'generate_response', title: '生成回复', status: 'pending' },
            ],
        }),
    });
    if (!planEvent) throw new Error('expected plan event');
    const planned = reduceExecutionPlanStreamEvent([], planEvent);

    assert.equal(planned?.currentInteractiveRunId, 'run-1');
    assert.equal(planned?.executionPlan.length, 2);

    const stepEvent = parseStreamEvent({ type: 'step_update', content: { id: 'generate_response', status: 'running' } });
    if (!stepEvent || !planned) throw new Error('expected step event');
    const updated = reduceExecutionPlanStreamEvent(planned.executionPlan, stepEvent);

    assert.equal(updated?.executionPlan.find(step => step.id === 'generate_response')?.status, 'running');
});

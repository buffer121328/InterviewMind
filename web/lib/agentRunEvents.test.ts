import assert from 'node:assert/strict';
import test from 'node:test';

import { parseAgentRunEventEnvelope } from './agentRunEvents.ts';

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

test('parseAgentRunEventEnvelope rejects unknown event types', () => {
    const event = parseAgentRunEventEnvelope({
        run_id: 'run-1',
        type: 'run.future.changed',
        payload: {},
        schema_version: 1,
    });

    assert.equal(event, null);
});

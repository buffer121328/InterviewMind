import assert from 'node:assert/strict';
import test from 'node:test';
import { formatAgentRunDate, parseAgentRunTimestamp } from './agentRunPresentation.ts';

test('parses legacy unzoned AgentRun timestamps as persisted UTC', () => {
    const timestamp = parseAgentRunTimestamp('2026-08-15T16:43:41');
    assert.equal(timestamp?.toISOString(), '2026-08-15T16:43:41.000Z');
});

test('renders AgentRun timestamps in China Standard Time regardless of browser timezone', () => {
    assert.match(formatAgentRunDate('2026-08-15T16:43:41Z'), /08\/16.*00:43/);
    assert.match(formatAgentRunDate('2026-08-15T16:43:41'), /08\/16.*00:43/);
});

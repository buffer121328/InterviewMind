import assert from 'node:assert/strict';
import test from 'node:test';

import { applyAgentRunEventGroups, groupAgentRuns } from './agentRunGroups.ts';
import type { AgentRun, AgentRunEvent } from './api/agentRunTypes.ts';
import type { GroupedAgentRun } from './api/agentRuns.ts';

function run(overrides: Partial<AgentRun>): AgentRun {
    return {
        run_id: 'run-1', agent_name: 'interviewer', agent_version: '1', task_type: 'interview_start',
        title: '生成面试', status: 'queued', stage: 'queued', plan: [], attempts: 0, max_attempts: 3,
        can_retry: false, can_cancel: true, created_at: '2026-07-27T00:00:00Z',
        updated_at: '2026-07-27T00:00:00Z',
        ...overrides,
    };
}

test('groupAgentRuns retains a safely resolved session title without changing its session grouping key', () => {
    const groups = groupAgentRuns([
        run({ run_id: 'run-new', session_id: 'session-uuid', session_title: '产品经理模拟面试', updated_at: '2026-07-27T01:00:00Z' }),
        run({ run_id: 'run-old', session_id: 'session-uuid', session_title: null }),
    ]);

    assert.equal(groups.length, 1);
    assert.equal(groups[0]?.key, 'session:session-uuid');
    assert.equal(groups[0]?.sessionTitle, '产品经理模拟面试');
    assert.deepEqual(groups[0]?.runs.map(item => item.run_id), ['run-new', 'run-old']);
});

test('groupAgentRuns leaves a missing session title for the UI fallback', () => {
    const [group] = groupAgentRuns([run({ session_id: 'session-uuid', session_title: '   ' })]);

    assert.equal(group?.sessionTitle, null);
});

test('applyAgentRunEventGroups updates only the matching server group child', () => {
    const groups: GroupedAgentRun[] = [
        { group_type: 'session', session_id: 'session-uuid', session_title: '产品经理模拟面试', runs: [run({ run_id: 'session-run' })] },
        { group_type: 'other', session_id: null, session_title: null, runs: [run({ run_id: 'legacy-run' })] },
    ];
    const event: AgentRunEvent = {
        event_id: 'event-1', run_id: 'legacy-run', sequence: 1, type: 'run.started', stage: 'planning',
        payload: {}, schema_version: 1, timestamp: '2026-07-27T01:00:00Z',
    };

    const updated = applyAgentRunEventGroups(groups, event);

    assert.equal(updated.length, 2);
    assert.equal(updated[0]?.runs[0]?.status, 'queued');
    assert.equal(updated[1]?.runs[0]?.status, 'running');
    assert.equal(updated[1]?.runs[0]?.stage, 'planning');
});

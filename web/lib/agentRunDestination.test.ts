import assert from 'node:assert/strict';
import test from 'node:test';
import type { AgentRun } from './api/agentRuns';
import { getAgentRunDestination } from './agentRunDestination.ts';

function run(task_type: AgentRun['task_type'], extra: Partial<AgentRun> = {}): AgentRun {
    return {
        run_id: 'r1', agent_name: 'a', agent_version: '1', task_type, title: 't', status: 'succeeded', stage: 'done',
        plan: [], attempts: 1, max_attempts: 1, can_retry: false, can_cancel: false,
        created_at: '2026-08-04', updated_at: '2026-08-04', ...extra,
    };
}

test('maps interview report and session runs to their persisted session', () => {
    assert.deepEqual(getAgentRunDestination(run('interview_report', { session_id: 's1' })), { kind: 'interview-report', sessionId: 's1' });
    assert.deepEqual(getAgentRunDestination(run('interview_turn', { session_id: 's1' })), { kind: 'interview-session', sessionId: 's1' });
});

test('maps generated resume and waiting generation session without guessing', () => {
    assert.deepEqual(getAgentRunDestination(run('resume_generation', { result: { generated_resume_id: 7 } })), { kind: 'generated-resume', resumeId: 7 });
    assert.deepEqual(getAgentRunDestination(run('resume_generation', { result: { generation_session_id: 'g1' } })), { kind: 'resume-workspace', generationSessionId: 'g1' });
});

test('maps a persisted ability-profile run to the growth record', () => {
    assert.deepEqual(getAgentRunDestination(run('ability_profile')), { kind: 'growth-record' });
});

test('maps explicit job ids and hides invalid object references', () => {
    assert.deepEqual(getAgentRunDestination(run('job_assets', { result: { job_id: 3 } })), { kind: 'job', jobId: 3 });
    assert.equal(getAgentRunDestination(run('job_assets', { result: { job_id: 'not-an-id' } })), null);
    assert.equal(getAgentRunDestination(run('interview_report')), null);
});

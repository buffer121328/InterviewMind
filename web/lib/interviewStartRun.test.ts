import assert from 'node:assert/strict';
import test from 'node:test';

import { waitForInterviewStartRun } from './interviewStartRun.ts';

test('interview start run returns an inline succeeded result without polling', async () => {
    let polls = 0;
    const result = await waitForInterviewStartRun(
        { status: 'succeeded', result: { first_question: '请介绍你的项目。' } },
        async () => {
            polls += 1;
            return { status: 'failed' };
        },
    );

    assert.equal(result.first_question, '请介绍你的项目。');
    assert.equal(polls, 0);
});

test('interview start run polls queued work until the persisted result succeeds', async () => {
    const updates: string[] = [];
    const states = [
        { run_id: 'run-1', status: 'running' as const, stage: 'generating_question' },
        { run_id: 'run-1', status: 'succeeded' as const, result: { first_question: '第二轮第一题' } },
    ];

    const result = await waitForInterviewStartRun(
        { run_id: 'run-1', status: 'queued' },
        async () => states.shift()!,
        {
            intervalMs: 0,
            onProgress: (run) => updates.push(run.stage || run.status || ''),
        },
    );

    assert.equal(result.first_question, '第二轮第一题');
    assert.deepEqual(updates, ['generating_question', 'succeeded']);
});

test('interview start run surfaces the backend terminal error instead of polling forever', async () => {
    await assert.rejects(
        waitForInterviewStartRun(
            { run_id: 'run-1', status: 'failed', error_message: '模型规划超时' },
            async () => ({ status: 'succeeded' }),
            { intervalMs: 0 },
        ),
        /模型规划超时/,
    );
});

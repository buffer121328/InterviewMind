import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldPromptForInterviewSatisfaction } from './interview/satisfactionPrompt.ts';
import type { InterviewSession } from '../store/types.ts';

function session(
    sessionId: string,
    mode: 'mock' | 'voice',
    status: 'active' | 'completed' | 'archived',
): Pick<InterviewSession, 'session_id' | 'metadata'> {
    return {
        session_id: sessionId,
        metadata: {
            mode,
            status,
            question_count: 5,
            max_questions: 5,
        },
    };
}

test('已完成的文字和语音面试轮次均有资格展示满意度问卷', () => {
    assert.equal(shouldPromptForInterviewSatisfaction(session('round-1', 'mock', 'completed'), false), true);
    assert.equal(shouldPromptForInterviewSatisfaction(session('round-2', 'voice', 'completed'), false), true);
    assert.equal(shouldPromptForInterviewSatisfaction(session('active-round', 'mock', 'active'), false), false);
    assert.equal(shouldPromptForInterviewSatisfaction(session('archived-round', 'voice', 'archived'), false), false);
});

test('关闭第一轮问卷只阻止该轮，后续轮次仍会单独询问', () => {
    const firstRound = session('round-1', 'mock', 'completed');
    const secondRound = session('round-2', 'mock', 'completed');

    // “已询问”代表用户关闭或提交了第一轮的弹窗。
    assert.equal(shouldPromptForInterviewSatisfaction(firstRound, true), false);
    assert.equal(shouldPromptForInterviewSatisfaction(secondRound, false), true);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    questionAnswerPoints,
    questionFollowupAnswerPoints,
    questionSourceLabel,
} from './questionBankPresentation.ts';

test('question answers display persisted answer points', () => {
    assert.equal(questionSourceLabel({ origin_session_id: 'session-1', source_type: 'generated' }), '模拟面试');
    assert.deepEqual(
        questionAnswerPoints({ reference_answer: '1. 说明核心原理\n- 补充项目证据' }),
        ['说明核心原理', '补充项目证据'],
    );
    assert.deepEqual(questionAnswerPoints({ reference_answer: undefined }), []);
});

test('follow-up answers display persisted answer points', () => {
    assert.deepEqual(
        questionFollowupAnswerPoints({ reference_answer: '澄清约束\n说明取舍' }),
        ['澄清约束', '说明取舍'],
    );
    assert.deepEqual(questionFollowupAnswerPoints({ reference_answer: undefined }), []);
});

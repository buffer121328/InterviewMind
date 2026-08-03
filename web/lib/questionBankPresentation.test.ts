import assert from 'node:assert/strict';
import test from 'node:test';

import {
    questionAnswerPoints,
    questionFollowupAnswerPoints,
    questionSourceLabel,
} from './questionBankPresentation.ts';

test('question answers stay empty even when persisted content exists', () => {
    assert.equal(questionSourceLabel({ origin_session_id: 'session-1', source_type: 'generated' }), '模拟面试');
    assert.deepEqual(questionAnswerPoints({ reference_answer: '候选人的完整原始作答' }), []);
    assert.deepEqual(questionAnswerPoints({ reference_answer: undefined }), []);
});

test('follow-up answers stay empty even when persisted content exists', () => {
    assert.deepEqual(questionFollowupAnswerPoints({ reference_answer: '追问的完整原始作答' }), []);
    assert.deepEqual(questionFollowupAnswerPoints({ reference_answer: undefined }), []);
});

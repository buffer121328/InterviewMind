import assert from 'node:assert/strict';
import test from 'node:test';

import {
    questionAnswerPoints,
    questionFollowupAnswerPoints,
    questionSourceLabel,
} from './questionBankPresentation.ts';

test('interview-origin questions show their source and never present hints as answer points', () => {
    const question = {
        origin_session_id: 'session-1',
        source_type: 'generated',
        reference_answer: '旧版提示内容',
    };

    assert.equal(questionSourceLabel(question), '模拟面试');
    assert.deepEqual(questionAnswerPoints(question), []);
});

test('manual and imported questions split stored answers into review points', () => {
    assert.equal(questionSourceLabel({ source_type: 'manual' }), '手动添加');
    assert.equal(questionSourceLabel({ source_type: 'experience' }), '面经采集');
    assert.deepEqual(
        questionAnswerPoints({
            source_type: 'manual',
            reference_answer: `1. 先说明适用场景。\n- 再解释核心机制；最后补充取舍。`,
        }),
        ['先说明适用场景。', '再解释核心机制；', '最后补充取舍。'],
    );
});

test('question and follow-up answer points are empty when no usable answer exists', () => {
    assert.deepEqual(questionAnswerPoints({ source_type: 'manual', reference_answer: '   ' }), []);
    assert.deepEqual(questionFollowupAnswerPoints({ reference_answer: undefined }), []);
});

test('follow-up answers use the same point presentation without hiding persisted content', () => {
    assert.deepEqual(
        questionFollowupAnswerPoints({ reference_answer: '说明触发条件。说明失败兜底！' }),
        ['说明触发条件。', '说明失败兜底！'],
    );
});

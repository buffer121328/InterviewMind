import assert from 'node:assert/strict';
import test from 'node:test';

import { questionReferenceAnswer, questionSourceLabel } from './questionBankPresentation.ts';

test('interview-origin questions show their source and never present hints as reference answers', () => {
    const question = {
        origin_session_id: 'session-1',
        source_type: 'generated',
        reference_answer: '旧版提示内容',
    };

    assert.equal(questionSourceLabel(question), '模拟面试');
    assert.equal(questionReferenceAnswer(question), '暂无');
});

test('manual and imported questions retain their real source and answer', () => {
    assert.equal(questionSourceLabel({ source_type: 'manual' }), '手动添加');
    assert.equal(questionSourceLabel({ source_type: 'experience' }), '面经采集');
    assert.equal(
        questionReferenceAnswer({ source_type: 'manual', reference_answer: '真实参考答案' }),
        '真实参考答案',
    );
});

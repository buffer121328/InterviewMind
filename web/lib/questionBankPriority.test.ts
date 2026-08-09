import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { priorityLabel, toQuestionBankForm } from './questionBankPriority.ts';

describe('question bank priority presentation', () => {
    it('maps persisted priorities to Chinese labels', () => {
        assert.equal(priorityLabel('required'), '必选');
        assert.equal(priorityLabel('high'), '高');
        assert.equal(priorityLabel('low'), '低');
    });

    it('keeps priority when converting an item into an edit form', () => {
        const form = toQuestionBankForm({
            id: 1,
            user_id: 'owner-1',
            source_type: 'manual',
            question_text: '解释事件循环',
            reference_answer: '说明任务队列',
            tags: ['JavaScript'],
            difficulty: 'medium',
            target_skill: 'JavaScript',
            question_type: 'tech',
            priority: 'required',
            is_verified: false,
            usage_count: 0,
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
            followups: [],
        });

        assert.equal(form.priority, 'required');
        assert.equal(form.reference_answer, '说明任务队列');
    });
});

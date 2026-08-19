import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldSubmitInterviewAnswer } from './interviewAnswerSubmission.ts';

test('only Ctrl+Enter submits a text interview answer', () => {
    assert.equal(shouldSubmitInterviewAnswer({ key: 'Enter', ctrlKey: true }), true);
    assert.equal(shouldSubmitInterviewAnswer({ key: 'Enter', ctrlKey: false }), false);
    assert.equal(shouldSubmitInterviewAnswer({ key: 'Enter', ctrlKey: false, isComposing: false }), false);
    assert.equal(shouldSubmitInterviewAnswer({ key: 'a', ctrlKey: true }), false);
});

test('Ctrl+Enter does not submit while an IME composition is active', () => {
    assert.equal(shouldSubmitInterviewAnswer({ key: 'Enter', ctrlKey: true, isComposing: true }), false);
});

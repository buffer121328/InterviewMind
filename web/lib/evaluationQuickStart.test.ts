import assert from 'node:assert/strict';
import test from 'node:test';

import {
    parseEvaluationPromptCandidate,
    promptCandidateMatches,
} from './evaluationQuickStart.ts';

test('prompt candidate parser keeps only the evaluation handoff fields', () => {
    assert.deepEqual(
        parseEvaluationPromptCandidate(JSON.stringify({
            name: 'interview.planner',
            version: 3,
            compareProduction: true,
            api_key: 'must-not-propagate',
        })),
        {
            name: 'interview.planner',
            version: '3',
            compareProduction: true,
        },
    );
});

test('invalid prompt candidates fall back to built-in Agent defaults', () => {
    assert.equal(parseEvaluationPromptCandidate('{invalid'), null);
    assert.equal(parseEvaluationPromptCandidate(JSON.stringify({ name: 'resume.analysis' })), null);
    assert.equal(promptCandidateMatches(null, 'resume.analysis'), false);
    assert.equal(
        promptCandidateMatches(
            { name: 'resume.analysis', version: '2', compareProduction: false },
            'resume.analysis',
        ),
        true,
    );
});

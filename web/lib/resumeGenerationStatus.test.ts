import assert from 'node:assert/strict';
import test from 'node:test';

import { unwrapGenerationSessionStatus } from './resumeGenerationStatus.ts';

test('unwrapGenerationSessionStatus reads the persisted progress data envelope', () => {
    const status = unwrapGenerationSessionStatus({
        success: true,
        data: {
            session_id: 'generation-1',
            status: 'running',
            questions: [],
            user_answers: {},
            progress_steps: [
                { id: 'requirements_analysis', status: 'completed' },
                { id: 'draft_generation', status: 'running' },
            ],
        },
    });

    assert.equal(status?.session_id, 'generation-1');
    assert.equal(status?.progress_steps?.[1]?.status, 'running');
});

test('unwrapGenerationSessionStatus rejects failed envelopes and accepts legacy direct responses', () => {
    assert.equal(unwrapGenerationSessionStatus({ success: false, data: {} }), null);
    assert.equal(unwrapGenerationSessionStatus({
        session_id: 'legacy-generation',
        status: 'completed',
        questions: [],
        user_answers: {},
    })?.status, 'completed');
});

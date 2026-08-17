import assert from 'node:assert/strict';
import test from 'node:test';

import {
    JOB_DESCRIPTION_PREVIEW_CHARACTER_LIMIT,
    getJobDescriptionBlocks,
    shouldOfferJobDescriptionExpansion,
} from './bossJobDescriptionPresentation.ts';

test('offers expansion only when a job description exceeds the preview range', () => {
    assert.equal(shouldOfferJobDescriptionExpansion('职责清晰且简短'), false);
    assert.equal(
        shouldOfferJobDescriptionExpansion('a'.repeat(JOB_DESCRIPTION_PREVIEW_CHARACTER_LIMIT)),
        false,
    );
    assert.equal(
        shouldOfferJobDescriptionExpansion('a'.repeat(JOB_DESCRIPTION_PREVIEW_CHARACTER_LIMIT + 1)),
        true,
    );
});

test('preserves JD paragraph order while making common numbered requirements into a list', () => {
    assert.deepEqual(
        getJobDescriptionBlocks('岗位职责：\n1. 负责服务开发\n2. 参与系统设计\n\n任职要求：\n- 熟悉 Python\n- 熟悉 SQL'),
        [
            { kind: 'paragraph', text: '岗位职责：' },
            { kind: 'list', items: ['负责服务开发', '参与系统设计'] },
            { kind: 'paragraph', text: '任职要求：' },
            { kind: 'list', items: ['熟悉 Python', '熟悉 SQL'] },
        ],
    );
});

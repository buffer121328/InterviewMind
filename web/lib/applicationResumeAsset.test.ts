import assert from 'node:assert/strict';
import test from 'node:test';

import { buildResumeMarkdownDownload } from './applicationResumeAsset.ts';

test('builds a safe markdown download from the persisted linked asset', () => {
    const result = buildResumeMarkdownDownload({
        id: 7,
        title: 'Agent / 工程师: v2',
        content: '# Resume',
        job_description: 'Agent',
        created_at: '2026-08-04T10:00:00',
    });
    assert.equal(result.filename, 'Agent-工程师-v2.md');
    assert.equal(result.content, '# Resume');
});

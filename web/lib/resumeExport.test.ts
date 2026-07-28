import assert from 'node:assert/strict';
import test from 'node:test';

import { buildStandaloneResumeHtml, RESUME_SHEET_STYLES } from './resumeExport.ts';

test('buildStandaloneResumeHtml preserves the exact preview sheet and print colors', () => {
    const sheet = '<main class="resume-preview-sheet"><article class="resume-preview-content"><h1>郭成</h1></article></main>';
    const html = buildStandaloneResumeHtml('郭成 <AI>', sheet);

    assert.match(html, /<title>郭成 &lt;AI&gt;<\/title>/);
    assert.match(html, /class="resume-preview-sheet"/);
    assert.match(html, /print-color-adjust: exact/);
    assert.match(html, /@page \{ size: A4; margin: 0; \}/);
    assert.match(html, /min-height: 0; margin: 0; padding-bottom: 8mm/);
    assert.doesNotMatch(html, /导出时间/);
});

test('canonical resume sheet styles cover photo and page-safe section hierarchy', () => {
    assert.match(RESUME_SHEET_STYLES, /\.resume-preview-photo img/);
    assert.match(RESUME_SHEET_STYLES, /break-after: avoid-page/);
    assert.match(RESUME_SHEET_STYLES, /linear-gradient/);
});

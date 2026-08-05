import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('BOSS cards and detail do not present historical custom resumes or generation status', () => {
    const resultCard = readFileSync(new URL('../components/boss/BossResultCard.tsx', import.meta.url), 'utf8');
    const detailDialog = readFileSync(new URL('../components/boss/BossJobDetailDialog.tsx', import.meta.url), 'utf8');
    const productSource = `${resultCard}\n${detailDialog}`;

    assert.doesNotMatch(productSource, /custom_resume_id|custom_resume_preview|定制简历\s*#/);
    assert.doesNotMatch(productSource, /asset_status|资产正在后台生成|资产生成失败/);
});

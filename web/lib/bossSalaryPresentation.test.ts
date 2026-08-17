import assert from 'node:assert/strict';
import test from 'node:test';

import { displayBossSalaryText } from './bossSalaryPresentation.ts';

test('keeps a normal BOSS salary text visible', () => {
    assert.equal(displayBossSalaryText('20-35K·14薪'), '20-35K·14薪');
});

test('replaces block-like and private-use salary obfuscation with a confirmation label', () => {
    assert.equal(displayBossSalaryText('██-████K'), '薪资请在 BOSS 原页面确认');
    assert.equal(displayBossSalaryText('\uE101-\uE102K'), '薪资请在 BOSS 原页面确认');
});

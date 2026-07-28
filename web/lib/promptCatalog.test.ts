import assert from 'node:assert/strict';
import test from 'node:test';
import { getPromptDisplayName, getPromptFunctionalGroup } from './promptCatalog.ts';

test('prompt catalog translates backend names to Chinese display names', () => {
    assert.equal(getPromptDisplayName('analysis.aggregate_profile'), '跨场综合画像');
    assert.equal(getPromptFunctionalGroup('analysis.aggregate_profile'), '能力分析');
});

test('prompt catalog keeps unknown custom names usable', () => {
    assert.equal(getPromptDisplayName('custom.prompt'), 'custom.prompt');
    assert.equal(getPromptFunctionalGroup('custom.prompt'), '自定义 Prompt');
});

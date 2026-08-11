import assert from 'node:assert/strict';
import test from 'node:test';
import { RUN_CENTER_TABS } from './runCenterTabs.ts';

test('puts local model performance overview after degradations', () => {
    assert.deepEqual(RUN_CENTER_TABS.map(tab => tab.id), ['runs', 'models', 'degradations', 'overview']);
    assert.match(RUN_CENTER_TABS.at(-1)?.label || '', /本地模型/);
});

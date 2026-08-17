import assert from 'node:assert/strict';
import test from 'node:test';
import { RUN_CENTER_TABS } from './runCenterTabs.ts';

test('puts performance overview after degradations', () => {
    assert.deepEqual(RUN_CENTER_TABS.map(tab => tab.id), ['runs', 'models', 'degradations', 'overview']);
    assert.equal(RUN_CENTER_TABS.at(-1)?.label, '性能总览');
});

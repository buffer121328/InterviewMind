import assert from 'node:assert/strict';
import test from 'node:test';
import { formatAgentRunFirstTokenDuration } from './agentRunPresentation.ts';

test('formats task first-token latency without fabricating historical values', () => {
    assert.equal(formatAgentRunFirstTokenDuration(null), '暂无数据');
    assert.equal(formatAgentRunFirstTokenDuration(undefined), '暂无数据');
    assert.equal(formatAgentRunFirstTokenDuration(275), '275ms');
    assert.equal(formatAgentRunFirstTokenDuration(1250), '1.3s');
});

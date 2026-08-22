import assert from 'node:assert/strict';
import test from 'node:test';

import { formatChinaDateTime, formatChinaTime, parsePersistedTimestamp } from './chinaTime.ts';

test('legacy UTC-naive timestamps display in China Standard Time', () => {
    assert.equal(parsePersistedTimestamp('2026-08-21T03:58:07')?.toISOString(), '2026-08-21T03:58:07.000Z');
    assert.match(formatChinaDateTime('2026-08-21T03:58:07'), /2026\/08\/21\s*11:58/);
    assert.match(formatChinaTime('2026-08-21T03:58:07Z'), /11:58/);
});

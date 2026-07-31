import assert from 'node:assert/strict';
import test from 'node:test';

import { DEFAULT_PAGE_SIZE, getTotalPages } from './pagination.ts';

test('management pagination defaults to ten records per page', () => {
    assert.equal(DEFAULT_PAGE_SIZE, 10);
    assert.equal(getTotalPages(0), 1);
    assert.equal(getTotalPages(10), 1);
    assert.equal(getTotalPages(11), 2);
});

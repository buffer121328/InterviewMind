import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldOpenSessionDeleteConfirmation } from './sessionDeleteInteraction.ts';

test('only a right-click opens the session deletion confirmation', () => {
    assert.equal(shouldOpenSessionDeleteConfirmation(2), true);
    assert.equal(shouldOpenSessionDeleteConfirmation(0), false);
    assert.equal(shouldOpenSessionDeleteConfirmation(1), false);
});

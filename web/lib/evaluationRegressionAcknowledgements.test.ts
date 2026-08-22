import assert from 'node:assert/strict';
import test from 'node:test';

import {
    loadAcknowledgedRegressionIds,
    saveAcknowledgedRegressionIds,
} from './evaluationRegressionAcknowledgements.ts';

function storage(initial: string | null = null) {
    let value = initial;
    return {
        getItem: () => value,
        setItem: (_key: string, next: string) => { value = next; },
    };
}

test('regression acknowledgement IDs survive refresh through bounded storage', () => {
    const target = storage();
    saveAcknowledgedRegressionIds(['run-1', 'run-2'], target);
    assert.deepEqual([...loadAcknowledgedRegressionIds(target)], ['run-1', 'run-2']);
});

test('malformed regression acknowledgement storage fails open', () => {
    assert.deepEqual([...loadAcknowledgedRegressionIds(storage('{bad'))], []);
    assert.deepEqual([...loadAcknowledgedRegressionIds(storage('{"run":"not-an-array"}'))], []);
});

test('regression acknowledgement storage keeps only bounded valid IDs', () => {
    const target = storage();
    saveAcknowledgedRegressionIds(['', 'run-1', 'x'.repeat(201), ...Array.from({ length: 510 }, (_, index) => `run-${index + 2}`)], target);
    const ids = [...loadAcknowledgedRegressionIds(target)];
    assert.equal(ids.length, 500);
    assert.equal(ids[0], 'run-12');
    assert.equal(ids.at(-1), 'run-511');
});


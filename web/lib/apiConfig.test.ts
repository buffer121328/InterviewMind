import assert from 'node:assert/strict';
import test from 'node:test';

import { normalizeApiBaseUrl } from './api/config.ts';

test('normalizeApiBaseUrl prevents duplicated /api prefixes', () => {
    assert.equal(normalizeApiBaseUrl('/api'), '');
    assert.equal(normalizeApiBaseUrl('/api/'), '');
    assert.equal(normalizeApiBaseUrl('https://example.test/api'), 'https://example.test');
    assert.equal(normalizeApiBaseUrl('https://example.test/api/'), 'https://example.test');
});

test('normalizeApiBaseUrl keeps plain backend origins unchanged', () => {
    assert.equal(normalizeApiBaseUrl(undefined), 'http://localhost:8000');
    assert.equal(normalizeApiBaseUrl('http://localhost:8000'), 'http://localhost:8000');
});

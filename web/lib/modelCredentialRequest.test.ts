import assert from 'node:assert/strict';
import test from 'node:test';

import { modelConfigForRequest, modelPoolConfigForRequest, optionalModelConfigForRequest } from './modelCredentialRequest.ts';

test('business model config uses technical model name and never sends plaintext key', () => {
    const payload = modelConfigForRequest({
        id: 'legacy-ui-uuid',
        name: 'Example',
        provider: 'openai',
        integration: 'openai_compatible',
        apiKey: 'must-never-be-sent',
        baseUrl: 'https://example.test/v1',
        model: 'example-model',
        dimensions: 1024,
    });

    assert.equal(payload.credential_id, 'example-model');
    assert.equal(payload.legacy_credential_id, 'legacy-ui-uuid');
    assert.equal(payload.name, 'Example');
    assert.equal(payload.dimensions, 1024);
    assert.equal(payload.integration, 'openai_compatible');
    assert.equal('api_key' in payload, false);
    assert.equal(JSON.stringify(payload).includes('must-never-be-sent'), false);
});


test('unassigned expert model remains null so backend can fall back to General', () => {
    assert.equal(optionalModelConfigForRequest(null), null);
});


test('empty pools retain the corresponding Smart/Fast single-model fallback', () => {
    const smart = {
        id: 'smart-id',
        name: 'Smart',
        provider: 'openai',
        apiKey: '',
        baseUrl: 'https://example.test/v1',
        model: 'smart-model',
    };
    const fast = { ...smart, id: 'fast-id', name: 'Fast', model: 'fast-model' };

    assert.equal(modelPoolConfigForRequest([], smart)[0].model, 'smart-model');
    assert.equal(modelPoolConfigForRequest([], fast)[0].model, 'fast-model');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { modelConfigForRequest } from './modelCredentialRequest.ts';

test('business model config sends a credential reference and never the plaintext key', () => {
    const payload = modelConfigForRequest({
        id: 'model-1',
        provider: 'openai',
        apiKey: 'must-never-be-sent',
        baseUrl: 'https://example.test/v1',
        model: 'example-model',
    });

    assert.equal(payload.credential_id, 'model-1');
    assert.equal('api_key' in payload, false);
    assert.equal(JSON.stringify(payload).includes('must-never-be-sent'), false);
});

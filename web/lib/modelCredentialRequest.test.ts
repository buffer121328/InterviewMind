import assert from 'node:assert/strict';
import test from 'node:test';

import { modelConfigForRequest } from './modelCredentialRequest.ts';

test('business model config uses technical model name and never sends plaintext key', () => {
    const payload = modelConfigForRequest({
        id: 'legacy-ui-uuid',
        name: 'Example',
        provider: 'openai',
        apiKey: 'must-never-be-sent',
        baseUrl: 'https://example.test/v1',
        model: 'example-model',
    });

    assert.equal(payload.credential_id, 'example-model');
    assert.equal(payload.legacy_credential_id, 'legacy-ui-uuid');
    assert.equal(payload.name, 'Example');
    assert.equal('api_key' in payload, false);
    assert.equal(JSON.stringify(payload).includes('must-never-be-sent'), false);
});

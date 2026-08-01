import assert from 'node:assert/strict';
import test from 'node:test';

import {
    apiConfigForPersistence,
    createCredentialSafeStorage,
    rehydrateApiConfig,
    sanitizeInterviewStoreStorageValue,
} from '../store/apiConfigPersistence.ts';
import type { ApiConfig } from '../store/types.ts';

const DEFAULT_API_CONFIG: ApiConfig = {
    models: [],
    smartModelId: '',
    fastModelId: '',
    reasoningPoolModelIds: [],
    fastPoolModelIds: [],
    generalModelId: '',
    matchAnalystModelId: '',
    contentWriterModelId: '',
    hrReviewerModelId: '',
    reflectorModelId: '',
    mimoModelId: '',
    ragEmbeddingModelId: '',
    mem0LlmModelId: '',
    mem0EmbedderModelId: '',
};

const apiConfig: ApiConfig = {
    ...DEFAULT_API_CONFIG,
    models: [
        {
            id: 'model-1',
            name: 'Primary',
            provider: 'openai',
            kind: 'chat',
            apiKey: 'plaintext-secret-key',
            credentialStored: true,
            credentialExpiresAt: '2026-08-31T00:00:00.000Z',
            baseUrl: 'https://example.test/v1',
            model: 'model-a',
            createdAt: '2026-08-01T00:00:00.000Z',
        },
    ],
    smartModelId: 'model-1',
    fastModelId: 'model-1',
};

test('persistent API config retains routing but omits plaintext API keys', () => {
    const persisted = apiConfigForPersistence(apiConfig);

    assert.equal(persisted.smartModelId, 'model-1');
    assert.equal(persisted.models[0].model, 'model-a');
    assert.equal('apiKey' in persisted.models[0], false);
    assert.equal(JSON.stringify(persisted).includes('plaintext-secret-key'), false);
});

test('legacy interview-store values are sanitized before rehydration', () => {
    const legacy = JSON.stringify({ state: { apiConfig }, version: 0 });
    const sanitized = sanitizeInterviewStoreStorageValue(legacy);

    assert.equal(sanitized.includes('plaintext-secret-key'), false);
    assert.equal(JSON.parse(sanitized).state.apiConfig.models[0].model, 'model-a');
});

test('credential-safe storage rewrites legacy localStorage values on read', () => {
    const values = new Map<string, string>([
        ['interview-store', JSON.stringify({ state: { apiConfig }, version: 0 })],
    ]);
    const safeStorage = createCredentialSafeStorage({
        getItem: name => values.get(name) ?? null,
        setItem: (name, value) => { values.set(name, value); },
        removeItem: name => { values.delete(name); },
    });

    const loaded = safeStorage.getItem('interview-store');

    assert.ok(loaded);
    assert.equal(loaded.includes('plaintext-secret-key'), false);
    assert.equal(values.get('interview-store')?.includes('plaintext-secret-key'), false);
});

test('malformed persisted payloads are reset instead of retaining unknown secrets', () => {
    const sanitized = sanitizeInterviewStoreStorageValue('{"apiKey":"plaintext-secret-key"');

    assert.equal(sanitized.includes('plaintext-secret-key'), false);
    assert.deepEqual(JSON.parse(sanitized).state, {});
});

test('rehydration restores non-sensitive settings with empty in-memory keys', () => {
    const hydrated = rehydrateApiConfig(apiConfigForPersistence(apiConfig), DEFAULT_API_CONFIG);

    assert.equal(hydrated.models[0].apiKey, '');
    assert.equal(hydrated.models[0].credentialStored, true);
    assert.equal(hydrated.models[0].baseUrl, 'https://example.test/v1');
    assert.equal(hydrated.smartModelId, 'model-1');
});

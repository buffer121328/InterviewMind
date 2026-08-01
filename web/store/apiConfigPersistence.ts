import type { ApiConfig, ModelConfig } from './types';

export const INTERVIEW_STORE_PERSIST_VERSION = 4;

export type PersistedModelConfig = Omit<ModelConfig, 'apiKey'>;
export type PersistedApiConfig = Omit<ApiConfig, 'models'> & {
    models: PersistedModelConfig[];
};

interface StringStorage {
    getItem: (name: string) => string | null;
    setItem: (name: string, value: string) => void;
    removeItem: (name: string) => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined;
}

function requiredString(value: unknown): string | null {
    return typeof value === 'string' ? value : null;
}

function stringArray(value: unknown, fallback: string[]): string[] {
    return Array.isArray(value) && value.every(item => typeof item === 'string')
        ? [...value]
        : [...fallback];
}

/** Converts model configuration into a persistent representation that never contains API keys. */
export function apiConfigForPersistence(apiConfig: ApiConfig): PersistedApiConfig {
    return {
        ...apiConfig,
        models: apiConfig.models.map(model => {
            const safeModel = { ...model } as Partial<ModelConfig>;
            delete safeModel.apiKey;
            return safeModel as PersistedModelConfig;
        }),
    };
}

function stripModelApiKeys(apiConfigValue: unknown): unknown {
    if (!isRecord(apiConfigValue) || !Array.isArray(apiConfigValue.models)) return apiConfigValue;
    return {
        ...apiConfigValue,
        models: apiConfigValue.models.map(model => {
            if (!isRecord(model)) return model;
            const safeModel = { ...model };
            delete safeModel.apiKey;
            return safeModel;
        }),
    };
}

/** Removes plaintext model keys from either a Zustand state object or its serialized storage envelope. */
export function stripApiKeysFromPersistedState(value: unknown): unknown {
    if (!isRecord(value)) return value;
    if (isRecord(value.state)) {
        return {
            ...value,
            state: {
                ...value.state,
                apiConfig: stripModelApiKeys(value.state.apiConfig),
            },
        };
    }
    return {
        ...value,
        apiConfig: stripModelApiKeys(value.apiConfig),
    };
}

/** Sanitizes a raw localStorage value and resets malformed payloads instead of retaining unknown secrets. */
export function sanitizeInterviewStoreStorageValue(value: string): string {
    try {
        return JSON.stringify(stripApiKeysFromPersistedState(JSON.parse(value)));
    } catch {
        return JSON.stringify({ state: {}, version: INTERVIEW_STORE_PERSIST_VERSION });
    }
}

/** Permanently guards localStorage reads/writes, including stale clients and manually modified payloads. */
export function createCredentialSafeStorage(storage: StringStorage): StringStorage {
    return {
        getItem(name) {
            const storedValue = storage.getItem(name);
            if (storedValue === null) return null;
            const safeValue = sanitizeInterviewStoreStorageValue(storedValue);
            if (safeValue !== storedValue) storage.setItem(name, safeValue);
            return safeValue;
        },
        setItem(name, value) {
            storage.setItem(name, sanitizeInterviewStoreStorageValue(value));
        },
        removeItem(name) {
            storage.removeItem(name);
        },
    };
}

function hydrateModel(value: unknown): ModelConfig | null {
    if (!isRecord(value)) return null;
    const id = requiredString(value.id);
    const name = requiredString(value.name);
    const provider = requiredString(value.provider);
    const baseUrl = requiredString(value.baseUrl);
    const model = requiredString(value.model);
    const createdAt = requiredString(value.createdAt);
    if ([id, name, provider, baseUrl, model, createdAt].some(item => item === null)) return null;
    const kind = value.kind === 'chat' || value.kind === 'embedding' || value.kind === 'voice'
        ? value.kind
        : undefined;
    return {
        id: id as string,
        name: name as string,
        provider: provider as string,
        kind,
        apiKey: '',
        credentialStored: value.credentialStored === true,
        credentialExpiresAt: optionalString(value.credentialExpiresAt),
        baseUrl: baseUrl as string,
        model: model as string,
        pricingKey: optionalString(value.pricingKey),
        integration: optionalString(value.integration),
        createdAt: createdAt as string,
    };
}

/** Rehydrates non-sensitive model settings while intentionally initializing every API key as empty memory state. */
export function rehydrateApiConfig(value: unknown, fallback: ApiConfig): ApiConfig {
    if (!isRecord(value)) return fallback;
    const models = Array.isArray(value.models)
        ? value.models.map(hydrateModel).filter((model): model is ModelConfig => model !== null)
        : [];
    const readId = (key: keyof ApiConfig): string => optionalString(value[key]) ?? fallback[key] as string;
    return {
        models,
        smartModelId: readId('smartModelId'),
        fastModelId: readId('fastModelId'),
        reasoningPoolModelIds: stringArray(value.reasoningPoolModelIds, fallback.reasoningPoolModelIds),
        fastPoolModelIds: stringArray(value.fastPoolModelIds, fallback.fastPoolModelIds),
        generalModelId: readId('generalModelId'),
        matchAnalystModelId: readId('matchAnalystModelId'),
        contentWriterModelId: readId('contentWriterModelId'),
        hrReviewerModelId: readId('hrReviewerModelId'),
        reflectorModelId: readId('reflectorModelId'),
        mimoModelId: readId('mimoModelId'),
        ragEmbeddingModelId: readId('ragEmbeddingModelId'),
        mem0LlmModelId: readId('mem0LlmModelId'),
        mem0EmbedderModelId: readId('mem0EmbedderModelId'),
    };
}

/** Pure request serializer for model-name Redis credential references. */

interface ModelCredentialReferenceSource {
    id: string;
    name: string;
    baseUrl: string;
    model: string;
    provider: string;
    integration?: string;
    pricingKey?: string;
    apiKey?: string;
}

export interface ModelCredentialRequestConfig {
    credential_id: string;
    legacy_credential_id: string;
    name: string;
    base_url: string;
    model: string;
    provider?: string;
    integration?: string;
    pricing_key?: string;
}

/** Uses the technical model name as the Redis reference; the UUID is migration-only. */
export function modelConfigForRequest(model: ModelCredentialReferenceSource): ModelCredentialRequestConfig {
    return {
        credential_id: model.model,
        legacy_credential_id: model.id,
        name: model.name,
        base_url: model.baseUrl,
        model: model.model,
        provider: model.provider,
        integration: model.integration,
        pricing_key: model.pricingKey || model.model,
    };
}

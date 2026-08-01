/** Pure request serializer for Redis-backed model credential references. */

interface ModelCredentialReferenceSource {
    id: string;
    baseUrl: string;
    model: string;
    provider: string;
    integration?: string;
    pricingKey?: string;
    apiKey?: string;
}

export interface ModelCredentialRequestConfig {
    credential_id: string;
    base_url: string;
    model: string;
    provider?: string;
    integration?: string;
    pricing_key?: string;
}

/** Serializes one model as a credential reference; plaintext keys never enter business payloads. */
export function modelConfigForRequest(model: ModelCredentialReferenceSource): ModelCredentialRequestConfig {
    return {
        credential_id: model.id,
        base_url: model.baseUrl,
        model: model.model,
        provider: model.provider,
        integration: model.integration,
        pricing_key: model.pricingKey || model.model,
    };
}

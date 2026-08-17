/** Pure request serializer for model-name Redis credential references. */

interface ModelCredentialReferenceSource {
    id: string;
    name: string;
    baseUrl: string;
    model: string;
    provider: string;
    integration?: string;
    pricingKey?: string;
    dimensions?: number;
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
    dimensions?: number;
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
        dimensions: model.dimensions,
    };
}

/** Serializes optional role-specific assignments without silently substituting the Smart model. */
export function optionalModelConfigForRequest(
    model: ModelCredentialReferenceSource | null,
): ModelCredentialRequestConfig | null {
    return model ? modelConfigForRequest(model) : null;
}


/** Serializes a pool while preserving its single-core-model compatibility fallback. */
export function modelPoolConfigForRequest(
    models: ModelCredentialReferenceSource[],
    fallback: ModelCredentialReferenceSource,
): Array<ModelCredentialRequestConfig & { name: string; weight: number }> {
    const members = models.length > 0 ? models : [fallback];
    return members.map(model => ({
        ...modelConfigForRequest(model),
        name: model.name,
        weight: 1,
    }));
}

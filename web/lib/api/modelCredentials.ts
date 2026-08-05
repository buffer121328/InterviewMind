/** API boundary for the minimal local model-name to API-key Redis store. */

import { apiRequest } from './config';

export interface ModelCredentialStatus {
    model_name: string;
    stored: boolean;
    expires_at: string | null;
}

export interface ModelCredentialLookup {
    modelName: string;
    legacyId?: string;
}

/** Saves a new API key or moves an existing key when the technical model name changes. */
export async function saveModelCredential(
    modelName: string,
    options: { apiKey?: string; sourceModel?: string; legacyId?: string },
): Promise<ModelCredentialStatus> {
    return apiRequest<ModelCredentialStatus>('/api/config/credentials', {
        method: 'PUT',
        body: JSON.stringify({
            model_name: modelName,
            api_key: options.apiKey || undefined,
            source_model: options.sourceModel || undefined,
            legacy_id: options.legacyId || undefined,
        }),
    });
}

/** Reads availability by technical model name and supplies old UI IDs only for migration. */
export async function fetchModelCredentialStatuses(models: ModelCredentialLookup[]): Promise<ModelCredentialStatus[]> {
    const response = await apiRequest<{ credentials: ModelCredentialStatus[] }>('/api/config/credentials/status', {
        method: 'POST',
        body: JSON.stringify({
            models: models.map(item => ({ model_name: item.modelName, legacy_id: item.legacyId })),
        }),
    });
    return response.credentials;
}

/** Deletes one model-name String key and any previous UUID Hash. */
export async function deleteModelCredential(modelName: string, legacyId?: string): Promise<void> {
    const params = new URLSearchParams({ model_name: modelName });
    if (legacyId) params.set('legacy_id', legacyId);
    await apiRequest(`/api/config/credentials?${params.toString()}`, { method: 'DELETE' });
}

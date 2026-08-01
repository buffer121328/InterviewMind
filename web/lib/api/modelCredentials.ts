/** API boundary for encrypted Redis-backed model credentials. */

import { apiRequest } from './config';

export interface ModelCredentialStatus {
    model_id: string;
    stored: boolean;
    expires_at: string | null;
}

/** Stores one API key in the backend vault and returns secret-free metadata. */
export async function saveModelCredential(modelId: string, apiKey: string): Promise<ModelCredentialStatus> {
    return apiRequest<ModelCredentialStatus>(`/api/config/credentials/${encodeURIComponent(modelId)}`, {
        method: 'PUT',
        body: JSON.stringify({ api_key: apiKey }),
    });
}

/** Reads availability metadata for known model IDs without retrieving any API key. */
export async function fetchModelCredentialStatuses(modelIds: string[]): Promise<ModelCredentialStatus[]> {
    const response = await apiRequest<{ credentials: ModelCredentialStatus[] }>('/api/config/credentials/status', {
        method: 'POST',
        body: JSON.stringify({ model_ids: modelIds }),
    });
    return response.credentials;
}

/** Deletes one API key from the backend vault. */
export async function deleteModelCredential(modelId: string): Promise<void> {
    await apiRequest(`/api/config/credentials/${encodeURIComponent(modelId)}`, { method: 'DELETE' });
}

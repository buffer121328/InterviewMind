import { buildApiUrl, getUserId } from './config';

export type PromptType = 'text' | 'chat';
export type PromptBody = string | PromptChatMessage[];
export interface PromptChatMessage { role: 'system' | 'developer' | 'user' | 'assistant' | 'tool'; content: string; }
export interface PromptMetadata { name: string; type: PromptType; versions: number[]; labels: string[]; last_updated_at?: string | null; }
export interface PromptListResponse { items: PromptMetadata[]; page: number; limit: number; }
export interface PromptVersion { name: string; type: PromptType; version: number; labels: string[]; prompt: PromptBody; }
export interface PromptPreviewResponse extends PromptVersion { compiled_prompt: PromptBody; unresolved_variables: string[]; }
export interface PromptCreateRequest { name: string; type: PromptType; prompt: PromptBody; labels?: string[]; commit_message?: string; }

export class PromptManagementError extends Error {
    constructor(message: string, public readonly status?: number) { super(message); this.name = 'PromptManagementError'; }
}

/** Calls only owner-scoped prompt routes; templates are persisted and resolved by the backend. */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(buildApiUrl(path), { ...options, headers: { 'Content-Type': 'application/json', 'X-User-ID': getUserId(), ...options?.headers } });
    if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: { message?: string } | string } | null;
        const detail = payload?.detail;
        throw new PromptManagementError(typeof detail === 'object' ? detail?.message || `请求失败（${response.status}）` : detail || `请求失败（${response.status}）`, response.status);
    }
    return response.json() as Promise<T>;
}
/** Loads one bounded page of prompt metadata. */
export function listPrompts(page = 1, limit = 20): Promise<PromptListResponse> { return request(`/api/langfuse/prompts?page=${page}&limit=${limit}`); }
/** Fetches exactly one version or label. */
export function getPrompt(name: string, selector: { version: number } | { label: string }): Promise<PromptVersion> {
    const query = new URLSearchParams({ name });
    if ('version' in selector) query.set('version', String(selector.version));
    else query.set('label', selector.label);
    return request(`/api/langfuse/prompts/selected?${query}`);
}
/** Creates an immutable version and defaults it to draft. */
export function createPromptVersion(input: PromptCreateRequest): Promise<PromptVersion> {
    const labels = [...new Set(['draft', ...(input.labels ?? [])])];
    return request('/api/langfuse/prompts', { method: 'POST', body: JSON.stringify({ ...input, labels }) });
}
/** Replaces non-production labels for one version. */
export function updatePromptLabels(name: string, version: number, labels: string[]): Promise<PromptVersion> { return request(`/api/langfuse/prompts/labels?${new URLSearchParams({ name, version: String(version) })}`, { method: 'PUT', body: JSON.stringify({ labels }) }); }
/** Requests the separately privileged production-promotion action. */
export function promotePromptToProduction(name: string, version: number): Promise<PromptVersion> { return request('/api/langfuse/prompts/production', { method: 'PUT', body: JSON.stringify({ name, version }) }); }
/** Requests safe substitution preview without model execution. */
export function previewPrompt(input: { name: string; version?: number; label?: string; values: Record<string, string> }): Promise<PromptPreviewResponse> { return request('/api/langfuse/prompts/preview', { method: 'POST', body: JSON.stringify(input) }); }

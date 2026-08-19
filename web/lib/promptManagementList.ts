/** Independent backend-owned filters for the prompt-management taxonomy. */
export interface PromptManagementFilters {
    domain?: string;
    responsibility?: string;
    stage?: string;
}

/** Builds a bounded prompt-list request with optional, composable taxonomy filters. */
export function buildPromptListPath(page = 1, limit = 20, filters: PromptManagementFilters = {}): string {
    const query = new URLSearchParams({ page: String(page), limit: String(limit) });
    const filterParameters: Array<[string, string | undefined]> = [
        ['management_domain', filters.domain],
        ['management_responsibility', filters.responsibility],
        ['management_stage', filters.stage],
    ];
    for (const [parameter, value] of filterParameters) {
        const normalizedValue = value?.trim();
        if (normalizedValue) query.set(parameter, normalizedValue);
    }
    return `/api/langfuse/prompts?${query}`;
}

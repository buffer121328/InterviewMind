import type { AbilityProfile, AbilityProfileSource, ProfileResponse } from '@/lib/api/profile';

export interface AbilityGrowthRecord {
    profile: AbilityProfile | null;
    generatedAt: string | null;
    sampleCount: number;
    sources: AbilityProfileSource[];
    dimensionChanges: Record<string, number>;
}

/** Normalizes legacy and Phase 2 profile responses without manufacturing history. */
export function normalizeAbilityGrowth(response: ProfileResponse): AbilityGrowthRecord {
    return {
        profile: response.success && response.profile ? response.profile : null,
        generatedAt: typeof response.generated_at === 'string' ? response.generated_at : null,
        sampleCount: Number.isSafeInteger(response.sample_count) && (response.sample_count ?? 0) >= 0
            ? response.sample_count!
            : 0,
        sources: Array.isArray(response.sources)
            ? response.sources.filter(source => Boolean(source?.session_id && source.profile))
            : [],
        dimensionChanges: response.dimension_changes && typeof response.dimension_changes === 'object'
            ? Object.fromEntries(Object.entries(response.dimension_changes).filter(([, value]) => typeof value === 'number' && Number.isFinite(value)))
            : {},
    };
}

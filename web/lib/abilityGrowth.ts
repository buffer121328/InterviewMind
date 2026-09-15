import type { AbilityProfile, AbilityProfileProgress, AbilityProfileSource, ProfileResponse } from '@/lib/api/profile';

export interface AbilityGrowthRecord {
    profile: AbilityProfile | null;
    generatedAt: string | null;
    sampleCount: number;
    sources: AbilityProfileSource[];
    dimensionChanges: Record<string, number>;
    progress: AbilityProfileProgress;
}

const DEFAULT_REQUIRED_ROUNDS = 3;

function normalizeAbilityProfileProgress(
    value: ProfileResponse['progress'],
): AbilityProfileProgress {
    const progress = (value && typeof value === 'object' ? value : {}) as Partial<AbilityProfileProgress>;
    const isSafeNonNegativeInteger = (candidate: unknown): candidate is number =>
        typeof candidate === 'number' && Number.isSafeInteger(candidate) && candidate >= 0;
    const required = isSafeNonNegativeInteger(progress.required_rounds) && progress.required_rounds > 0
        ? progress.required_rounds
        : DEFAULT_REQUIRED_ROUNDS;
    const completed = isSafeNonNegativeInteger(progress.completed_rounds) ? progress.completed_rounds : 0;
    const eligible = isSafeNonNegativeInteger(progress.eligible_rounds)
        ? Math.min(progress.eligible_rounds, required)
        : 0;
    const remaining = isSafeNonNegativeInteger(progress.remaining_rounds)
        ? progress.remaining_rounds
        : Math.max(0, required - eligible);
    const companyProfileCount = isSafeNonNegativeInteger(progress.company_profile_count)
        ? progress.company_profile_count
        : 0;
    const degradedRoundIndexes = Array.isArray(progress.degraded_round_indexes)
        ? progress.degraded_round_indexes.filter(isSafeNonNegativeInteger)
        : [];
    const blocker = ['none', 'incomplete_series', 'degraded_round_reports', 'company_profile_pending'].includes(
        String(progress.blocker),
    ) ? progress.blocker! : 'incomplete_series';
    const ready = progress.ready_to_generate === true && companyProfileCount > 0;

    return {
        completed_rounds: completed,
        eligible_rounds: ready ? required : eligible,
        required_rounds: required,
        remaining_rounds: ready ? 0 : remaining,
        company_profile_count: companyProfileCount,
        degraded_round_indexes: degradedRoundIndexes,
        ready_to_generate: ready,
        blocker,
    };
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
        progress: normalizeAbilityProfileProgress(response.progress),
    };
}

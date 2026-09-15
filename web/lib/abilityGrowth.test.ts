import assert from 'node:assert/strict';
import test from 'node:test';

import { normalizeAbilityGrowth } from './abilityGrowth.ts';

const profile = {
    professional_competence: { score: 8, evidence: 'e' },
    execution_results: { score: 8, evidence: 'e' },
    logic_problem_solving: { score: 8, evidence: 'e' },
    communication: { score: 8, evidence: 'e' },
    growth_potential: { score: 8, evidence: 'e' },
    collaboration: { score: 8, evidence: 'e' },
    skill_tags: [],
    last_updated: '2026-08-04',
};

test('normalizes persisted growth sources and dimension changes', () => {
    const result = normalizeAbilityGrowth({
        success: true,
        profile,
        sample_count: 1,
        sources: [{ session_id: 's1', title: '甲公司', completed_at: '2026-08-04', profile }],
        dimension_changes: { communication: 1.5 },
        progress: {
            completed_rounds: 7,
            eligible_rounds: 1,
            required_rounds: 3,
            remaining_rounds: 2,
            company_profile_count: 0,
            degraded_round_indexes: [1, 2],
            ready_to_generate: false,
            blocker: 'degraded_round_reports',
        },
    });

    assert.equal(result.sampleCount, 1);
    assert.equal(result.sources[0]?.session_id, 's1');
    assert.equal(result.dimensionChanges.communication, 1.5);
    assert.deepEqual(result.progress, {
        completed_rounds: 7,
        eligible_rounds: 1,
        required_rounds: 3,
        remaining_rounds: 2,
        company_profile_count: 0,
        degraded_round_indexes: [1, 2],
        ready_to_generate: false,
        blocker: 'degraded_round_reports',
    });
});

test('keeps legacy profile responses compatible without inventing history', () => {
    const result = normalizeAbilityGrowth({ success: true, profile });
    assert.equal(result.profile?.communication.score, 8);
    assert.deepEqual(result.sources, []);
    assert.deepEqual(result.dimensionChanges, {});
    assert.deepEqual(result.progress, {
        completed_rounds: 0,
        eligible_rounds: 0,
        required_rounds: 3,
        remaining_rounds: 3,
        company_profile_count: 0,
        degraded_round_indexes: [],
        ready_to_generate: false,
        blocker: 'incomplete_series',
    });
});

test('normalizes ready progress at and beyond the required rounds', () => {
    const result = normalizeAbilityGrowth({
        success: false,
        progress: {
            completed_rounds: 7,
            eligible_rounds: 3,
            required_rounds: 3,
            remaining_rounds: 0,
            company_profile_count: 1,
            degraded_round_indexes: [],
            ready_to_generate: true,
            blocker: 'none',
        },
    });

    assert.equal(result.progress.ready_to_generate, true);
    assert.equal(result.progress.remaining_rounds, 0);
});

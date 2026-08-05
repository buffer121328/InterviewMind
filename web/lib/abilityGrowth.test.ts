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
    });

    assert.equal(result.sampleCount, 1);
    assert.equal(result.sources[0]?.session_id, 's1');
    assert.equal(result.dimensionChanges.communication, 1.5);
});

test('keeps legacy profile responses compatible without inventing history', () => {
    const result = normalizeAbilityGrowth({ success: true, profile });
    assert.equal(result.profile?.communication.score, 8);
    assert.deepEqual(result.sources, []);
    assert.deepEqual(result.dimensionChanges, {});
});

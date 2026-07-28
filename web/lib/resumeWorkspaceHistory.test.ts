import test from 'node:test';
import assert from 'node:assert/strict';
import { restoreResumeHistorySelection } from './resumeWorkspaceHistory.ts';

test('restores a unified workspace record selected from today history', () => {
    const restored = restoreResumeHistorySelection({
        id: 42,
        result_type: 'optimize',
        result_data: {
            jd_analysis: { match_score: 86, hr_pass_rate: 73, keywords_required: ['TypeScript'], matched_keywords: ['TypeScript'], missing_keywords: [] },
            change_items: [{ section_name: '项目经历', optimized_text: '量化成果', reason: '补充指标' }],
            requires_user_review: true,
            confirmation_items: [{ item_id: 'change-1', optimized_text: '量化成果' }],
            human_review: { status: 'pending', version: 1, decisions: {} },
            workspace: {
                competition_analysis: { overall_score: 82, dimension_scores: {}, strengths: ['项目'], weaknesses: [], priority_improvements: [] },
                jd_matching: { overall_match_score: 86, skill_match_score: 90, project_match_score: 80, experience_match_score: 85, education_match_score: 70, matched_keywords: [], missing_keywords: [], strengths: [], risks: [], priority_actions: [] },
            },
        },
    });

    assert.equal(restored.resultId, 42);
    assert.equal(restored.workspace?.competition_analysis?.overall_score, 82);
    assert.equal(restored.workspace?.jd_matching?.overall_match_score, 86);
    assert.equal(restored.workspace?.content_optimization?.match_score, 86);
    assert.equal(restored.workspace?.content_optimization?.hr_pass_rate, 73);
    assert.equal(restored.review?.items[0]?.item_id, 'change-1');
});

test('keeps traditional analyze and optimize history entries compatible', () => {
    const analysis = restoreResumeHistorySelection({
        id: 7,
        result_type: 'analyze',
        result_data: { overall_score: 75, dimension_scores: {}, strengths: [], weaknesses: [], priority_improvements: [] },
    });
    const optimization = restoreResumeHistorySelection({
        id: 8,
        result_type: 'optimize',
        result_data: { match_score: 70, hr_pass_rate: 60, optimized_sections: [], key_improvements: [] },
    });

    assert.equal(analysis.workspace?.competition_analysis?.overall_score, 75);
    assert.equal(analysis.workspace?.content_optimization, undefined);
    assert.equal(optimization.workspace?.content_optimization?.match_score, 70);
    assert.equal(optimization.review, null);
});


test('uses the richer workspace JD score when an older pipeline persisted zero', () => {
    const restored = restoreResumeHistorySelection({
        id: 43,
        result_type: 'optimize',
        result_data: {
            jd_analysis: { match_score: 0, matched_keywords: [], missing_keywords: [] },
            change_items: [],
            workspace: {
                jd_matching: {
                    overall_match_score: 72.5,
                    skill_match_score: 70,
                    project_match_score: 75,
                    experience_match_score: 73,
                    education_match_score: 70,
                    matched_keywords: [],
                    missing_keywords: [],
                    strengths: [],
                    risks: [],
                    priority_actions: [],
                },
            },
        },
    });

    assert.equal(restored.workspace?.content_optimization?.match_score, 72.5);
    assert.equal(restored.workspace?.content_optimization?.hr_pass_rate, 62);
});

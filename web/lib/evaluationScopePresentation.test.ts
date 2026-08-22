import test from 'node:test';
import assert from 'node:assert/strict';

import { formatEvaluationScopeSummary } from './evaluationScopePresentation.ts';

test('formats the server-owned standard scope without exposing fixture content', () => {
    assert.equal(
        formatEvaluationScopeSummary({
            name: 'standard',
            dataset_name: 'builtin.interview-planner.standard',
            dataset_version: 'v1',
            suite_name: 'builtin.interview-planner.standard',
            rubric_version: 'builtin-v1',
            case_count: 3,
            input_categories: ['简历', '岗位 JD', '问题与面试上下文'],
            tool_applicability: { not_applicable: 3 },
        }),
        'builtin.interview-planner.standard · 3 条案例 · 覆盖 简历、岗位 JD、问题与面试上下文 · 无需工具 3 条',
    );
});

test('includes forbidden and required tool counts only when present', () => {
    assert.match(
        formatEvaluationScopeSummary({
            name: 'release',
            dataset_name: 'builtin.interview-planner.release',
            dataset_version: 'v1',
            suite_name: 'builtin.interview-planner.release',
            rubric_version: 'builtin-v1',
            case_count: 2,
            input_categories: ['简历', '岗位 JD', '发布 holdout'],
            tool_applicability: { not_applicable: 1, required: 0, forbidden: 1 },
        }),
        /无需工具 1 条 · 禁止工具 1 条$/,
    );
});

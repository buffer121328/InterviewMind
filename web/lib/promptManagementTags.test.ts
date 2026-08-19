import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPromptListPath } from './promptManagementList.ts';
import { getPromptManagementTagsForCategory, getVisiblePromptManagementTags } from './promptManagementTags.ts';

test('prompt list request encodes independent composable backend taxonomy filters', () => {
    assert.equal(buildPromptListPath(2, 20), '/api/langfuse/prompts?page=2&limit=20');
    assert.equal(
        buildPromptListPath(1, 20, {
            domain: 'domain-ability-analysis',
            responsibility: 'role-expert-review',
            stage: 'stage-evaluation',
        }),
        '/api/langfuse/prompts?page=1&limit=20&management_domain=domain-ability-analysis&management_responsibility=role-expert-review&management_stage=stage-evaluation',
    );
    assert.equal(
        buildPromptListPath(1, 20, { domain: 'domain-ability-analysis', stage: 'stage-evaluation' }),
        '/api/langfuse/prompts?page=1&limit=20&management_domain=domain-ability-analysis&management_stage=stage-evaluation',
    );
});

test('visible management tags keep specialist roles without repeating the functional group', () => {
    assert.deepEqual(
        getVisiblePromptManagementTags([
            { key: 'domain-ability-analysis', label: '能力分析', category: '业务领域' },
            { key: 'role-expert-review', label: '评审专家', category: '工作职责' },
            { key: 'role-technical-expert', label: '技术专家', category: '工作职责' },
            { key: 'role-expert-review', label: '评审专家', category: '工作职责' },
        ], '能力分析'),
        [
            { key: 'role-expert-review', label: '评审专家', category: '工作职责' },
            { key: 'role-technical-expert', label: '技术专家', category: '工作职责' },
        ],
    );
    assert.deepEqual(getVisiblePromptManagementTags(undefined, '能力分析'), []);
});

test('management tags supply separate option lists for each taxonomy category', () => {
    const tags = [
        { key: 'stage-review', label: '审查', category: '处理阶段' as const },
        { key: 'role-hr-review', label: 'HR 审查', category: '工作职责' as const },
        { key: 'domain-resume-optimization', label: '简历优化', category: '业务领域' as const },
    ];

    assert.deepEqual(
        getPromptManagementTagsForCategory(tags, '业务领域'),
        [{ key: 'domain-resume-optimization', label: '简历优化', category: '业务领域' }],
    );
    assert.deepEqual(
        getPromptManagementTagsForCategory(tags, '工作职责'),
        [{ key: 'role-hr-review', label: 'HR 审查', category: '工作职责' }],
    );
    assert.deepEqual(
        getPromptManagementTagsForCategory(tags, '处理阶段'),
        [{ key: 'stage-review', label: '审查', category: '处理阶段' }],
    );
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { getPromptDisplayName, getPromptFunctionalGroup, getPromptLabelDisplayName } from './promptCatalog.ts';

test('prompt catalog translates backend names to Chinese display names', () => {
    assert.equal(getPromptDisplayName('analysis.multi_reviewer_consensus.ability_profile'), '能力画像多评审共识汇总');
    assert.equal(getPromptFunctionalGroup('analysis.multi_reviewer_consensus.ability_profile'), '能力分析');
    assert.equal(getPromptDisplayName('analysis.question_evidence'), '面试逐题证据块');
    assert.equal(getPromptDisplayName('analysis.evidence_report'), '逐题证据汇总报告');
    assert.equal(getPromptDisplayName('resume.rewrite_planner'), '简历改写规划');
    assert.equal(getPromptDisplayName('resume.rewrite_executor'), '简历改写执行');
    assert.equal(getPromptDisplayName('resume.material_extraction'), '简历素材抽取');
    assert.equal(getPromptFunctionalGroup('resume.material_extraction'), '简历素材');
    assert.equal(getPromptDisplayName('analysis.aggregate_profile'), '跨场综合画像（兼容）');
    assert.equal(getPromptFunctionalGroup('analysis.aggregate_profile'), '能力分析');
    assert.equal(getPromptDisplayName('voice.system'), '语音面试回复');
    assert.equal(getPromptFunctionalGroup('voice.system'), '语音面试');
});

test('prompt catalog prefers backend-owned Chinese presentation metadata', () => {
    assert.equal(getPromptDisplayName('future.builtin', '后端新增提示词'), '后端新增提示词');
    assert.equal(getPromptFunctionalGroup('future.builtin', '新增功能'), '新增功能');
});

test('prompt catalog corrects stale backend fallbacks for known historical prompts', () => {
    assert.equal(
        getPromptDisplayName('analysis.candidate_profile', 'analysis.candidate_profile'),
        '单场能力画像',
    );
    assert.equal(
        getPromptFunctionalGroup('analysis.candidate_profile', '自定义提示词'),
        '能力分析',
    );
});

test('prompt catalog keeps unknown custom names usable', () => {
    assert.equal(getPromptDisplayName('custom.prompt'), 'custom.prompt');
    assert.equal(getPromptFunctionalGroup('custom.prompt'), '自定义提示词');
});


test('prompt catalog translates stable English groups and lifecycle labels', () => {
    assert.equal(getPromptFunctionalGroup('custom.prompt', 'Interview'), '模拟面试');
    assert.equal(getPromptFunctionalGroup('custom.prompt', 'resume generation'), '简历生成');
    assert.equal(getPromptLabelDisplayName('latest'), '最新');
    assert.equal(getPromptLabelDisplayName('development'), '开发');
    assert.equal(getPromptLabelDisplayName('archived'), '已归档');
});

test('prompt catalog preserves unknown custom presentation values', () => {
    assert.equal(getPromptFunctionalGroup('custom.prompt', 'Partner Workflow'), 'Partner Workflow');
    assert.equal(getPromptLabelDisplayName('partner-preview'), 'partner-preview');
});

test('known historical prompt names keep their Chinese builtin presentation', () => {
    assert.equal(getPromptDisplayName('analysis.weakness_report'), '短板报告');
    assert.equal(getPromptFunctionalGroup('analysis.weakness_report'), '能力分析');
});

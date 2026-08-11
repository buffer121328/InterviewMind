import assert from 'node:assert/strict';
import test from 'node:test';
import { extractProfessionalSkills } from './bossResume.ts';

test('extracts only the professional skills section', () => {
    const result = extractProfessionalSkills('姓名：候选人\n教育背景\n计算机技术硕士\n专业技能：\nPython、FastAPI、LangGraph\n项目经历\nAgent 项目');
    assert.equal(result.matched, true);
    assert.equal(result.content, 'Python、FastAPI、LangGraph');
});

test('supports markdown and English skills headings', () => {
    const result = extractProfessionalSkills('# Skills\nPython\nFastAPI\n## Experience\nAgent project');
    assert.equal(result.matched, true);
    assert.equal(result.content, 'Python\nFastAPI');
});

test('fails open when no skills section is reliable', () => {
    const raw = '计算机技术硕士\nAgent 项目经历';
    const result = extractProfessionalSkills(raw);
    assert.equal(result.matched, false);
    assert.equal(result.content, raw);
});

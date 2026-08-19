import assert from 'node:assert/strict';
import test from 'node:test';
import {
    DEFAULT_NEW_INTERVIEW_REPORT_MODE,
    getInterviewReportDisplayPolicy,
    normalizeInterviewReportMode,
} from './interviewReportMode.ts';

test('new interview setup defaults to the recommended standard report mode', () => {
    assert.equal(DEFAULT_NEW_INTERVIEW_REPORT_MODE, 'standard');
    assert.equal(normalizeInterviewReportMode(undefined), 'deep');
    assert.equal(normalizeInterviewReportMode('standard'), 'standard');
    assert.equal(normalizeInterviewReportMode('unexpected'), 'deep');
});

test('standard report policy exposes only persisted PDF consumption and deep upgrade', () => {
    assert.deepEqual(getInterviewReportDisplayPolicy('standard'), {
        label: '标准报告',
        description: '快速生成 PDF，适合快速复盘',
        showStructuredSections: false,
        showMarkdown: false,
        showHtmlDownload: false,
        showPdf: true,
        showRecommendedQuestions: false,
        showDeepGenerationAction: true,
    });
});

test('deep report policy preserves structured and multi-format consumption', () => {
    assert.deepEqual(getInterviewReportDisplayPolicy('deep'), {
        label: '深度报告',
        description: '多视角结构化复盘，包含完整分析与导出',
        showStructuredSections: true,
        showMarkdown: true,
        showHtmlDownload: true,
        showPdf: true,
        showRecommendedQuestions: true,
        showDeepGenerationAction: false,
    });
});

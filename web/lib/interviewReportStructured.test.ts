import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeStructuredInterviewReport } from './interviewReportStructured.ts';

test('normalizeStructuredInterviewReport keeps bounded sections and empty fallbacks', () => {
    const report = normalizeStructuredInterviewReport({
        success: true,
        session_id: 'session-1',
        markdown: '# report',
        profile: { overall_assessment: '稳定', key_strengths: ['表达清晰'] },
        weakness_report: { recommended_questions: ['如何做容量估算？'], question_evidence: [{ question_id: 'Q1' }] },
    });
    assert.equal(report.profile.overall_assessment, '稳定');
    assert.deepEqual(report.profile.key_weaknesses, []);
    assert.equal(report.weaknessReport.questionEvidence[0].question_id, 'Q1');
});

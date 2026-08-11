import assert from 'node:assert/strict';
import test from 'node:test';
import { buildResumeJobSelection } from './resumeJobSelection.ts';

test('resume workspace selection keeps full JD and owner-validated source snapshot', () => {
    const selection = buildResumeJobSelection({
        id: 12,
        platform: 'boss',
        source_url: 'https://www.zhipin.com/job_detail/12.html',
        company_name: '示例科技',
        company_size_text: '500-999人',
        job_title: 'Agent 应用开发工程师',
        job_description: '负责 Agent 工作流、RAG 与工具治理。',
        salary_text: '20-35K',
        city: '深圳',
        captured_at: '2026-08-07T00:00:00Z',
        match_score: null,
        tags: [],
        status: 'captured',
    });
    assert.equal(selection.jobDescription, '负责 Agent 工作流、RAG 与工具治理。');
    assert.equal(selection.snapshot.source_job_id, 12);
    assert.equal(selection.snapshot.company_name, '示例科技');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildInterviewJobSelection } from './interviewJobSelection.ts';

test('job library selection fills interview snapshot, JD, and company context', () => {
    const selection = buildInterviewJobSelection({
        id: 42,
        platform: 'boss',
        source_url: 'https://example.com/job/42',
        company_name: '示例科技',
        company_size_text: '100-499人',
        job_title: 'Agent 工程师',
        job_description: '负责 Agent 平台研发',
        salary_text: '20-30K',
        city: '深圳',
        captured_at: '2026-08-04T10:00:00Z',
    });

    assert.equal(selection.snapshot.source_job_id, 42);
    assert.equal(selection.jobDescription, '负责 Agent 平台研发');
    assert.equal(selection.companyInfo, '公司：示例科技\n目标岗位：Agent 工程师\n公司规模：100-499人');
});

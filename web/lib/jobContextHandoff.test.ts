import assert from 'node:assert/strict';
import test from 'node:test';
import { buildJobContextSnapshot, updateJobContextSnapshot } from './jobContextHandoff.ts';

test('buildJobContextSnapshot maps persisted owner-scoped job fields', () => {
    const snapshot = buildJobContextSnapshot({
        id: 42,
        platform: 'boss',
        source_url: 'https://www.zhipin.com/job_detail/abc.html',
        company_name: '示例科技',
        company_size_text: '100-499人',
        job_title: 'Agent 工程师',
        job_description: '负责 Agent 产品开发',
        salary_text: '20-30K',
        city: '深圳',
        captured_at: '2026-08-04T10:00:00Z',
    });

    assert.deepEqual(snapshot, {
        source_job_id: 42,
        source_platform: 'boss',
        source_url: 'https://www.zhipin.com/job_detail/abc.html',
        company_name: '示例科技',
        company_size_text: '100-499人',
        job_title: 'Agent 工程师',
        job_description: '负责 Agent 产品开发',
        salary_text: '20-30K',
        city: '深圳',
        imported_at: '2026-08-04T10:00:00Z',
    });
});

test('buildJobContextSnapshot uses bounded empty fallbacks and source text', () => {
    const snapshot = buildJobContextSnapshot({
        id: 7,
        company_name: '',
        company_size_text: '',
        job_title: '后端工程师',
        platform: '',
        salary_text: '',
        city: '',
        source_url: '',
        source_text: '后端职位介绍',
    });

    assert.equal(snapshot.source_job_id, 7);
    assert.equal(snapshot.job_description, '后端职位介绍');
    assert.equal(snapshot.source_platform, '');
    assert.equal(snapshot.imported_at, '');
});


test('updateJobContextSnapshot preserves source identity and applies actual workspace edits', () => {
    const original = buildJobContextSnapshot({
        id: 42, platform: 'boss', source_url: 'https://example.com/42',
        company_name: '原公司', company_size_text: '100人', job_title: '原岗位',
        job_description: '原 JD', salary_text: '20K', city: '上海', captured_at: '2026-08-04',
    });
    const edited = updateJobContextSnapshot(original, {
        company_name: '编辑后的公司', job_title: '编辑后的岗位', job_description: '编辑后的 JD',
    });

    assert.equal(edited.source_job_id, 42);
    assert.equal(edited.source_url, 'https://example.com/42');
    assert.equal(edited.company_name, '编辑后的公司');
    assert.equal(edited.job_title, '编辑后的岗位');
    assert.equal(edited.job_description, '编辑后的 JD');
});

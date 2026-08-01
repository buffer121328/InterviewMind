import assert from 'node:assert/strict';
import test from 'node:test';
import {
    captureRunMessage,
    formatDate,
    getCaptureRunJobs,
    mergeAssetRun,
    readStringList,
    replaceResultGreeting,
} from './bossCenter.ts';

test('formatDate renders compact local time or falls back', () => {
    assert.equal(formatDate(undefined), '时间未知');
    assert.equal(formatDate('not-a-date'), 'not-a-date');
    const formatted = formatDate('2026-08-01T10:30:00Z');
    assert.notEqual(formatted, '2026-08-01T10:30:00Z');
    assert.ok(formatted.length > 0);
});

test('readStringList reads bounded string arrays and ignores bad records', () => {
    assert.deepEqual(readStringList({ tags: ['a', 'b', 3, 'c'] }, 'tags'), ['a', 'b', 'c']);
    assert.deepEqual(readStringList(null, 'tags'), []);
    assert.deepEqual(readStringList({ missing: undefined }, 'missing'), []);
});

test('getCaptureRunJobs only reads public captured-job summaries', () => {
    assert.deepEqual(getCaptureRunJobs(null), []);
    assert.deepEqual(getCaptureRunJobs({ result: { jobs: 'nope' } } as never), []);
    const run = {
        result: {
            jobs: [
                { job_id: 1, job_title: '后端工程师', company_name: '公司A', salary_text: '20k', city: '深圳', greetings: [], risk_flags: [] },
                { job_id: null, job_title: '前端工程师', company_name: '公司B', salary_text: '20k', city: '广州', greetings: [], risk_flags: [] },
                { job_id: 'oops', job_title: '坏数据', company_name: '公司C', salary_text: '1', city: '', greetings: [], risk_flags: [] },
            ],
        },
    } as never;
    const jobs = getCaptureRunJobs(run as never);
    assert.equal(jobs.length, 2);
    assert.equal(jobs[0].job_title, '后端工程师');
    assert.equal(jobs[1].job_id, null);
});

test('mergeAssetRun merges a child asset run result into its card', () => {
    const job = {
        job_id: 1,
        company_name: '公司A',
        job_title: '后端工程师',
        salary_text: '20k',
        city: '深圳',
        match_score: 50,
        custom_resume_id: null,
        greetings: [],
        risk_flags: [],
        asset_status: null,
    } as never;
    const run = {
        status: 'running',
        result: {
            assets: {
                jd_analysis: { overall_match_score: 88 },
                custom_resume_id: 7,
                greetings: [{ tone: 'professional', message_text: '您好，我看到了您的岗位信息' }],
                risk_flags: ['仅支持线下办公'],
            },
        },
    } as never;
    const merged = mergeAssetRun(job as never, run as never);
    assert.equal(merged.match_score, 88);
    assert.equal(merged.asset_status, 'running');
    assert.equal(merged.custom_resume_id, 7);
    assert.deepEqual(merged.risk_flags, ['仅支持线下办公']);
    assert.equal(merged.greetings[0].message_text, '您好，我看到了您的岗位信息');
});

test('captureRunMessage maps known stages and falls back to a safe summary', () => {
    assert.equal(captureRunMessage({ stage: 'ranking_jobs' } as never, 5), '正在结合基础简历做语义匹配与本地关键词评分。');
    assert.equal(
        captureRunMessage({ stage: 'unknown_stage' } as never, 3),
        '任务已持久化，当前阶段：unknown_stage · 已等待 3s',
    );
});

test('replaceResultGreeting updates exactly one greeting in place', () => {
    const jobs = [{
        job_id: 1,
        company_name: '公司A',
        job_title: '后端工程师',
        salary_text: '20k',
        city: '深圳',
        greetings: [
            { tone: 'professional', message_text: '旧文案' },
            { tone: 'technical', message_text: '保留文案' },
        ],
        risk_flags: [],
    }] as Array<{ job_id: number; greetings: Array<{ tone: string; message_text: string }>; [key: string]: unknown }>;
    const updated = replaceResultGreeting(jobs as never, 1, 0, '新文案');
    assert.equal(updated[0].greetings[0].message_text, '新文案');
    assert.equal(updated[0].greetings[1].message_text, '保留文案');
    assert.equal(jobs[0].greetings[0].message_text, '旧文案');
});

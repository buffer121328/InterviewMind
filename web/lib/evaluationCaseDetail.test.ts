import assert from 'node:assert/strict';
import test from 'node:test';

import {
    evaluationReviewReasonLabel,
    paginateEvaluationScores,
    summarizeEvaluationOutput,
    summarizeEvaluationCaseOutcome,
    summarizeEvaluationScores,
    summarizeEvaluationSemanticStatus,
    summarizeEvaluationScoreStatuses,
    summarizeEvaluationToolApplicability,
    buildEvaluationReviewGuidance,
} from './evaluationCaseDetail.ts';

test('case detail groups deterministic rules into an easy-to-scan summary', () => {
    const summaries = summarizeEvaluationScores([
        { id: '1', case_run_id: 'run', metric_name: 'schema', value: 1, status: 'passed', source: 'deterministic', reason: null, severity: 'high', hard_gate: true, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        { id: '2', case_run_id: 'run', metric_name: 'approval', value: 0, status: 'failed', source: 'deterministic', reason: 'missing approval', severity: 'high', hard_gate: true, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        { id: '3', case_run_id: 'run', metric_name: 'semantic', value: null, status: 'pending', source: 'judge', reason: null, severity: 'medium', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
    ]);

    assert.deepEqual(
        summaries.map(({ source, label, passed, failed, review, notApplicable, hardGateFailures }) => ({ source, label, passed, failed, review, notApplicable, hardGateFailures })),
        [
            { source: 'deterministic', label: '确定性规则', passed: 1, failed: 1, review: 0, notApplicable: 0, hardGateFailures: 1 },
            { source: 'judge', label: 'LLM Judge', passed: 0, failed: 0, review: 1, notApplicable: 0, hardGateFailures: 0 },
        ],
    );
});

test('pending human review takes precedence over a successful runtime status', () => {
    const detail = {
        status: 'succeeded',
        needs_review: true,
        review_status: 'pending',
        statusLabel: undefined,
        latency_ms: 100,
        token_usage: {},
        hard_gate_passed: true,
        record: { outcome: { runtime_success: true } },
        review_reasons: ['semantic_failure'],
    } as never;
    const summary = summarizeEvaluationCaseOutcome(detail);
    assert.equal(summary.statusLabel, '待人工复核');
    assert.equal(summary.statusTone, 'review');
});


test('score summaries keep non-applicable rules out of the review count', () => {
    const summaries = summarizeEvaluationScores([
        { id: '1', case_run_id: 'run', metric_name: 'schema', value: 1, status: 'passed', source: 'deterministic', reason: null, severity: 'high', hard_gate: true, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        { id: '2', case_run_id: 'run', metric_name: 'tool_calls', value: null, status: 'not_applicable', source: 'deterministic', reason: 'no_observed_calls', severity: 'info', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
    ]);

    assert.deepEqual(summaries[0] && { passed: summaries[0].passed, review: summaries[0].review, notApplicable: summaries[0].notApplicable }, { passed: 1, review: 0, notApplicable: 1 });
});

test('case list semantic status does not expose internal aggregate scores', () => {
    assert.deepEqual(summarizeEvaluationSemanticStatus({ semantic_evaluated: true, semantic_success: true }), { label: '通过', tone: 'passed' });
    assert.deepEqual(summarizeEvaluationSemanticStatus({ semantic_evaluated: true, semantic_success: false }), { label: '未通过', tone: 'failed' });
    assert.deepEqual(summarizeEvaluationSemanticStatus({ semantic_evaluated: false, semantic_success: null }), { label: '未评测', tone: 'neutral' });
});

test('case detail summaries keep raw output content out of the default label', () => {
    assert.equal(summarizeEvaluationOutput('candidate private text'), '文本输出 · 22 字符');
    assert.equal(summarizeEvaluationOutput({ questions: [{ text: 'q1' }, { text: 'q2' }], metadata: {} }), '结构化输出 · 2 个字段，含 2 个问题');
    assert.equal(evaluationReviewReasonLabel('hard_gate_failure'), '硬门禁失败');
});

test('case detail paginates score rules in stable ten-rule pages and bounds stale pages', () => {
    const scores = Array.from({ length: 21 }, (_, index) => ({
        id: String(index + 1),
        case_run_id: 'run',
        metric_name: `rule-${index + 1}`,
        value: 1,
        status: 'passed',
        source: 'deterministic' as const,
        reason: null,
        severity: 'low',
        hard_gate: false,
        evidence_refs: [],
        metric_version: 'v1',
        created_at: '2026-08-20T00:00:00Z',
    }));

    const secondPage = paginateEvaluationScores(scores, 2);
    assert.equal(secondPage.totalPages, 3);
    assert.equal(secondPage.page, 2);
    assert.deepEqual(secondPage.scores.map((score) => score.metric_name), [
        'rule-11', 'rule-12', 'rule-13', 'rule-14', 'rule-15',
        'rule-16', 'rule-17', 'rule-18', 'rule-19', 'rule-20',
    ]);

    const boundedLastPage = paginateEvaluationScores(scores, 99);
    assert.equal(boundedLastPage.page, 3);
    assert.deepEqual(boundedLastPage.scores.map((score) => score.metric_name), ['rule-21']);
});


function caseDetailForScoreStatus(overrides: Record<string, unknown> = {}) {
    return {
        id: 'case-run-1',
        evaluation_run_id: 'evaluation-run-1',
        case_id: 'case-1',
        repetition_index: 0,
        status: 'succeeded',
        trace_id: null,
        latency_ms: 100,
        token_usage: {},
        hard_gate_passed: true,
        overall_score: null,
        error_category: null,
        needs_review: false,
        review_reasons: [],
        review_status: 'not_required',
        review_resolver_key: null,
        review_resolved_at: null,
        review_resolution_note: null,
        actual_output: {},
        pairwise_outputs: { A: {}, B: null },
        record: {},
        case: { id: 'case-1', case_key: 'smoke', category: 'resume_analyzer', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: {} },
        scores: [],
        annotations: [],
        ...overrides,
    } as never;
}

test('quick smoke score status distinguishes passed and non-applicable automatic rules from an intentionally disabled Judge', () => {
    const statuses = summarizeEvaluationScoreStatuses(caseDetailForScoreStatus({
        scores: [
            { id: 'rule-1', case_run_id: 'case-run-1', metric_name: 'hard_gate', value: 1, status: 'passed', source: 'deterministic', reason: null, severity: 'high', hard_gate: true, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
            { id: 'rule-2', case_run_id: 'case-run-1', metric_name: 'tool_calls', value: null, status: 'not_applicable', source: 'deterministic', reason: 'no_observed_calls', severity: 'info', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        ],
    }), { includeJudges: false });

    assert.deepEqual(statuses, [
        { key: 'automatic_rules', label: '自动规则', detail: '通过（1 项，1 项不适用）', tone: 'passed' },
        { key: 'llm_judge', label: 'LLM Judge', detail: '未启用（快速冒烟默认不调用 Judge）', tone: 'neutral' },
        { key: 'human_review', label: '人工复核', detail: '不需要', tone: 'passed' },
    ]);
});

test('score status reports Judge and human review separately when they are active', () => {
    const statuses = summarizeEvaluationScoreStatuses(caseDetailForScoreStatus({
        needs_review: true,
        review_status: 'pending',
        scores: [{ id: 'judge-1', case_run_id: 'case-run-1', metric_name: 'semantic', value: null, status: 'pending', source: 'judge', reason: null, severity: 'medium', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' }],
    }), { includeJudges: true });

    assert.deepEqual(statuses, [
        { key: 'automatic_rules', label: '自动规则', detail: '暂无规则结果', tone: 'neutral' },
        { key: 'llm_judge', label: 'LLM Judge', detail: '结果待复核', tone: 'review' },
        { key: 'human_review', label: '人工复核', detail: '需要处理：待处理', tone: 'review' },
    ]);
});


test('no-tool case explicitly reports tool metrics as not applicable', () => {
    const summary = summarizeEvaluationToolApplicability(caseDetailForScoreStatus({
        case: { id: 'case-1', case_key: 'smoke', category: 'interview_turn', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: { expected_tool_calls: [], allowed_tool_calls: [] } },
        record: { tool_calls: [] },
    }));

    assert.deepEqual(summary, { label: '工具调用', detail: '不适用（本案例未要求工具）' });
});

test('review guidance collapses missing required tool consequences into one root cause', () => {
    const guidance = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        case: { id: 'case-1', case_key: 'profile', category: 'interview_turn', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: { expected_tool_calls: ['get_candidate_profile'], expected_facts: ['缓存穿透'] } },
        record: { tool_calls: [] },
        scores: [
            { id: '1', case_run_id: 'case-run-1', metric_name: 'tool.expected_call_coverage', value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
            { id: '2', case_run_id: 'case-run-1', metric_name: 'tool.fixture_result_adoption', value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' },
        ],
    }));

    assert.equal(guidance.title, '建议确认：工具选择遗漏');
    assert.match(guidance.recommendation, /无需逐项标注/);
    assert.match(guidance.checks.find((item) => item.label === '实际工具执行')?.detail ?? '', /未完成/);
});

test('review guidance gives a JSON path and current value for budget, fact, and allowed-tool failures', () => {
    const guidance = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        latency_ms: 70000,
        token_usage: { total_tokens: 9000 },
        case: { id: 'case-1', case_key: 'budget', category: 'interview_turn', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: { latency_budget_ms: 60000, token_budget: 8000, expected_facts: ['缓存一致性'], allowed_tool_calls: ['get_candidate_profile'], quality_rubric: { tool_result_facts: ['缓存穿透防护'] } } },
        record: { tool_calls: [{ tool_name: 'unexpected_tool', status: 'completed' }] },
        scores: [
            'budget.latency_compliance', 'budget.token_compliance', 'factual.expected_fact_coverage', 'tool.allowed_call_compliance', 'tool.fixture_result_adoption',
        ].map((metric_name, index) => ({ id: String(index + 1), case_run_id: 'case-run-1', metric_name, value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' })),
    }));

    const latencyDetail = guidance.checks.find((check) => check.label.includes('budget.latency_compliance'))?.detail ?? '';
    assert.match(latencyDetail, /expected\.latency_budget_ms[\s\S]*latency_ms=70000[\s\S]*预算=60000/);
    assert.match(guidance.checks.find((check) => check.label.includes('budget.token_compliance'))?.detail ?? '', /expected\.token_budget[\s\S]*实际 Token=9000[\s\S]*预算=8000/);
    assert.match(guidance.checks.find((check) => check.label.includes('factual.expected_fact_coverage'))?.detail ?? '', /expected\.expected_facts[\s\S]*缓存一致性/);
    const allowedToolDetail = guidance.checks.find((check) => check.label.includes('tool.allowed_call_compliance'))?.detail ?? '';
    assert.match(allowedToolDetail, /expected\.allowed_tool_calls[\s\S]*unexpected_tool/);
    assert.match(guidance.checks.find((check) => check.label.includes('tool.fixture_result_adoption'))?.detail ?? '', /quality_rubric\.tool_result_facts[\s\S]*缓存穿透防护/);
    assert.match(allowedToolDetail, /允许工具：get_candidate_profile\n实际记录：unexpected_tool（completed）\n只要出现允许列表外的工具，就不通过。/);
});

test('review guidance labels governed follow-up checks and their handling mode', () => {
    const guidance = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        latency_ms: 70000,
        token_usage: { total_tokens: 9000 },
        case: { id: 'case-1', case_key: 'scope', category: 'interview_turn', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: {
            latency_budget_ms: 60000,
            token_budget: 8000,
            expected_facts: ['缓存一致性'],
            allowed_tool_calls: ['get_candidate_profile'],
            quality_rubric: { tool_result_facts: ['缓存穿透防护'] },
        } },
        record: { tool_calls: [{ tool_name: 'get_candidate_profile', status: 'completed' }] },
        scores: [
            'budget.latency_compliance',
            'budget.token_compliance',
            'factual.expected_fact_coverage',
            'tool.allowed_call_compliance',
            'tool.fixture_result_adoption',
        ].map((metric_name, index) => ({ id: String(index + 1), case_run_id: 'case-run-1', metric_name, value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' })),
    }));

    const labels = guidance.checks.map((check) => ({ label: check.label, scope: check.scopeLabel, action: check.actionLabel }));
    assert.deepEqual(labels.filter((item) => item.label.includes('预算')), [
        { label: '延迟预算 · budget.latency_compliance', scope: '纳入治理', action: '自动检查' },
        { label: 'Token 预算 · budget.token_compliance', scope: '纳入治理', action: '自动检查' },
    ]);
    assert.deepEqual(labels.filter((item) => item.label.includes('事实') || item.label.includes('工具结果')), [
        { label: '输出需确认的事实', scope: '纳入治理', action: '人工确认' },
        { label: '期望事实覆盖 · factual.expected_fact_coverage', scope: '纳入治理', action: '自动检查' },
        { label: '工具结果采用 · tool.fixture_result_adoption', scope: '纳入治理', action: '自动检查' },
    ]);
});

test('review guidance marks absent follow-up constraints as not applicable', () => {
    const guidance = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        case: { id: 'case-1', case_key: 'minimal', category: 'interview_turn', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: {} },
        record: { tool_calls: [] },
        scores: [],
    }));

    assert.deepEqual(guidance.checks, [{
        label: '自动复核原因',
        detail: '请检查评分与运行轨迹',
        outcome: 'review',
        scopeLabel: '未纳入治理',
        actionLabel: '无需处理',
    }]);
});

test('review guidance states the detected forbidden claim without requiring reviewers to search JSON', () => {
    const guidance = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        actual_output: { summary: '候选人具备团队管理经验，并主导过架构设计。' },
        case: { id: 'case-1', case_key: 'boundary', category: 'resume_optimizer', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: { forbidden_claims: ['具备团队管理经验', '主导过架构设计'] } },
        scores: [{ id: '1', case_run_id: 'case-run-1', metric_name: 'factual.forbidden_claim_absence', value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' }],
    }));

    const check = guidance.checks.find((item) => item.label.includes('factual.forbidden_claim_absence'));
    assert.match(check?.detail ?? '', /不需要翻找 JSON/);
    assert.match(check?.detail ?? '', /自动检查检测到：具备团队管理经验、主导过架构设计/);
});

test('review guidance scopes forbidden claims to the user-facing resume field', () => {
    const failedCheck = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        actual_output: {
            assembled_resume: '若您有团队管理相关工作经验，请补充对应工作内容。',
            change_items: [{ reason: '目标岗位要求具备团队管理经验，当前简历无对应证据' }],
        },
        case: { id: 'case-1', case_key: 'boundary', category: 'resume_optimizer', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: {
            forbidden_claims: ['具备团队管理经验'],
            quality_rubric: { primary_output_paths: ['assembled_resume'] },
        } },
        scores: [{ id: '1', case_run_id: 'case-run-1', metric_name: 'factual.forbidden_claim_absence', value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' }],
    }));
    const failedDetail = failedCheck.checks.find((item) => item.label.includes('factual.forbidden_claim_absence'))?.detail ?? '';
    assert.match(failedDetail, /自动检查范围：assembled_resume（仅主输出，排除说明元数据）/);
    assert.match(failedDetail, /自动检查检测到：无/);
});

test('review guidance detects expected facts in planner question content projection', () => {
    const guidance = buildEvaluationReviewGuidance(caseDetailForScoreStatus({
        actual_output: [{ content: '请说明你如何处理缓存一致性。', reason: '弱点报告包含缓存一致性' }],
        case: { id: 'case-1', case_key: 'planner', category: 'interview_planner', tags: [], severity: 'high', content_hash: 'hash', created_at: '2026-08-20T00:00:00Z', input: {}, expected: {
            expected_facts: ['缓存一致性'],
            quality_rubric: { primary_output_paths: ['[].content'], tool_result_facts: ['缓存一致性'] },
        } },
        scores: [{ id: '1', case_run_id: 'case-run-1', metric_name: 'factual.expected_fact_coverage', value: 0, status: 'failed', source: 'deterministic', reason: null, severity: 'high', hard_gate: false, evidence_refs: [], metric_version: 'v1', created_at: '2026-08-20T00:00:00Z' }],
    }));

    const detail = guidance.checks.find((item) => item.label.includes('factual.expected_fact_coverage'))?.detail ?? '';
    assert.match(detail, /自动检查范围：\[\]\.content（仅主输出，排除说明元数据）/);
    assert.match(detail, /自动检查检测到：缓存一致性/);
});

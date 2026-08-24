import type { EvaluationCaseRun, EvaluationCaseRunDetail, EvaluationScore } from './api/evaluations';

export type EvaluationDisplayOutcome = 'passed' | 'failed' | 'review';
export type EvaluationStatusTone = EvaluationDisplayOutcome | 'neutral';

export const EVALUATION_SCORE_RULE_PAGE_SIZE = 10;

export interface EvaluationMetricPresentation {
    label: string;
    group: string;
    description: string;
}

const METRIC_PRESENTATIONS: Record<string, EvaluationMetricPresentation> = {
    'case.expected_output_match': { label: '期望输出匹配', group: '输出质量', description: '实际输出是否与案例指定的期望输出一致。' },
    'factual.expected_fact_coverage': { label: '期望事实覆盖', group: '事实与证据', description: '待评输出是否包含案例要求出现的事实。' },
    'factual.forbidden_claim_absence': { label: '禁止事实边界', group: '事实与证据', description: '待评输出是否避免案例明确禁止的说法。' },
    'tool.contract_applicability': { label: '工具规则适用性', group: '工具调用', description: '本案例是否配置了需要检查的工具契约。' },
    'tool.forbidden_call_compliance': { label: '禁止工具调用', group: '工具调用', description: '禁止使用工具的案例中是否没有发生工具调用。' },
    'tool.expected_call_coverage': { label: '必需工具调用', group: '工具调用', description: '案例要求的每个工具是否都成功完成调用。' },
    'tool.key_argument_contract_compliance': { label: '工具参数契约', group: '工具调用', description: '工具名称、状态和关键参数是否符合案例契约。' },
    'tool.fixture_result_adoption': { label: '工具结果采用', group: '工具调用', description: '工具返回的关键事实是否被最终输出采用。' },
    'tool.allowed_call_compliance': { label: '允许工具范围', group: '工具调用', description: '实际调用是否全部位于案例允许的工具白名单内。' },
    'workflow.required_tool_call_coverage': { label: '工作流必需工具', group: '工作流', description: '固定工作流声明的必需工具是否完成调用。' },
    'workflow.tool_degradation_compliance': { label: '工具降级合规', group: '工作流', description: '可降级工具失败后，工作流是否按约定成功降级。' },
    'workflow.external_effect_interception': { label: '外部副作用拦截', group: '安全与权限', description: '未确认的外部副作用是否被正确阻断。' },
    'workflow.required_state_transition_coverage': { label: '必需状态迁移', group: '工作流', description: '运行是否经历案例要求的状态迁移。' },
    'workflow.forbidden_state_transition_compliance': { label: '禁止状态迁移', group: '工作流', description: '运行是否避免案例禁止的状态迁移。' },
    'rubric.required_output_path_coverage': { label: '必需输出字段', group: '输出结构', description: '输出是否包含案例要求的字段或路径。' },
    'rubric.expected_output_value_coverage': { label: '期望字段值', group: '输出结构', description: '输出字段值是否符合案例指定的期望值。' },
    'rubric.forbidden_output_text_absence': { label: '禁止输出文本', group: '输出结构', description: '输出是否避免案例禁止出现的文本。' },
    'rubric.question_count_compliance': { label: '题目数量合规', group: '输出结构', description: '生成的问题数量是否符合案例要求。' },
    'budget.latency_compliance': { label: '延迟预算合规', group: '成本与性能', description: '实际运行延迟是否不超过案例预算。' },
    'budget.token_compliance': { label: 'Token 预算合规', group: '成本与性能', description: '本次运行消耗的 Token 是否不超过案例预算。' },
    'runtime.tool_execution_success_rate': { label: '工具执行成功率', group: '运行可靠性', description: '实际执行的工具调用中成功完成的比例。' },
    'runtime.tool_failure_rate': { label: '工具失败率', group: '运行可靠性', description: '实际执行的工具调用中失败的比例。' },
    'runtime.tool_blocked_rate': { label: '工具阻断率', group: '安全与权限', description: '被权限、审批或策略正确阻断的工具调用比例。' },
    'runtime.tool_p95_duration_ms': { label: '工具 P95 耗时', group: '成本与性能', description: '已执行工具调用的 P95 耗时。' },
    'runtime.tool_retry_rate': { label: '工具重试率', group: '运行可靠性', description: '发生过重复尝试的工具调用比例。' },
    'runtime.dependency_failure_rate': { label: '依赖失败率', group: '运行可靠性', description: '外部依赖最终失败的比例。' },
    'runtime.external_io_timeout_rate': { label: '外部 IO 超时率', group: '运行可靠性', description: '外部 IO 调用被分类为超时的比例。' },
    'model.call_amplification': { label: '模型调用放大率', group: '成本与性能', description: '物理 Provider 请求数相对逻辑模型调用数的放大倍数。' },
    'model.fallback_rate': { label: '模型降级率', group: '成本与性能', description: '进入备用模型候选的请求比例。' },
    'model.timeout_rate': { label: '模型超时率', group: '运行可靠性', description: '模型请求被分类为超时的比例。' },
    'model.p95_latency_ms': { label: '模型 P95 延迟', group: '成本与性能', description: '模型物理请求的 P95 耗时。' },
    'context.authoritative_truncation_rate': { label: '权威上下文截断率', group: '运行可靠性', description: '权威上下文发生静默截断的比例。' },
    'rag.retrieval_success_rate': { label: '检索成功率', group: '检索与记忆', description: '检索调用成功返回终态的比例。' },
    'rag.empty_result_rate': { label: '检索空结果率', group: '检索与记忆', description: '检索成功但没有返回结果的比例。' },
    'rag.adopted_rate': { label: '检索结果采用率', group: '检索与记忆', description: '有采用证据的检索结果中被 Agent 使用的比例。' },
    'memory.search_hit_rate': { label: '记忆命中率', group: '检索与记忆', description: '记忆搜索成功且至少返回一条结果的比例。' },
    'memory.adopted_rate': { label: '记忆采用率', group: '检索与记忆', description: '有采用证据的记忆检索中被 Agent 使用的比例。' },
    'memory.write_duplication_rate': { label: '记忆重复写入率', group: '检索与记忆', description: '带幂等键的记忆写入中重复键的比例。' },
    'observability.critical_trace_completeness': { label: 'Trace 完整率', group: '可观测性', description: '关键 Trace、版本和错误分类字段完整的比例。' },
    'hard_gate.cross_user_access': { label: '跨用户访问', group: '安全门禁', description: '是否发生跨用户数据或资源访问。' },
    'hard_gate.unapproved_external_action': { label: '未审批外部操作', group: '安全门禁', description: '是否执行了未经确认的外部副作用操作。' },
    'hard_gate.credential_leak': { label: '凭据泄漏', group: '安全门禁', description: '输出或轨迹中是否泄漏凭据等敏感信息。' },
    'hard_gate.prompt_injection_success': { label: '提示注入成功', group: '安全门禁', description: '是否被提示注入绕过既定安全边界。' },
    'hard_gate.high_severity_resume_fabrication': { label: '高严重度简历虚构', group: '安全门禁', description: '是否生成未经证据支持的高严重度简历事实。' },
    'hard_gate.duplicate_external_side_effect': { label: '重复外部副作用', group: '安全门禁', description: '是否因重试等原因重复执行外部副作用。' },
    'hard_gate.post_cancel_external_write': { label: '取消后外部写入', group: '安全门禁', description: '任务取消后是否仍发生外部写入。' },
    'hard_gate.checkpoint_integrity_violation': { label: 'Checkpoint 完整性', group: '安全门禁', description: '检查点数据是否发生完整性违规。' },
    'hard_gate.evaluation_data_contamination': { label: '评测数据污染', group: '安全门禁', description: '评测运行是否污染了生产或其他案例数据。' },
    'deepeval.tool_correctness': { label: 'DeepEval 工具正确性', group: 'DeepEval Judge', description: '实际工具调用是否符合案例声明的必需工具和关键参数。' },
    'deepeval.business_rubric': { label: 'DeepEval 业务目标符合度', group: 'DeepEval Judge', description: '实际输出是否满足案例业务目标，并保持在 Golden 事实边界内。' },
};

function humanizeMetricName(metricName: string): string {
    return metricName
        .split(/[._]/g)
        .filter(Boolean)
        .map((part) => part.replace(/(^|[- ])\w/g, (value) => value.toUpperCase()))
        .join(' / ');
}

/** Turns an internal metric key into a readable label while preserving the raw key separately. */
export function presentEvaluationMetric(metricName: string): EvaluationMetricPresentation {
    return METRIC_PRESENTATIONS[metricName] ?? {
        label: humanizeMetricName(metricName),
        group: '自定义规则',
        description: '该规则由当前评测套件定义，具体判断请查看技术字段和证据。',
    };
}

/** Keeps internal status codes out of the primary score label. */
export function evaluationScoreStatusLabel(status: string): string {
    const normalized = status.trim().toLowerCase();
    if (isEvaluationScoreNotApplicable(normalized)) return '不适用';
    if (SCORE_PASSED.has(normalized)) return '通过';
    if (SCORE_FAILED.has(normalized)) return '未通过';
    return '待复核';
}

export interface EvaluationScorePage {
    scores: EvaluationScore[];
    page: number;
    totalPages: number;
}

/** Returns a bounded ten-rule page without changing the score order from the evaluation service. */
export function paginateEvaluationScores(
    scores: EvaluationScore[],
    requestedPage: number,
    pageSize = EVALUATION_SCORE_RULE_PAGE_SIZE,
): EvaluationScorePage {
    const safePageSize = Math.max(1, Math.floor(pageSize));
    const totalPages = Math.ceil(scores.length / safePageSize);
    const page = totalPages === 0 ? 1 : Math.min(Math.max(1, Math.floor(requestedPage)), totalPages);
    const start = (page - 1) * safePageSize;

    return {
        scores: scores.slice(start, start + safePageSize),
        page,
        totalPages,
    };
}

export interface EvaluationScoreSummary {
    source: string;
    label: string;
    scores: EvaluationScore[];
    passed: number;
    failed: number;
    review: number;
    notApplicable: number;
    hardGateFailures: number;
}

export interface EvaluationCaseOutcomeSummary {
    statusLabel: string;
    statusTone: EvaluationDisplayOutcome;
    hardGateLabel: string;
    hardGateTone: EvaluationDisplayOutcome;
    reviewLabel: string;
    reviewTone: EvaluationDisplayOutcome;
    reviewReasons: string[];
    metrics: Array<{ label: string; value: string }>;
}

export interface EvaluationReviewGuidance {
    title: string;
    checks: Array<{
        label: string;
        detail: string;
        outcome: EvaluationStatusTone;
        scopeLabel: '纳入治理' | '未纳入治理' | '不适用';
        actionLabel: '自动检查' | '人工确认' | '无需处理';
    }>;
    recommendation: string;
}

const REVIEW_RULE_LABELS: Record<string, string> = {
    'budget.latency_compliance': '延迟预算',
    'budget.token_compliance': 'Token 预算',
    'tool.expected_call_coverage': '必需工具调用',
    'tool.key_argument_contract_compliance': '工具参数契约',
    'tool.allowed_call_compliance': '允许工具范围',
    'tool.fixture_result_adoption': '工具结果采用',
    'factual.expected_fact_coverage': '期望事实覆盖',
    'factual.forbidden_claim_absence': '禁止事实边界',
};

const REVIEW_RULE_LOCATIONS: Record<string, string> = {
    'budget.latency_compliance': '案例输入 / 证据 JSON → expected.latency_budget_ms\n案例运行字段 → latency_ms',
    'budget.token_compliance': '案例输入 / 证据 JSON → expected.token_budget\n案例运行字段 → token_usage.total_tokens（没有时看 input_tokens + output_tokens）',
    'factual.expected_fact_coverage': '案例输入 / 证据 JSON → expected.expected_facts\n待评输出 JSON → 搜索这些事实',
    'tool.allowed_call_compliance': '案例输入 / 证据 JSON → expected.allowed_tool_calls\n案例记录 → record.tool_calls[].tool_name',
    'tool.fixture_result_adoption': '案例输入 / 证据 JSON → expected.quality_rubric.tool_result_facts\n待评输出 JSON → 搜索工具结果事实',
    'tool.expected_call_coverage': '案例输入 / 证据 JSON → expected.expected_tool_calls\n案例记录 → record.tool_calls[]',
    'tool.key_argument_contract_compliance': '案例输入 / 证据 JSON → expected.quality_rubric.expected_tool_arguments\n案例记录 → record.tool_calls[]',
    'factual.forbidden_claim_absence': '不需要翻找 JSON\n系统已按“禁止出现的说法”逐项检查待评输出',
};

/** Builds a bounded checklist from already sanitized case contracts, trace facts, and scores. */
export function buildEvaluationReviewGuidance(detail: EvaluationCaseRunDetail): EvaluationReviewGuidance {
    const expected = detail.case.expected ?? {};
    const expectedTools = strings(expected.expected_tool_calls);
    const expectedFacts = strings(expected.expected_facts);
    const completedTools = new Set(
        (detail.record.tool_calls ?? [])
            .filter((call) => call.status === 'completed')
            .map((call) => call.tool_name),
    );
    const missingTools = expectedTools.filter((tool) => !completedTools.has(tool));
    const failedRules = detail.scores.filter((score) => (
        score.source === 'deterministic' && evaluationScoreOutcome(score.status) === 'failed'
    ));
    const actualToolCalls = (detail.record.tool_calls ?? [])
        .map((call) => `${call.tool_name}（${call.status}）`)
        .join('、') || '无工具调用';
    const totalTokens = tokenUsageTotal(detail.token_usage);
    const configuredMetricNames = new Set<string>();
    const configuredChecks: EvaluationReviewGuidance['checks'] = [];
    const addConfiguredCheck = (metricName: string, label: string, detailText: string) => {
        const score = detail.scores.find((item) => item.source === 'deterministic' && item.metric_name === metricName);
        const outcome = score ? evaluationScoreOutcome(score.status) : 'review';
        configuredMetricNames.add(metricName);
        configuredChecks.push({
            label: `${label} · ${metricName}`,
            detail: `${detailText}\n自动检查状态：${reviewCheckStatusLabel(outcome, Boolean(score))}`,
            outcome,
            scopeLabel: '纳入治理',
            actionLabel: '自动检查',
        });
    };
    if (hasFiniteNumber(expected.latency_budget_ms)) {
        addConfiguredCheck(
            'budget.latency_compliance',
            REVIEW_RULE_LABELS['budget.latency_compliance'],
            `${REVIEW_RULE_LOCATIONS['budget.latency_compliance']}。${ruleValueDetail('budget.latency_compliance', expected, detail, actualToolCalls, totalTokens)}`,
        );
    }
    if (hasFiniteNumber(expected.token_budget)) {
        addConfiguredCheck(
            'budget.token_compliance',
            REVIEW_RULE_LABELS['budget.token_compliance'],
            `${REVIEW_RULE_LOCATIONS['budget.token_compliance']}。${ruleValueDetail('budget.token_compliance', expected, detail, actualToolCalls, totalTokens)}`,
        );
    }
    if (expectedFacts.length) {
        addConfiguredCheck(
            'factual.expected_fact_coverage',
            REVIEW_RULE_LABELS['factual.expected_fact_coverage'],
            `${REVIEW_RULE_LOCATIONS['factual.expected_fact_coverage']}。${ruleValueDetail('factual.expected_fact_coverage', expected, detail, actualToolCalls, totalTokens)}`,
        );
    }
    const ruleChecks = failedRules.filter((score) => !configuredMetricNames.has(score.metric_name)).map((score) => ({
        label: `${REVIEW_RULE_LABELS[score.metric_name] ?? score.metric_name} · ${score.metric_name}`,
        detail: `${REVIEW_RULE_LOCATIONS[score.metric_name] ?? '案例详情的对应执行记录和输出'}。${ruleValueDetail(score.metric_name, expected, detail, actualToolCalls, totalTokens)}`,
        outcome: 'failed' as const,
        scopeLabel: '纳入治理' as const,
        actionLabel: '自动检查' as const,
    }));
    const checks: EvaluationReviewGuidance['checks'] = [
        ...(expectedTools.length ? [{
            label: '案例要求的工具',
            detail: expectedTools.join('、'),
            outcome: missingTools.length ? 'failed' as const : 'passed' as const,
            scopeLabel: '纳入治理' as const,
            actionLabel: '自动检查' as const,
        }] : []),
        ...(expectedTools.length ? [{
            label: '实际工具执行',
            detail: missingTools.length
                ? `未完成：${missingTools.join('、')}`
                : `已完成：${expectedTools.join('、')}`,
            outcome: missingTools.length ? 'failed' as const : 'passed' as const,
            scopeLabel: '纳入治理' as const,
            actionLabel: '自动检查' as const,
        }] : []),
        ...(expectedFacts.length ? [{
            label: '输出需确认的事实',
            detail: expectedFacts.join('、'),
            outcome: 'review' as const,
            scopeLabel: '纳入治理' as const,
            actionLabel: '人工确认' as const,
        }] : []),
        ...configuredChecks,
        ...ruleChecks,
    ];
    if (missingTools.length) {
        const derivedCount = failedRules.filter((score) => REVIEW_RULE_LABELS[score.metric_name]).length;
        return {
            title: '建议确认：工具选择遗漏',
            checks,
            recommendation: `确认 ${missingTools.join('、')} 未执行且输出未采用工具结果后，标注一次“问题分类：工具选择错误”即可。${derivedCount > 1 ? `${derivedCount} 项自动失败由同一遗漏派生，无需逐项标注。` : ''} 最终处理选择“确认不通过”。`,
        };
    }
    return {
        title: '请按案例要求核对输出与执行事实',
        checks: checks.length ? checks : [{
            label: '自动复核原因',
            detail: detail.review_reasons.map(evaluationReviewReasonLabel).join('、') || '请检查评分与运行轨迹',
            outcome: 'review',
            scopeLabel: '未纳入治理',
            actionLabel: '无需处理',
        }],
        recommendation: '确认事实、工具和状态约束是否满足；一个人工标注用于记录主要归因，再保存最终处理结论。',
    };
}

function ruleValueDetail(
    metricName: string,
    expected: Record<string, unknown>,
    detail: EvaluationCaseRunDetail,
    actualToolCalls: string,
    totalTokens: number | null,
): string {
    if (metricName === 'budget.latency_compliance') {
        return `当前：latency_ms=${detail.latency_ms ?? '未返回'}\n预算=${expected.latency_budget_ms ?? '未配置'} ms\n判断实际延迟是否 ≤ 预算。`;
    }
    if (metricName === 'budget.token_compliance') {
        return `当前：实际 Token=${totalTokens ?? '未返回'}\n预算=${expected.token_budget ?? '未配置'}\n判断实际 Token 是否 ≤ 预算。`;
    }
    if (metricName === 'factual.expected_fact_coverage') {
        const facts = strings(expected.expected_facts);
        const detected = phrasesInOutput(facts, primaryOutputProjection(detail.actual_output, expected));
        return `应出现：${facts.join('、') || '未配置'}\n自动检查检测到：${detected.join('、') || '无'}\n${primaryOutputScope(expected)}\n不需要先读完整 JSON。`;
    }
    if (metricName === 'factual.forbidden_claim_absence') {
        const forbidden = strings(expected.forbidden_claims);
        const detected = phrasesInOutput(forbidden, primaryOutputProjection(detail.actual_output, expected));
        return `禁止出现：${forbidden.join('、') || '未配置'}\n自动检查检测到：${detected.join('、') || '无'}\n${primaryOutputScope(expected)}\n若检测结果符合你的判断，直接按“事实虚构”记录，无需翻找输出 JSON。`;
    }
    if (metricName === 'tool.allowed_call_compliance') {
        const allowedTools = new Set(strings(expected.allowed_tool_calls));
        const invalidTools = (detail.record.tool_calls ?? [])
            .map((call) => call.tool_name)
            .filter((toolName) => !allowedTools.has(toolName));
        return `允许工具：${[...allowedTools].join('、') || '未配置'}\n实际记录：${actualToolCalls}\n自动检查检测到越界工具：${invalidTools.length ? [...new Set(invalidTools)].join('、') : '无'}\n只要出现允许列表外的工具，就不通过。`;
    }
    if (metricName === 'tool.fixture_result_adoption') {
        const rubric = isRecord(expected.quality_rubric) ? expected.quality_rubric : {};
        const facts = strings(rubric.tool_result_facts);
        const detected = phrasesInOutput(facts, primaryOutputProjection(detail.actual_output, expected));
        return `工具结果事实：${facts.join('、') || '未配置'}\n自动检查检测到：${detected.join('、') || '无'}\n${primaryOutputScope(expected)}\n在待评输出中确认是否采用，而不是只确认工具调用成功。`;
    }
    if (metricName === 'tool.expected_call_coverage') {
        return `必需工具：${strings(expected.expected_tool_calls).join('、') || '未配置'}；实际记录：${actualToolCalls}。每个必需工具都应有 completed 记录。`;
    }
    if (metricName === 'tool.key_argument_contract_compliance') {
        return `去 record.tool_calls[] 对照工具参数契约；重点确认工具名称、调用状态和参数是否符合 expected.quality_rubric.expected_tool_arguments。`;
    }
    return '对照该规则的证据引用和实际输出，确认失败是否成立。';
}

function hasFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

function reviewCheckStatusLabel(outcome: EvaluationStatusTone, hasScore: boolean): string {
    if (outcome === 'passed') return '通过';
    if (outcome === 'failed') return '未通过';
    return hasScore ? '待复核' : '待自动检查';
}

/** One user-facing status for a scoring or review source, kept separate from raw numeric metrics. */
/** Explains whether a tool summary has a meaningful denominator for this case. */
export function summarizeEvaluationToolApplicability(
    detail: Pick<EvaluationCaseRunDetail, 'case' | 'record'>,
): { label: string; detail: string } {
    const expected = detail.case.expected?.expected_tool_calls;
    const allowed = detail.case.expected?.allowed_tool_calls;
    const observed = detail.record?.tool_calls;
    const hasExpectedTools = Array.isArray(expected) && expected.length > 0;
    const hasAllowedTools = Array.isArray(allowed) && allowed.length > 0;
    const hasObservedTools = Array.isArray(observed) && observed.length > 0;

    if (!hasExpectedTools && !hasAllowedTools && !hasObservedTools) {
        return { label: '工具调用', detail: '不适用（本案例未要求工具）' };
    }
    return { label: '工具调用', detail: '已纳入工具调用指标' };
}

export interface EvaluationScoreStatusSummary {
    key: 'automatic_rules' | 'llm_judge' | 'human_review';
    label: string;
    detail: string;
    tone: EvaluationStatusTone;
}

/** Keeps the case-list semantic result readable without leaking the mixed-unit internal aggregate. */
export function summarizeEvaluationSemanticStatus(
    caseRun: Pick<EvaluationCaseRun, 'semantic_evaluated' | 'semantic_success'> &
        Partial<Pick<EvaluationCaseRun, 'needs_review' | 'review_status'>>,
): { label: string; tone: EvaluationStatusTone } {
    if (caseRun.needs_review && (caseRun.review_status ?? 'pending') === 'pending') {
        return { label: '待人工复核', tone: 'review' };
    }
    if (caseRun.semantic_evaluated === false) return { label: '未评测', tone: 'neutral' };
    if (caseRun.semantic_success === true) return { label: '通过', tone: 'passed' };
    if (caseRun.semantic_success === false) return { label: '未通过', tone: 'failed' };
    return { label: '暂无结论', tone: 'neutral' };
}

const SOURCE_LABELS: Record<string, string> = {
    deterministic: '确定性规则',
    deepeval: 'DeepEval',
    judge: 'LLM Judge',
    human: '人工标注',
    user_feedback: '用户反馈',
};

const REVIEW_REASON_LABELS: Record<string, string> = {
    runtime_failure: '运行失败',
    trace_incomplete: 'Trace 不完整',
    hard_gate_failure: '硬门禁失败',
    semantic_not_evaluated: '语义未评测',
    semantic_failure: '语义评测失败',
    tool_selection_execution_conflict: '工具选择/执行冲突',
    dependency_failure_with_success: '依赖失败但业务声称成功',
    external_approval_evidence_missing: '外部审批证据缺失',
    sampled_review: '命中人工抽样',
    judge_disagreement: 'Judge 分歧',
};

const SCORE_PASSED = new Set(['passed', 'pass', 'succeeded', 'success']);
const SCORE_FAILED = new Set(['failed', 'fail', 'blocked', 'error']);
const SCORE_NOT_APPLICABLE = new Set(['not_applicable', 'not-applicable', 'n/a', 'na', 'skipped']);

/** Maps an evaluator source to a stable product-facing label. */
export function evaluationScoreSourceLabel(source: string): string {
    return SOURCE_LABELS[source] ?? source;
}

/** Maps a governed review code without exposing the backend enum as the primary UI. */
export function evaluationReviewReasonLabel(reason: string): string {
    return REVIEW_REASON_LABELS[reason] ?? reason;
}

/** Returns whether a rule was intentionally not evaluated because its prerequisites were absent. */
export function isEvaluationScoreNotApplicable(status: string): boolean {
    return SCORE_NOT_APPLICABLE.has(status.trim().toLowerCase());
}

/** Normalizes heterogeneous applicable score status values to the three states used by the UI. */
export function evaluationScoreOutcome(status: string): EvaluationDisplayOutcome {
    const normalized = status.trim().toLowerCase();
    if (SCORE_PASSED.has(normalized)) return 'passed';
    if (SCORE_FAILED.has(normalized)) return 'failed';
    return 'review';
}

/** Groups scores by source and calculates a compact, source-local verdict. */
export function summarizeEvaluationScores(scores: EvaluationScore[]): EvaluationScoreSummary[] {
    const grouped = new Map<string, EvaluationScore[]>();
    for (const score of scores) {
        const group = grouped.get(score.source) ?? [];
        group.push(score);
        grouped.set(score.source, group);
    }
    return [...grouped.entries()].map(([source, group]) => {
        const applicableScores = group.filter((score) => !isEvaluationScoreNotApplicable(score.status));
        const outcomes = applicableScores.map((score) => evaluationScoreOutcome(score.status));
        return {
            source,
            label: evaluationScoreSourceLabel(source),
            scores: group,
            passed: outcomes.filter((outcome) => outcome === 'passed').length,
            failed: outcomes.filter((outcome) => outcome === 'failed').length,
            review: outcomes.filter((outcome) => outcome === 'review').length,
            notApplicable: group.length - applicableScores.length,
            hardGateFailures: applicableScores.filter(
                (score) => score.hard_gate && evaluationScoreOutcome(score.status) === 'failed',
            ).length,
        };
    });
}

/** Describes each scoring source without treating an intentionally disabled Judge as missing data. */
export function summarizeEvaluationScoreStatuses(
    detail: EvaluationCaseRunDetail,
    { includeJudges }: { includeJudges: boolean },
): EvaluationScoreStatusSummary[] {
    const deterministic = detail.scores.filter((score) => score.source === 'deterministic');
    const judge = detail.scores.filter((score) => score.source === 'judge' || score.source === 'deepeval');
    const deterministicNotApplicable = deterministic.filter((score) => isEvaluationScoreNotApplicable(score.status)).length;
    const applicableDeterministic = deterministic.filter((score) => !isEvaluationScoreNotApplicable(score.status));
    const deterministicOutcomes = applicableDeterministic.map((score) => evaluationScoreOutcome(score.status));
    const deterministicFailed = deterministicOutcomes.filter((outcome) => outcome === 'failed').length;
    const deterministicReview = deterministicOutcomes.filter((outcome) => outcome === 'review').length;
    const deterministicPassed = deterministic.length - deterministicFailed - deterministicReview - deterministicNotApplicable;
    const automaticRules: EvaluationScoreStatusSummary = deterministic.length === 0
        ? { key: 'automatic_rules', label: '自动规则', detail: '暂无规则结果', tone: 'neutral' }
        : deterministicFailed > 0
            ? { key: 'automatic_rules', label: '自动规则', detail: `${deterministicFailed} 项未通过 / ${deterministic.length} 项${deterministicNotApplicable ? `（${deterministicNotApplicable} 项不适用）` : ''}`, tone: 'failed' }
            : deterministicReview > 0
                ? { key: 'automatic_rules', label: '自动规则', detail: `${deterministicReview} 项待复核 / ${deterministic.length} 项${deterministicNotApplicable ? `（${deterministicNotApplicable} 项不适用）` : ''}`, tone: 'review' }
                : deterministicPassed === 0
                    ? { key: 'automatic_rules', label: '自动规则', detail: `不适用（${deterministicNotApplicable} 项）`, tone: 'neutral' }
                    : { key: 'automatic_rules', label: '自动规则', detail: `通过（${deterministicPassed} 项${deterministicNotApplicable ? `，${deterministicNotApplicable} 项不适用` : ''}）`, tone: 'passed' };
    const judgeStatus: EvaluationScoreStatusSummary = !includeJudges
        ? { key: 'llm_judge', label: 'LLM Judge', detail: '未启用（快速冒烟默认不调用 Judge）', tone: 'neutral' }
        : judge.length === 0
            ? { key: 'llm_judge', label: 'LLM Judge', detail: '已启用，暂无结果', tone: 'neutral' }
            : judge.some((score) => evaluationScoreOutcome(score.status) === 'failed')
                ? { key: 'llm_judge', label: 'LLM Judge', detail: '存在未通过结果', tone: 'failed' }
                : judge.some((score) => evaluationScoreOutcome(score.status) === 'review')
                    ? { key: 'llm_judge', label: 'LLM Judge', detail: '结果待复核', tone: 'review' }
                    : { key: 'llm_judge', label: 'LLM Judge', detail: `通过（${judge.length} 项）`, tone: 'passed' };
    const humanReview: EvaluationScoreStatusSummary = detail.needs_review
        ? { key: 'human_review', label: '人工复核', detail: `需要处理：${reviewStatusLabel(detail.review_status)}`, tone: 'review' }
        : detail.annotations.length > 0
            ? { key: 'human_review', label: '人工复核', detail: `已有人工作出裁决（${detail.annotations.length} 项）`, tone: 'passed' }
            : { key: 'human_review', label: '人工复核', detail: '不需要', tone: 'passed' };
    return [automaticRules, judgeStatus, humanReview];
}

/** Produces a non-content summary so output stays compact until the user asks for details. */
export function summarizeEvaluationOutput(output: unknown): string {
    if (output == null) return '未返回实际输出';
    if (typeof output === 'string') return `文本输出 · ${output.length.toLocaleString('zh-CN')} 字符`;
    if (Array.isArray(output)) return `列表输出 · ${output.length.toLocaleString('zh-CN')} 项`;
    if (typeof output === 'object') {
        const record = output as Record<string, unknown>;
        const questions = Array.isArray(record.questions) ? `，含 ${record.questions.length} 个问题` : '';
        return `结构化输出 · ${Object.keys(record).length.toLocaleString('zh-CN')} 个字段${questions}`;
    }
    return `输出类型：${typeof output}`;
}

/** Builds the top-level case verdict without assuming a single adapter payload shape. */
export function summarizeEvaluationCaseOutcome(detail: EvaluationCaseRunDetail): EvaluationCaseOutcomeSummary {
    const awaitingReview = detail.needs_review && ['pending', 'rerun_requested'].includes(detail.review_status);
    const runtimeSucceeded = !awaitingReview && (detail.status === 'succeeded' || detail.record.outcome?.runtime_success === true);
    const statusTone: EvaluationDisplayOutcome = awaitingReview ? 'review' : runtimeSucceeded ? 'passed' : detail.status === 'failed' ? 'failed' : 'review';
    const estimatedCost = Number(detail.record.estimated_cost_usd);
    const totalTokens = totalTokenUsage(detail.token_usage);
    const metrics = [
        { label: '延迟', value: `${Math.round(detail.latency_ms).toLocaleString('zh-CN')} ms` },
        ...(totalTokens == null ? [] : [{ label: 'Token', value: totalTokens.toLocaleString('zh-CN') }]),
        ...(Number.isFinite(estimatedCost) ? [{ label: '成本', value: formatUsd(estimatedCost) }] : []),
    ];

    return {
        statusLabel: awaitingReview ? '待人工复核' : runtimeSucceeded ? '运行成功' : detail.status === 'failed' ? '运行失败' : `运行状态：${detail.status}`,
        statusTone,
        hardGateLabel: detail.hard_gate_passed ? '硬门禁通过' : '硬门禁未通过',
        hardGateTone: detail.hard_gate_passed ? 'passed' : 'failed',
        reviewLabel: detail.needs_review ? '需要人工复核' : '无需人工复核',
        reviewTone: detail.needs_review ? 'review' : 'passed',
        reviewReasons: detail.review_reasons.map(evaluationReviewReasonLabel),
        metrics,
    };
}

/** Formats a score value while retaining status-only evaluators. */
export function formatEvaluationScore(score: EvaluationScore): string {
    return score.value == null
        ? scoreStatusLabel(score.status)
        : Number.isFinite(score.value)
            ? score.value.toFixed(3)
            : scoreStatusLabel(score.status);
}

const RATE_METRICS = new Set([
    'quality.runtime_success_rate',
    'quality.semantic_evaluated_rate',
    'quality.semantic_success_rate',
    'quality.complete_success_rate',
    'governance.pending_review_rate',
    'factual.expected_fact_coverage',
    'factual.forbidden_claim_absence',
    'tool.expected_call_coverage',
    'tool.key_argument_contract_compliance',
    'tool.fixture_result_adoption',
    'tool.allowed_call_compliance',
    'workflow.required_tool_call_coverage',
    'workflow.tool_degradation_compliance',
    'workflow.external_effect_interception',
    'runtime.tool_execution_success_rate',
    'runtime.tool_failure_rate',
    'runtime.tool_blocked_rate',
    'runtime.tool_retry_rate',
    'runtime.dependency_failure_rate',
    'runtime.external_io_timeout_rate',
    'model.fallback_rate',
    'model.timeout_rate',
    'context.authoritative_truncation_rate',
    'rag.retrieval_success_rate',
    'rag.empty_result_rate',
    'rag.adopted_rate',
    'memory.search_hit_rate',
    'memory.adopted_rate',
    'memory.write_duplication_rate',
    'observability.critical_trace_completeness',
]);

const DURATION_METRICS = new Set([
    'budget.latency_compliance',
    'runtime.tool_p95_duration_ms',
    'model.p95_latency_ms',
]);

/** Formats the raw metric value with its unit; this is not a normalized score. */
export function formatEvaluationMetricValue(score: EvaluationScore): string {
    if (score.value == null || !Number.isFinite(score.value)) return scoreStatusLabel(score.status);
    if (RATE_METRICS.has(score.metric_name)) return `${(score.value * 100).toFixed(1)}%`;
    if (DURATION_METRICS.has(score.metric_name)) return `${Math.round(score.value).toLocaleString('zh-CN')} ms`;
    if (score.metric_name === 'model.call_amplification') return `${score.value.toFixed(2)}x`;
    return score.value.toLocaleString('zh-CN', { maximumFractionDigits: 3 });
}

/** Formats a regression delta using the metric's native unit. */
export function formatEvaluationMetricDelta(metricName: string, value: number): string {
    if (!Number.isFinite(value)) return '-';
    if (RATE_METRICS.has(metricName)) return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
    if (DURATION_METRICS.has(metricName)) return `${value >= 0 ? '+' : ''}${Math.round(value).toLocaleString('zh-CN')} ms`;
    if (metricName === 'model.call_amplification') return `${value >= 0 ? '+' : ''}${value.toFixed(2)}x`;
    return `${value >= 0 ? '+' : ''}${value.toLocaleString('zh-CN', { maximumFractionDigits: 3 })}`;
}

/** Formats an annotation without rendering unbounded evidence or comments in collapsed UI. */
export function summarizeEvaluationAnnotation(annotation: { adjudication: boolean; blind: boolean }): string {
    if (annotation.adjudication) return '专家裁决';
    return annotation.blind ? '盲测标注' : '人工标注';
}

function reviewStatusLabel(status: string): string {
    return ({
        not_required: '无需处理', pending: '待处理', approved: '人工确认通过',
        rejected: '人工确认不通过', waived: '已豁免', rerun_requested: '待重跑',
    } as Record<string, string>)[status] ?? status;
}

function scoreStatusLabel(status: string): string {
    if (isEvaluationScoreNotApplicable(status)) return '不适用';
    const outcome = evaluationScoreOutcome(status);
    return outcome === 'passed' ? '通过' : outcome === 'failed' ? '未通过' : '待复核';
}

function totalTokenUsage(usage: Record<string, number>): number | null {
    const directTotal = usage.total_tokens ?? usage.total ?? usage.token_total;
    if (typeof directTotal === 'number' && Number.isFinite(directTotal)) return Math.round(directTotal);
    const values = Object.values(usage).filter((value) => Number.isFinite(value) && value >= 0);
    return values.length ? Math.round(values.reduce((total, value) => total + value, 0)) : null;
}

function formatUsd(value: number): string {
    return `$${value.toFixed(value < 0.01 ? 4 : 2)}`;
}

function strings(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function tokenUsageTotal(usage: Record<string, number>): number | null {
    const direct = usage.total_tokens ?? usage.total ?? usage.token_total;
    if (typeof direct === 'number' && Number.isFinite(direct)) return Math.round(direct);
    const input = usage.input_tokens;
    const output = usage.output_tokens;
    if (typeof input === 'number' && typeof output === 'number') return Math.round(input + output);
    return null;
}

function phrasesInOutput(phrases: string[], output: unknown): string[] {
    const normalizedOutput = normalizeForContainment(output);
    return phrases.filter((phrase) => normalizedOutput.includes(normalizeForContainment(phrase)));
}

function primaryOutputScope(expected: Record<string, unknown>): string {
    const rubric = isRecord(expected.quality_rubric) ? expected.quality_rubric : {};
    if (!Object.prototype.hasOwnProperty.call(rubric, 'primary_output_paths')) {
        return '自动检查范围：待评输出 JSON 全部字段（旧案例兼容，未配置主输出路径）';
    }
    const paths = strings(rubric.primary_output_paths);
    return paths.length
        ? `自动检查范围：${paths.join('、')}（仅主输出，排除说明元数据）`
        : '自动检查范围：主输出路径配置无效，当前按空内容检查';
}

function primaryOutputProjection(output: unknown, expected: Record<string, unknown>): unknown {
    const rubric = isRecord(expected.quality_rubric) ? expected.quality_rubric : {};
    if (!Object.prototype.hasOwnProperty.call(rubric, 'primary_output_paths')) return output;
    const paths = strings(rubric.primary_output_paths);
    if (!paths.length || paths.some((path) => !path.trim())) return [];
    return paths.flatMap((path) => outputPathValues(output, path));
}

function outputPathValues(value: unknown, path: string): unknown[] {
    let current: unknown[] = [value];
    for (const part of path.split('.')) {
        if (!part) return [];
        const next: unknown[] = [];
        for (const item of current) {
            if (part === '[]') {
                if (Array.isArray(item)) next.push(...item);
            } else if (isRecord(item) && Object.prototype.hasOwnProperty.call(item, part)) {
                next.push(item[part]);
            }
        }
        current = next;
        if (!current.length) return [];
    }
    return current.filter((item) => item !== null && item !== '');
}

function normalizeForContainment(value: unknown): string {
    const serialized = typeof value === 'string' ? value : JSON.stringify(value) ?? '';
    return serialized.replace(/\s+/g, '').toLowerCase();
}

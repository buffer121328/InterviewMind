import { apiRequest, authFetch } from './config';

export type EvaluationAgentName =
    | 'interview_planner'
    | 'interview_turn'
    | 'interview_scoring'
    | 'resume_optimizer'
    | 'resume_analyzer';

export type EvaluationQuickModeName = 'quick' | 'standard' | 'release';

export interface EvaluationCatalogAgent {
    name: EvaluationAgentName;
    label: string;
    description: string;
    prompt_name: string;
    prompt_version: string;
    dataset_name: string;
    dataset_version: string;
    suite_name: string;
    rubric_version: string;
    case_count: number;
    latest_successful_run_id: string | null;
}

export interface EvaluationQuickMode {
    name: EvaluationQuickModeName;
    label: string;
    description: string;
    repetition_count: number;
    max_concurrency: number;
    max_budget_usd: number;
    max_cases: number | null;
    include_judges: boolean;
    human_review_rate: number;
}

export interface EvaluationCatalog {
    agents: EvaluationCatalogAgent[];
    modes: EvaluationQuickMode[];
    runs_enabled: boolean;
}

export interface EvaluationQuickRunRequest {
    agent_name: EvaluationAgentName;
    mode: EvaluationQuickModeName;
    /** Request-scoped credentials; callers must never log or render this object. */
    api_config: Record<string, unknown>;
    prompt_name?: string;
    prompt_version?: string;
    compare_production?: boolean;
}

export interface EvaluationOverview {
    run_count: number;
    runtime_success_rate: number | null;
    semantic_success_rate: number | null;
    complete_success_rate: number | null;
    hard_gate_pass_rate: number | null;
    factual_support_rate: number | null;
    tool_call_accuracy: number | null;
    judge_human_agreement: number | null;
    pending_review_count: number;
    regression_count: number;
    p95_latency_ms: number | null;
    token_delta_percent: number | null;
    trace_completeness_rate: number | null;
    trace_incomplete_count: number;
    tool_failure_rate: number | null;
    tool_execution_success_rate: number | null;
    tool_p95_duration_ms: number | null;
    dependency_failure_rate: number | null;
    external_io_timeout_rate: number | null;
    retrieval_empty_rate: number | null;
    external_effect_count: number;
    external_effect_blocked_count: number;
    approval_event_count: number;
    approval_violation_count: number;
    langfuse_reported_case_count: number;
    langfuse_failed_case_count: number;
}

export interface EvaluationDatasetCase {
    id: string;
    case_key: string;
    category: string;
    tags: string[];
    severity: 'low' | 'medium' | 'high' | 'critical';
    content_hash: string;
    created_at: string;
}

export interface EvaluationDataset {
    id: string;
    name: string;
    version: string;
    status: string;
    case_count: number;
    source: string;
    content_hash: string;
    created_at: string;
    locked_at: string | null;
}

export interface EvaluationDatasetDetail extends EvaluationDataset {
    cases: EvaluationDatasetCase[];
}

export interface EvaluationSuite {
    id: string;
    name: string;
    agent_name: string;
    description: string | null;
    dataset_version_id: string;
    rubric_version: string;
    gate_policy_id: string | null;
}

export interface EvaluationRunSummary {
    case_total?: number;
    completed_count?: number;
    failed_count?: number;
    hard_gate_failure_count?: number;
    needs_review_count?: number;
    progress?: number;
    complete_success_rate?: number | null;
    p95_latency_ms?: number | null;
    token_total?: number | null;
    trace_complete_count?: number;
    trace_incomplete_count?: number;
    trace_completeness_rate?: number | null;
    tool_call_total?: number;
    tool_call_completed_count?: number;
    tool_call_failed_count?: number;
    tool_failure_rate?: number | null;
    tool_execution_success_rate?: number | null;
    tool_p95_duration_ms?: number | null;
    external_effect_total?: number;
    external_effect_blocked_count?: number;
    approval_violation_count?: number;
    external_io_total?: number;
    external_io_failed_count?: number;
    external_io_timeout_count?: number;
    dependency_failure_rate?: number | null;
    external_io_timeout_rate?: number | null;
    approval_event_total?: number;
    retrieval_observed_case_count?: number;
    retrieval_empty_case_count?: number;
    retrieval_empty_rate?: number | null;
    langfuse_reported_case_count?: number;
    langfuse_failed_case_count?: number;
    [key: string]: unknown;
}

export interface EvaluationRun {
    id: string;
    suite_id: string;
    agent_run_id: string | null;
    agent_name: string;
    agent_version: string;
    prompt_name: string | null;
    prompt_version: string | null;
    model_config_hash: string;
    dataset_version: string;
    status: string;
    baseline_run_id: string | null;
    repetition_count: number;
    include_judges: boolean;
    budget: Record<string, unknown>;
    summary: EvaluationRunSummary;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
}

export interface EvaluationScore {
    id: string;
    case_run_id: string;
    metric_name: string;
    value: number | null;
    status: string;
    source: 'deterministic' | 'deepeval' | 'judge' | 'human' | 'user_feedback' | string;
    reason: string | null;
    severity: string;
    hard_gate: boolean;
    evidence_refs: string[];
    metric_version: string;
    created_at: string;
}

export interface EvaluationCaseRun {
    id: string;
    evaluation_run_id: string;
    case_id: string;
    repetition_index: number;
    status: string;
    trace_id: string | null;
    latency_ms: number;
    token_usage: Record<string, number>;
    hard_gate_passed: boolean;
    overall_score: number | null;
    error_category: string | null;
    needs_review: boolean;
}

export type EvaluationToolEffect = 'none' | 'read' | 'write' | 'external';
export type EvaluationToolStatus = 'requested' | 'started' | 'completed' | 'failed' | 'blocked' | 'skipped' | string;
export type EvaluationApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected' | string;

export interface EvaluationToolCall {
    call_id: string;
    sequence: number;
    event_type?: string;
    parent_call_id?: string | null;
    tool_name: string;
    effect: EvaluationToolEffect;
    status: EvaluationToolStatus;
    attempt: number;
    requires_confirmation: boolean;
    approval_status: EvaluationApprovalStatus;
    simulated: boolean;
    duration_ms?: number | null;
    error_type?: string | null;
    error_category?: string | null;
    evidence_refs: string[];
}

export interface EvaluationRetrieval {
    retrieval_id: string;
    sequence?: number | null;
    source_type: string;
    strategy?: string | null;
    result_count?: number | null;
    empty_result?: boolean | null;
    adopted: boolean;
    duration_ms?: number | null;
    error_category?: string | null;
}

export interface EvaluationExternalIo {
    call_id: string;
    sequence: number;
    event_type?: string;
    parent_call_id?: string | null;
    operation: string;
    dependency?: string | null;
    status: string;
    attempt: number;
    duration_ms?: number | null;
    item_count?: number | null;
    result_count?: number | null;
    adopted?: boolean | null;
    error_type?: string | null;
    error_category?: string | null;
}

export interface EvaluationModelCall {
    call_id: string;
    sequence: number;
    model_channel: string;
    model_member_hash: string;
    fallback_index: number;
    latency_ms: number;
    status: string;
    error_classification?: string | null;
}

export interface EvaluationApproval {
    approval_id: string;
    action: string;
    status: EvaluationApprovalStatus;
    call_id?: string | null;
    requested_sequence?: number | null;
    sequence?: number | null;
    evidence_refs: string[];
}

export interface EvaluationRunEvent {
    sequence: number;
    stage: string;
    event_type: string;
    status?: string | null;
    payload_summary: Record<string, unknown>;
}

export interface EvaluationTraceCompleteness {
    complete: boolean;
    score: number;
    missing: string[];
    trace_id_present: boolean;
    tool_terminal_states_complete: boolean;
    stable_error_categories: boolean;
    external_approval_status_present: boolean;
    agent_run_id_present: boolean;
}

export interface EvaluationObservabilitySummary {
    schema_version: number;
    tool_event_count: number;
    tool_call_summary: Record<string, unknown>;
    external_io_event_count: number;
    external_io_summary: Record<string, unknown>;
    approval_event_count: number;
    langfuse_reported?: boolean | null;
    langfuse_error?: string | null;
    trace_completeness: EvaluationTraceCompleteness;
}

export interface EvaluationRecord {
    final_status?: string;
    trace_id?: string | null;
    agent_run_id?: string | null;
    tool_calls?: EvaluationToolCall[];
    retrievals?: EvaluationRetrieval[];
    external_ios?: EvaluationExternalIo[];
    model_calls?: EvaluationModelCall[];
    approvals?: EvaluationApproval[];
    events?: EvaluationRunEvent[];
    observability?: EvaluationObservabilitySummary;
    recovery_count?: number;
    estimated_cost_usd?: number | null;
    error?: { classification?: string; message?: string; retryable?: boolean } | null;
    [key: string]: unknown;
}

export interface EvaluationCaseRunDetail extends EvaluationCaseRun {
    actual_output: unknown;
    pairwise_outputs: { A: unknown; B: unknown | null };
    record: EvaluationRecord;
    case: EvaluationDatasetCase & {
        input: Record<string, unknown>;
        expected: Record<string, unknown>;
    };
    scores: EvaluationScore[];
    annotations: EvaluationAnnotation[];
}

export interface EvaluationAnnotation {
    id: string;
    case_run_id: string;
    rubric_version: string;
    annotation_type: string;
    metric_name: string;
    value: unknown;
    labels: string[];
    evidence_spans: Array<{ start: number; end: number; text: string }>;
    comment: string | null;
    confidence: number | null;
    reviewer_key: string;
    blind: boolean;
    revision: number;
    adjudication: boolean;
    created_at: string;
}

export interface EvaluationCalibration {
    id: string;
    metric_name: string;
    judge_version: string;
    dataset_version: string;
    human_sample_count: number;
    statistics: Record<string, number | null>;
    threshold: number | null;
    status: string;
    created_at: string;
}

export interface EvaluationGatePolicy {
    id: string;
    name: string;
    version: string;
    hard_gates: string[];
    metric_thresholds: Record<string, number | { value: number; comparison: 'gte' | 'lte' | 'eq' }>;
    regression_tolerances: Record<string, unknown>;
    minimum_sample_size: number;
    status: string;
    created_at: string;
}

export interface EvaluationTrendPoint {
    run_id: string;
    created_at: string;
    environment: string;
    agent_name: string;
    agent_version: string;
    prompt_name: string | null;
    prompt_version: string | null;
    model_config_hash: string;
    dataset_version: string;
    average_score: number | null;
    minimum_score: number | null;
    score_spread: number | null;
    sample_count: number;
    complete_success_rate: number | null;
    p50_latency_ms: number | null;
    p95_latency_ms: number | null;
    token_total: number | null;
    p50_tokens: number | null;
    p95_tokens: number | null;
}

export interface EvaluationRegression {
    run_id: string;
    baseline_run_id: string | null;
    agent_name: string;
    agent_version: string;
    prompt_name: string | null;
    prompt_version: string | null;
    model_config_hash: string;
    dataset_version: string;
    severity: string;
    regression_count: number;
    failed_case_count: number;
    hard_gate_failure_count: number;
    hard_gate_blocked: boolean;
    metric_deltas: Record<string, number>;
    complete_success_rate_delta: number | null;
    p95_latency_ms_delta: number | null;
    created_at: string;
}

export interface EvaluationTrendFilters {
    agent_name?: string;
    agent_version?: string;
    prompt_name?: string;
    prompt_version?: string;
    model_config_hash?: string;
    dataset_version?: string;
    environment?: string;
    created_from?: string;
    created_to?: string;
}

export interface EvaluationCaseRunFilters {
    status?: string;
    error_category?: string;
    tool_name?: string;
    tool_effect?: EvaluationToolEffect;
    tool_status?: string;
    approval_status?: EvaluationApprovalStatus;
    has_external_side_effect?: boolean;
    trace_incomplete?: boolean;
    retrieval_empty?: boolean;
    needs_review?: boolean;
    hard_gate_passed?: boolean;
}

interface Page<T> { items: T[]; total: number; limit?: number; offset?: number }

function withQuery(path: string, values: object): string {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
    const query = params.toString();
    return query ? `${path}?${query}` : path;
}

export const evaluationApi = {
    /** Loads server-owned one-click presets and owner-scoped baseline availability. */
    catalog: () => apiRequest<EvaluationCatalog>('/api/evaluations/catalog'),
    overview: () => apiRequest<EvaluationOverview>('/api/evaluations/overview'),
    trends: (filters: EvaluationTrendFilters = {}) => apiRequest<{ items: EvaluationTrendPoint[] }>(withQuery('/api/evaluations/metrics/trends', filters)),
    regressions: () => apiRequest<Page<EvaluationRegression>>('/api/evaluations/regressions'),
    datasets: () => apiRequest<Page<EvaluationDataset>>('/api/evaluations/datasets?limit=200&offset=0'),
    getDataset: (id: string) => apiRequest<EvaluationDatasetDetail>(`/api/evaluations/datasets/${id}`),
    createDataset: (payload: Record<string, unknown>) => apiRequest<EvaluationDataset>('/api/evaluations/datasets', { method: 'POST', body: JSON.stringify(payload) }),
    updateDatasetStatus: (id: string, status: 'annotating' | 'calibrated' | 'retired') => apiRequest<EvaluationDataset>(`/api/evaluations/datasets/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
    lockDataset: (id: string) => apiRequest<EvaluationDataset>(`/api/evaluations/datasets/${id}/lock`, { method: 'POST' }),
    suites: () => apiRequest<Page<EvaluationSuite>>('/api/evaluations/suites'),
    createSuite: (payload: Record<string, unknown>) => apiRequest<EvaluationSuite>('/api/evaluations/suites', { method: 'POST', body: JSON.stringify(payload) }),
    runs: () => apiRequest<Page<EvaluationRun>>('/api/evaluations/runs?limit=200&offset=0'),
    getRun: (id: string) => apiRequest<EvaluationRun & { cases: EvaluationCaseRun[] }>(`/api/evaluations/runs/${id}`),
    createRun: (payload: Record<string, unknown>) => apiRequest<EvaluationRun>('/api/evaluations/runs', { method: 'POST', body: JSON.stringify(payload), headers: { 'Idempotency-Key': crypto.randomUUID() } }),
    /** Starts a real evaluation while the backend keeps API keys only in encrypted AgentRun payload. */
    quickRun: (payload: EvaluationQuickRunRequest, idempotencyKey: string) => apiRequest<EvaluationRun>('/api/evaluations/quick-runs', {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: { 'Idempotency-Key': idempotencyKey },
    }),
    cancelRun: (id: string) => apiRequest<Record<string, unknown>>(`/api/evaluations/runs/${id}/cancel`, { method: 'POST' }),
    retryRun: (id: string) => apiRequest<Record<string, unknown>>(`/api/evaluations/runs/${id}/retry-failed`, { method: 'POST' }),
    requestReview: (id: string, caseRunIds: string[] = [], failedOnly = true) => apiRequest<{ run_id: string; queued_count: number }>(`/api/evaluations/runs/${id}/request-review`, { method: 'POST', body: JSON.stringify({ case_run_ids: caseRunIds, failed_only: failedOnly }) }),
    caseRuns: (runId: string, filters: EvaluationCaseRunFilters = {}) => {
        const params = new URLSearchParams();
        for (const [key, value] of Object.entries(filters)) {
            if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
        }
        const suffix = params.toString() ? `?${params.toString()}` : '';
        return apiRequest<Page<EvaluationCaseRun>>(`/api/evaluations/runs/${runId}/cases${suffix}`);
    },
    caseRun: (id: string) => apiRequest<EvaluationCaseRunDetail>(`/api/evaluations/case-runs/${id}`),
    annotationQueue: () => apiRequest<Page<EvaluationCaseRun & { agent_name: string }>>('/api/evaluations/annotations/queue'),
    annotations: (caseRunId: string) => apiRequest<Page<EvaluationAnnotation>>(`/api/evaluations/case-runs/${caseRunId}/annotations`),
    addAnnotation: (caseRunId: string, payload: Record<string, unknown>) => apiRequest<EvaluationAnnotation>(`/api/evaluations/case-runs/${caseRunId}/annotations`, { method: 'POST', body: JSON.stringify(payload) }),
    adjudicate: (annotationId: string, payload: Record<string, unknown>) => apiRequest<EvaluationAnnotation>(`/api/evaluations/annotations/${annotationId}/adjudicate`, { method: 'POST', body: JSON.stringify(payload) }),
    createCandidateDataset: (caseRunId: string, payload: Record<string, unknown>) => apiRequest<EvaluationDataset>(`/api/evaluations/case-runs/${caseRunId}/candidate-dataset`, { method: 'POST', body: JSON.stringify(payload) }),
    calibrations: () => apiRequest<Page<EvaluationCalibration>>('/api/evaluations/calibrations'),
    createCalibration: (payload: Record<string, unknown>) => apiRequest<EvaluationCalibration>('/api/evaluations/calibrations', { method: 'POST', body: JSON.stringify(payload) }),
    simulateCalibration: (id: string, payload: Record<string, unknown>) => apiRequest<Record<string, number>>(`/api/evaluations/calibrations/${id}/simulate`, { method: 'POST', body: JSON.stringify(payload) }),
    gates: () => apiRequest<Page<EvaluationGatePolicy>>('/api/evaluations/gates'),
    createGate: (payload: Record<string, unknown>) => apiRequest<EvaluationGatePolicy>('/api/evaluations/gates', { method: 'POST', body: JSON.stringify(payload) }),
    gateCheck: (runId: string, policyId?: string) => apiRequest<Record<string, unknown>>(`/api/evaluations/runs/${runId}/gate-check${policyId ? `?policy_id=${encodeURIComponent(policyId)}` : ''}`, { method: 'POST' }),
    traceLink: (agentRunId: string) => apiRequest<{ available: boolean; url: string | null; message: string | null }>(`/api/agent-runs/${agentRunId}/trace-link`),
};

/** Downloads an authenticated HTML report without exposing the user id in the URL. */
export async function downloadEvaluationReport(runId: string): Promise<void> {
    const response = await authFetch(`/api/evaluations/runs/${runId}/report?format=html`);
    if (!response.ok) throw new Error(`报告导出失败: HTTP ${response.status}`);
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `evaluation-${runId}.html`;
    link.click();
    URL.revokeObjectURL(link.href);
}

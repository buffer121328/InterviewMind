import { apiRequest, authFetch } from './config';

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
    summary: Record<string, unknown>;
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

export interface EvaluationCaseRunDetail extends EvaluationCaseRun {
    actual_output: unknown;
    pairwise_outputs: { A: unknown; B: unknown | null };
    record: Record<string, unknown>;
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

interface Page<T> { items: T[]; total: number; limit?: number; offset?: number }

function withQuery(path: string, values: object): string {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
    const query = params.toString();
    return query ? `${path}?${query}` : path;
}

export const evaluationApi = {
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
    cancelRun: (id: string) => apiRequest<Record<string, unknown>>(`/api/evaluations/runs/${id}/cancel`, { method: 'POST' }),
    retryRun: (id: string) => apiRequest<Record<string, unknown>>(`/api/evaluations/runs/${id}/retry-failed`, { method: 'POST' }),
    requestReview: (id: string, caseRunIds: string[] = [], failedOnly = true) => apiRequest<{ run_id: string; queued_count: number }>(`/api/evaluations/runs/${id}/request-review`, { method: 'POST', body: JSON.stringify({ case_run_ids: caseRunIds, failed_only: failedOnly }) }),
    caseRuns: (runId: string) => apiRequest<Page<EvaluationCaseRun>>(`/api/evaluations/runs/${runId}/cases`),
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

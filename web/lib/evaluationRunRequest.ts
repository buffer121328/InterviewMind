export const MISSING_EVALUATION_MODEL_CONFIG_MESSAGE = '请先在模型设置中配置主模型与 Fast 模型';

export interface AdvancedEvaluationRunRequestInput<TApiConfig extends object> {
    suiteId: string;
    agentVersion: string;
    promptName: string | null;
    promptVersion: string | null;
    baselineRunId: string | null;
    modelConfigHash: string;
    apiConfig: TApiConfig | null;
    repetitionCount: number;
    maxConcurrency: number;
    maxBudgetUsd: number;
    caseIds: string[];
    includeJudges: boolean;
    humanReviewRate: number;
}

/** Builds the advanced-run payload without persisting or rendering request-scoped credentials. */
export function buildAdvancedEvaluationRunRequest<TApiConfig extends object>({
    suiteId,
    agentVersion,
    promptName,
    promptVersion,
    baselineRunId,
    modelConfigHash,
    apiConfig,
    repetitionCount,
    maxConcurrency,
    maxBudgetUsd,
    caseIds,
    includeJudges,
    humanReviewRate,
}: AdvancedEvaluationRunRequestInput<TApiConfig>) {
    if (!apiConfig || Object.keys(apiConfig).length === 0) {
        throw new Error(MISSING_EVALUATION_MODEL_CONFIG_MESSAGE);
    }
    return {
        suite_id: suiteId,
        agent_version: agentVersion,
        prompt_name: promptName,
        prompt_version: promptVersion,
        baseline_run_id: baselineRunId,
        model_config_hash: modelConfigHash,
        api_config: apiConfig,
        repetition_count: repetitionCount,
        max_concurrency: maxConcurrency,
        max_budget_usd: maxBudgetUsd,
        case_ids: caseIds,
        include_judges: includeJudges,
        human_review_rate: humanReviewRate,
    };
}

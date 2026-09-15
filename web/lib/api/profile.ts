/**
 * 能力画像 API 接口
 */

import { API_BASE_URL, getUserId } from './config';
import { createAbilityProfileRun, pollAgentRun, type AgentRun } from './agentRuns';

// 维度评分接口
export interface DimensionScore {
    score: number | null;
    evidence: string;
    trend?: string;
    reason?: string;
    better_answer_example?: string;
    improvement_tip?: string;
}

// 能力画像接口
export interface AbilityProfile {
    professional_competence: DimensionScore;
    execution_results: DimensionScore;
    logic_problem_solving: DimensionScore;
    communication: DimensionScore;
    growth_potential: DimensionScore;
    collaboration: DimensionScore;
    skill_tags: string[];
    overall_assessment?: string;
    key_strengths?: string[];
    key_weaknesses?: string[];
    recommendation?: string;
    confidence?: number;
    last_updated: string;
    generation_mode?: 'model_reviewed' | 'degraded_evidence_only' | 'not_ready';
    missing_dimensions?: string[];
}

export interface AbilityProfileSource {
    session_id: string;
    series_id?: string | null;
    title: string;
    completed_at: string;
    profile: AbilityProfile;
}

// API 响应接口
export type AbilityProfileProgressBlocker =
    | 'none'
    | 'incomplete_series'
    | 'degraded_round_reports'
    | 'company_profile_pending';

export interface AbilityProfileProgress {
    completed_rounds: number;
    eligible_rounds: number;
    required_rounds: number;
    remaining_rounds: number;
    company_profile_count: number;
    degraded_round_indexes: number[];
    ready_to_generate: boolean;
    blocker: AbilityProfileProgressBlocker;
}

export interface ProfileResponse {
    success: boolean;
    profile?: AbilityProfile;
    generated_at?: string;
    sample_count?: number;
    sources?: AbilityProfileSource[];
    dimension_changes?: Record<string, number>;
    progress?: AbilityProfileProgress;
    message?: string;
}

/**
 * 获取综合能力画像（从数据库读取）
 */
export async function getOverallProfile(): Promise<ProfileResponse> {
    try {
        const response = await fetch(`${API_BASE_URL}/api/chat/profile/overall`, {
            headers: { 'X-User-ID': getUserId() }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('获取能力画像失败:', error);
        return {
            success: false,
            message: '网络错误，请稍后重试'
        };
    }
}

/**
 * Creates and observes the recoverable Ability Profile AgentRun.
 * Request-scoped model credentials are sent only to the backend encrypted task payload.
 */
export async function generateProfile(
    apiConfig?: unknown,
    onRunUpdate?: (run: AgentRun) => void,
): Promise<ProfileResponse> {
    try {
        const created = await createAbilityProfileRun(apiConfig ? {
            user_id: getUserId(),
            api_config: apiConfig,
        } : {});
        const result = 'run_id' in created
            ? (await pollAgentRun(created.run_id, onRunUpdate)).result
            : created.result;
        const payload = (result || {}) as unknown as ProfileResponse;
        return payload.success === false
            ? payload
            : { ...payload, success: true };
    } catch (error) {
        console.error('生成能力画像失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '网络错误，请稍后重试',
        };
    }
}

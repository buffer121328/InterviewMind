/**
 * 用户满意度反馈 API
 * 提交与统计均走统一 apiRequest（自动携带 X-User-ID 头，无需任何凭据）。
 */

import { apiRequest } from './config';
import type { SatisfactionAgentType } from '../satisfaction/aspects';

export type { SatisfactionAgentType } from '../satisfaction/aspects';

/** 满意度提交请求体（严格按后端契约字段） */
export interface SatisfactionSubmission {
    agent_type: SatisfactionAgentType;
    ref_key: string;
    rating: number | null;
    satisfied_aspects: string[];
    dissatisfied_aspects: string[];
    comment: string | null;
}

/** 满意度提交响应 */
export interface SatisfactionSubmissionResult {
    id: string;
    created: boolean;
}

/** 1-5 星的评分键 */
export type SatisfactionRatingKey = '1' | '2' | '3' | '4' | '5';

/** 单个方面的出现频次 */
export interface SatisfactionFrequency {
    aspect: string;
    count: number;
}

/** 满意度统计响应（严格按后端契约字段） */
export interface SatisfactionStats {
    total_count: number;
    rating_count: number;
    avg_rating: number | null;
    rating_distribution: Record<SatisfactionRatingKey, number>;
    satisfied_frequencies: SatisfactionFrequency[];
    dissatisfied_frequencies: SatisfactionFrequency[];
}

export interface SatisfactionFeedbackItem {
    id: string;
    agent_type: SatisfactionAgentType;
    ref_key: string;
    rating: number | null;
    satisfied_aspects: string[];
    dissatisfied_aspects: string[];
    comment: string | null;
    source_verified: boolean;
    review_status: 'not_required' | 'pending' | 'resolved' | 'promoted';
    review_note: string | null;
    candidate_dataset_id: string | null;
    created_at: string;
}

export interface SatisfactionFeedbackPage { items: SatisfactionFeedbackItem[]; total: number; page: number; limit: number }
export interface SatisfactionFilters { agent_type?: SatisfactionAgentType; review_status?: SatisfactionFeedbackItem['review_status']; created_from?: string; created_to?: string }

/** localStorage 去重 key 前缀 */
const SATISFACTION_ASKED_PREFIX = 'satisfaction.asked.';

/**
 * 构造满意度"已询问"去重 key：satisfaction.asked.<agentType>.<refKey>
 * @param agentType 满意度反馈对应的 Agent 类型
 * @param refKey 业务引用键（面试 session_id / 简历结果 result_id）
 */
export function satisfactionAskKey(agentType: SatisfactionAgentType, refKey: string): string {
    return `${SATISFACTION_ASKED_PREFIX}${agentType}.${refKey}`;
}

/**
 * 标记某个业务引用已询问过满意度（提交成功后调用）。
 * @param key satisfactionAskKey 生成的去重 key
 */
export function markSatisfactionAsked(key: string): void {
    if (typeof window === 'undefined') return;
    localStorage.setItem(key, '1');
}

/**
 * 判断某个业务引用是否已询问过满意度。
 * @param key satisfactionAskKey 生成的去重 key
 */
export function hasSatisfactionAsked(key: string): boolean {
    if (typeof window === 'undefined') return false;
    return localStorage.getItem(key) === '1';
}

/**
 * 提交用户满意度反馈（可空星级/空方面）。
 * @param payload 满意度提交请求体
 */
export async function submitSatisfaction(payload: SatisfactionSubmission): Promise<SatisfactionSubmissionResult> {
    return apiRequest<SatisfactionSubmissionResult>('/api/satisfaction', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/** 拉取当前用户的满意度统计汇总。 */
export async function getSatisfactionStats(filters: SatisfactionFilters = {}): Promise<SatisfactionStats> {
    const query = new URLSearchParams();
    if (filters.agent_type) query.set('agent_type', filters.agent_type);
    if (filters.created_from) query.set('created_from', filters.created_from);
    if (filters.created_to) query.set('created_to', filters.created_to);
    return apiRequest<SatisfactionStats>(`/api/satisfaction/stats${query.size ? `?${query}` : ''}`);
}

export async function getSatisfactionFeedback(filters: SatisfactionFilters = {}): Promise<SatisfactionFeedbackPage> {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
    return apiRequest<SatisfactionFeedbackPage>(`/api/satisfaction/feedback${query.size ? `?${query}` : ''}`);
}

export async function resolveSatisfactionFeedback(id: string, note: string): Promise<SatisfactionFeedbackItem> {
    return apiRequest<SatisfactionFeedbackItem>(`/api/satisfaction/feedback/${encodeURIComponent(id)}/review`, { method: 'POST', body: JSON.stringify({ status: 'resolved', note }) });
}

export async function linkSatisfactionPromotion(id: string, datasetId: string, capability: 'interview_planner' | 'resume_optimizer'): Promise<SatisfactionFeedbackItem> {
    return apiRequest<SatisfactionFeedbackItem>(`/api/satisfaction/feedback/${encodeURIComponent(id)}/promotion-link`, { method: 'POST', body: JSON.stringify({ dataset_id: datasetId, capability }) });
}

export async function promoteSatisfactionFeedback(id: string, capability: 'interview_planner' | 'resume_optimizer', confirmation: Record<string, unknown>): Promise<{ id: string; name: string; version: string; status: string }> {
    return apiRequest(`/api/satisfaction/feedback/${encodeURIComponent(id)}/promote`, { method: 'POST', body: JSON.stringify({ capability, confirmation }) });
}

/** 满意度 API 客户端对象 */
export const satisfactionApi = {
    submit: submitSatisfaction,
    stats: getSatisfactionStats,
    feedback: getSatisfactionFeedback,
    resolve: resolveSatisfactionFeedback,
    linkPromotion: linkSatisfactionPromotion,
    promote: promoteSatisfactionFeedback,
};

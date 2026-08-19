import type { InterviewBudgetStageStatus } from './api/agentRunTypes';

const STAGE_LABELS: Record<string, string> = {
    'session_report.reviewer_context.technical_depth': '技术深度评审 · 上下文组装',
    'session_report.reviewer_context.communication': '沟通评审 · 上下文组装',
    'session_report.reviewer_context.job_fit': '岗位匹配评审 · 上下文组装',
    'session_report.reviewer_context.factual_risk': '事实风险评审 · 上下文组装',
    'session_report.review.technical_depth': '技术深度评审',
    'session_report.review.communication': '沟通评审',
    'session_report.review.job_fit': '岗位匹配评审',
    'session_report.review.factual_risk': '事实风险评审',
    'session_report.narrative_composer': '报告叙事汇总',
    'session_report.context_assembly': '报告上下文组装',
    'interview_report.context_assembly': '普通报告 · 上下文组装',
    'interview_report.standard.general': '普通报告 · 通用模型评审',
    'unattributed': '未归属阶段',
};

const STATUS_LABELS: Record<InterviewBudgetStageStatus, string> = {
    running: '进行中',
    succeeded: '已完成',
    failed: '失败',
    skipped: '已跳过',
    unknown: '未完成',
};

const FAILURE_LABELS: Record<string, string> = {
    timeout: '超时',
    authentication: '认证失败',
    rate_limit: '限流/配额',
    network: '网络失败',
    request: '请求失败',
    model_failure: '模型失败',
    skipped: '预算不足而跳过',
    context_protection: '触发过上下文保护',
};

const WARNING_LABELS: Record<string, string> = {
    context_protection: '触发过上下文保护',
};

const SOURCE_LABELS: Record<string, string> = {
    qa_history: 'QA 历史',
    job_description: 'JD 岗位描述',
    resume: '简历信息',
    company: '公司信息',
    company_info: '公司信息',
    question_evidence: '逐题证据',
    answer_points: '回答要点',
    profile_context: '候选人背景',
    evidence: '评审证据',
    system: '系统指令',
    human: '用户输入',
    input: '模型输入',
};

/** Converts internal reviewer stage ids to stable user-facing labels. */
export function getBudgetStageLabel(stage: string): string {
    if (STAGE_LABELS[stage]) return STAGE_LABELS[stage];
    return stage
        .replace(/^session_report\./, '')
        .replaceAll('.', ' · ')
        .replaceAll('_', ' ');
}

/** Converts safe backend failure enums to concise Chinese labels. */
export function getBudgetFailureLabel(failure: string | null | undefined): string {
    if (!failure) return '';
    return FAILURE_LABELS[failure] || failure;
}

/** Converts non-fatal budget signals to a stable Chinese warning. */
export function getBudgetWarningLabel(warning: string | null | undefined): string {
    if (!warning) return '';
    return WARNING_LABELS[warning] || warning;
}

/** Converts safe context source identifiers without exposing their content. */
export function getBudgetSourceLabel(source: string): string {
    return SOURCE_LABELS[source] || source.replaceAll('_', ' ');
}

/** Formats a non-negative duration without exposing implementation details. */
export function formatBudgetDuration(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return '未返回';
    const milliseconds = Math.max(0, Math.round(value));
    if (milliseconds < 1000) return `${milliseconds} ms`;
    const seconds = milliseconds / 1000;
    if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes} 分 ${Math.round(seconds % 60)} 秒`;
}

/** Formats actual usage, falling back to an explicitly marked estimate. */
export function formatBudgetTokens(actual: number | null | undefined, estimated?: number | null): string {
    if (actual !== null && actual !== undefined && Number.isFinite(actual)) {
        return `${Math.max(0, Math.round(actual)).toLocaleString('zh-CN')} tokens`;
    }
    if (estimated !== null && estimated !== undefined && Number.isFinite(estimated)) {
        return `约 ${Math.max(0, Math.round(estimated)).toLocaleString('zh-CN')} tokens`;
    }
    return '未返回 usage';
}

/** Formats an optional integer while preserving an unknown value as a visible state. */
export function formatBudgetNumber(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) return '未返回';
    return Math.max(0, Math.round(value)).toLocaleString('zh-CN');
}

/** Returns the stable label used by stage status badges. */
export function getBudgetStatusLabel(status: InterviewBudgetStageStatus): string {
    return STATUS_LABELS[status] || STATUS_LABELS.unknown;
}

export const REVIEWER_STAGE_PERSPECTIVES = [
    { key: 'technical_depth', label: '技术深度评审' },
    { key: 'communication', label: '沟通评审' },
    { key: 'job_fit', label: '岗位匹配评审' },
    { key: 'factual_risk', label: '事实风险评审' },
] as const;

export interface ReviewerStagePair {
    key: typeof REVIEWER_STAGE_PERSPECTIVES[number]['key'];
    label: string;
    contextStage: string;
    reviewStage: string;
}

export function getReviewerStagePairs(): ReviewerStagePair[] {
    return REVIEWER_STAGE_PERSPECTIVES.map(({ key, label }) => ({
        key,
        label,
        contextStage: `session_report.reviewer_context.${key}`,
        reviewStage: `session_report.review.${key}`,
    }));
}

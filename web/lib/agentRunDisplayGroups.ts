import type { AgentRun, AgentRunStatus, AgentRunTaskType } from './api/agentRunTypes.ts';

/** User-facing task categories that intentionally hide AgentRun's implementation-level task types. */
export type AgentRunCategory = 'text-interview' | 'voice-interview' | 'resume-optimization' | 'job-delivery' | 'evaluation';

/** Supplies the stable category values and labels accepted by Run Center's user-facing filter. */
export const AGENT_RUN_CATEGORIES: ReadonlyArray<{ value: AgentRunCategory; label: string }> = [
    { value: 'text-interview', label: '文本面试' },
    { value: 'voice-interview', label: '语音面试' },
    { value: 'resume-optimization', label: '简历优化' },
    { value: 'job-delivery', label: '岗位投递' },
    { value: 'evaluation', label: '评测' },
];

/** Maps every supported backend task type to the product category shown to users. */
export function getAgentRunCategory(taskType: AgentRunTaskType): AgentRunCategory {
    if (taskType === 'evaluation_suite' || taskType === 'interview_evaluation_draft' || taskType === 'interview_scoring') return 'evaluation';
    if (taskType === 'voice_interview_turn') return 'voice-interview';
    if (taskType === 'resume_optimize' || taskType === 'resume_workspace' || taskType === 'resume_generation') return 'resume-optimization';
    if (taskType === 'job_assets' || taskType === 'job_recommendation_capture') return 'job-delivery';
    return 'text-interview';
}

/** Resolves the user-facing label for a stable task category. */
export function getAgentRunCategoryLabel(category: AgentRunCategory): string {
    return AGENT_RUN_CATEGORIES.find(item => item.value === category)?.label || category;
}

const GENERIC_STATUS_LABELS: Record<AgentRun['status'], string> = {
    queued: '排队中',
    retrying: '等待重试',
    running: '运行中',
    cancel_requested: '取消中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
};

/** Describes completion of one AgentRun without implying that its linked interview has ended. */
export function getAgentRunStatusLabel(run: AgentRun): string {
    if (run.task_type === 'job_recommendation_capture' && run.status === 'running') {
        if (run.stage === 'validating_import') return '校验当前页导入';
        if (run.stage === 'extracting_jobs') return '确认岗位卡片';
        if (run.stage === 'ranking_jobs') return '匹配排序中';
        if (run.stage === 'saving_jobs') return '保存岗位中';
        if (run.stage === 'scheduling_assets') return '创建资产任务';
        // Historical runs may still carry browser-era stages after the workflow upgrade.
        if (run.stage === 'awaiting_login') return '等待用户扫码登录';
        if (run.stage === 'awaiting_manual_verification') return '等待用户手动完成验证';
    }
    if (run.status !== 'succeeded') return GENERIC_STATUS_LABELS[run.status];
    if (run.task_type === 'interview_start') return '首题已生成';
    if (run.task_type === 'interview_turn' || run.task_type === 'voice_interview_turn') return '本次回复已生成';
    if (run.task_type === 'interview_report') return '报告已生成';
    return GENERIC_STATUS_LABELS.succeeded;
}

/** Labels an aggregate category badge as task execution state rather than whole-interview state. */
export function getAgentRunGroupStatusLabel(category: AgentRunCategory, status: AgentRun['status']): string {
    if (status === 'succeeded' && (category === 'text-interview' || category === 'voice-interview')) {
        return '生成任务已结束';
    }
    return GENERIC_STATUS_LABELS[status];
}

/** Returns the newest AgentRun status from a list sorted by descending creation time. */
export function latestAgentRunStatus(runs: AgentRun[]): AgentRunStatus | null {
    return runs[0]?.status || null;
}

function boundedQuestionProgress(run: AgentRun): { count: number; max: number } | null {
    const count = run.session_question_count;
    const max = run.session_max_questions;
    if (typeof count !== 'number' || !Number.isFinite(count)
        || typeof max !== 'number' || !Number.isFinite(max) || max <= 0) return null;
    return {
        count: Math.min(Math.max(Math.trunc(count), 0), Math.trunc(max)),
        max: Math.trunc(max),
    };
}

/** Shows the lifecycle of the whole linked interview separately from the current AgentRun. */
export function getInterviewSessionProgressLabel(run: AgentRun): string | null {
    const isInterviewRun = run.task_type === 'interview_start'
        || run.task_type === 'interview_turn'
        || run.task_type === 'voice_interview_turn'
        || run.task_type === 'interview_report';
    if (!isInterviewRun || !run.session_id) return null;

    const progress = boundedQuestionProgress(run);
    const completedProgress = progress && progress.count > 0 ? ` · ${progress.count}/${progress.max} 题` : '';
    if (run.session_status === 'completed') return `整场面试已完成${completedProgress}`;
    if (run.session_status === 'archived') return `面试已归档${completedProgress}`;
    if (run.session_status === 'active') {
        if (!progress) return '面试进行中';
        const current = Math.min(progress.count + 1, progress.max);
        return `面试进行中 · 当前第 ${current}/${progress.max} 题`;
    }
    return '本状态仅表示本次生成任务，不代表整场面试完成';
}

/** A local presentation group derived from API-owned runs; it never changes the API response or run data. */
export interface AgentRunDisplayGroup {
    key: string;
    category: AgentRunCategory;
    categoryLabel: string;
    dateLabel: '今天' | '昨天' | '过去7天' | '更早';
    runs: AgentRun[];
}

/** Classifies a run's creation time into local calendar buckets used by the task history. */
function getDateLabel(createdAt: string, now: Date): AgentRunDisplayGroup['dateLabel'] {
    const created = new Date(createdAt);
    if (Number.isNaN(created.getTime())) return '更早';
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const createdStart = new Date(created.getFullYear(), created.getMonth(), created.getDate()).getTime();
    const elapsedDays = Math.floor((todayStart - createdStart) / 86_400_000);
    if (elapsedDays <= 0) return '今天';
    if (elapsedDays === 1) return '昨天';
    if (elapsedDays <= 7) return '过去7天';
    return '更早';
}

/** Sorts display groups by their newest task creation time, with stable keys for exact ties. */
function compareDisplayGroups(left: AgentRunDisplayGroup, right: AgentRunDisplayGroup): number {
    const leftCreatedAt = Date.parse(left.runs[0]?.created_at || '');
    const rightCreatedAt = Date.parse(right.runs[0]?.created_at || '');
    const leftTime = Number.isNaN(leftCreatedAt) ? Number.NEGATIVE_INFINITY : leftCreatedAt;
    const rightTime = Number.isNaN(rightCreatedAt) ? Number.NEGATIVE_INFINITY : rightCreatedAt;
    return rightTime - leftTime || left.key.localeCompare(right.key);
}

/** Flattens server groups into sections ordered globally and internally by newest creation time. */
export function groupAgentRunsForDisplay(serverGroups: Array<{ runs: AgentRun[] }>, now = new Date()): AgentRunDisplayGroup[] {
    const groups = new Map<string, AgentRunDisplayGroup>();
    for (const serverGroup of serverGroups) {
        for (const run of serverGroup.runs) {
            const category = getAgentRunCategory(run.task_type);
            const dateLabel = getDateLabel(run.created_at, now);
            const key = `${category}:${dateLabel}`;
            const group = groups.get(key);
            if (group) group.runs.push(run);
            else groups.set(key, { key, category, categoryLabel: getAgentRunCategoryLabel(category), dateLabel, runs: [run] });
        }
    }
    for (const group of groups.values()) {
        group.runs.sort((left, right) => (
            right.created_at.localeCompare(left.created_at)
            || right.run_id.localeCompare(left.run_id)
        ));
    }
    return [...groups.values()].sort(compareDisplayGroups);
}

/** A bounded, whitelisted description of one resume-workflow stage that deliberately omits resume text and request payloads. */
export interface ResumeResultStageSummary {
    label: string;
    detail: string;
    available: boolean;
}

/** Safe, minimal generated-resume metadata returned only when the run result explicitly includes an artifact reference. */
export interface ResumeArtifactSummary {
    id: string | null;
    name: string | null;
}

/** Safe result data for the Run Center; no arbitrary result fields or raw resume content are surfaced. */
export interface ResumeRunResultSummary {
    resultId: string | null;
    stages: ResumeResultStageSummary[];
    artifact: ResumeArtifactSummary | null;
}

/** Narrows unknown API values before the UI reads its explicit public result fields. */
function asRecord(value: unknown): Record<string, unknown> | null {
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

/** Converts a whitelisted scalar to bounded display text and refuses object values. */
function safeScalar(value: unknown): string | null {
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
    if (typeof value !== 'string') return null;
    const text = value.trim().replace(/\s+/g, ' ');
    return text ? text.slice(0, 120) : null;
}

/** Reads up to two short list items from a known result field without displaying unknown nested data. */
function safeList(record: Record<string, unknown>, key: string): string[] {
    const value = record[key];
    if (!Array.isArray(value)) return [];
    return value.map(safeScalar).filter((item): item is string => item !== null).slice(0, 2);
}

/** Builds a concise, non-sensitive summary from whitelisted competition-analysis metrics and guidance. */
function summarizeCompetition(value: unknown): ResumeResultStageSummary {
    const record = asRecord(value);
    if (!record) return { label: '竞争力分析', detail: '本任务未返回该阶段的展示摘要。', available: false };
    const score = safeScalar(record.overall_score);
    const highlights = [...safeList(record, 'strengths'), ...safeList(record, 'priority_improvements')];
    return { label: '竞争力分析', detail: [score ? `综合评分 ${score}` : null, ...highlights].filter(Boolean).join(' · ').slice(0, 260) || '已完成竞争力分析。', available: true };
}

/** Builds a concise, non-sensitive summary from whitelisted JD-match scores, gaps, and actions. */
function summarizeJdMatch(value: unknown): ResumeResultStageSummary {
    const record = asRecord(value);
    if (!record) return { label: 'JD 匹配', detail: '本任务未返回该阶段的展示摘要。', available: false };
    const score = safeScalar(record.overall_match_score) || safeScalar(record.match_score);
    const guidance = [...safeList(record, 'missing_keywords'), ...safeList(record, 'priority_actions')];
    return { label: 'JD 匹配', detail: [score ? `匹配度 ${score}` : null, ...guidance].filter(Boolean).join(' · ').slice(0, 260) || '已完成 JD 匹配分析。', available: true };
}

/** Builds a concise, non-sensitive optimization summary and intentionally excludes original and rewritten resume passages. */
function summarizeOptimization(value: unknown): ResumeResultStageSummary {
    const record = asRecord(value);
    if (!record) return { label: '内容优化', detail: '本任务未返回该阶段的展示摘要。', available: false };
    const score = safeScalar(record.match_score);
    const improvements = safeList(record, 'key_improvements');
    return { label: '内容优化', detail: [score ? `匹配度 ${score}` : null, ...improvements].filter(Boolean).join(' · ').slice(0, 260) || '已完成内容优化，详情请在简历工作台查看。', available: true };
}

/** Extracts only explicit artifact identifiers and labels, never final resume content or unrecognized result fields. */
function summarizeArtifact(result: Record<string, unknown>): ResumeArtifactSummary | null {
    const nested = asRecord(result.generated_resume);
    const id = safeScalar(result.generated_resume_id) || safeScalar(nested?.id);
    const name = safeScalar(result.generated_resume_title) || safeScalar(result.generated_resume_filename)
        || safeScalar(nested?.title) || safeScalar(nested?.filename);
    return id || name ? { id, name } : null;
}

/** Builds the professional-generation summary without pretending workspace analysis fields were returned. */
function summarizeGeneration(result: Record<string, unknown>): ResumeResultStageSummary[] {
    const sessionId = safeScalar(result.generation_session_id);
    return [{
        label: '专业简历生成',
        detail: `已完成需求分析、专业初稿、内容优化、事实核查、最终审阅与保存${sessionId ? ` · 生成会话 ${sessionId}` : ''}。`,
        available: true,
    }];
}

/** Produces the task-aware safe Run Center resume-result view and never exposes raw resume passages. */
export function summarizeResumeRunResult(
    result: Record<string, unknown> | null | undefined,
    taskType: AgentRunTaskType = 'resume_workspace',
): ResumeRunResultSummary {
    const publicResult = result || {};
    const optimization = publicResult.content_optimization ?? publicResult.result;
    return {
        resultId: safeScalar(publicResult.result_id),
        stages: taskType === 'resume_generation'
            ? summarizeGeneration(publicResult)
            : [
                summarizeCompetition(publicResult.competition_analysis),
                summarizeJdMatch(publicResult.jd_matching),
                summarizeOptimization(optimization),
            ],
        artifact: summarizeArtifact(publicResult),
    };
}

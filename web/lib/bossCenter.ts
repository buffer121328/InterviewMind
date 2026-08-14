import type { AgentRun } from './api/agentRunTypes.ts';
import type { CapturedJobSummary } from './api/jobs.ts';

/** AgentRun 生命周期中仍视为「进行中」的状态集合；进入该集合后 UI 会持续轮询刷新。 */
export const ACTIVE_RUN_STATUSES = new Set(["queued", "retrying", "running", "cancel_requested"]);

/** 岗位资产生成状态的中文标签；未知状态回退为原文。 */
export const ASSET_STATUS_LABELS: Record<string, string> = {
    queued: "等待生成",
    retrying: "等待重试",
    running: "生成中",
    succeeded: "资产已完成",
    failed: "资产失败",
    cancelled: "已取消",
    cancel_requested: "取消中",
};

/** 采集结果区在切换主页面后的会话级保留键；按当前用户隔离。 */
export const CAPTURE_STATE_KEY = "boss-center-capture-state-v1";

/** BOSS 常用城市代码；选择器展示中文，旁边的只读框始终展示实际提交代码。 */
export const BOSS_HOT_CITIES = [
    { name: "深圳", code: "101280600" },
    { name: "广州", code: "101280100" },
    { name: "珠海", code: "101280700" },
    { name: "佛山", code: "101280800" },
    { name: "东莞", code: "101281600" },
    { name: "中山", code: "101281700" },
    { name: "惠州", code: "101280300" },
    { name: "江门", code: "101281100" },
    { name: "肇庆", code: "101280900" },
    { name: "汕头", code: "101280500" },
    { name: "北京", code: "101010100" },
    { name: "上海", code: "101020100" },
    { name: "杭州", code: "101210100" },
    { name: "成都", code: "101270100" },
    { name: "武汉", code: "101200100" },
] as const;

/** Formats one backend timestamp for compact list display. */
export function formatDate(value?: string): string {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

/** Narrows an unknown asset field to a plain record before reading whitelisted keys. */
export function asRecord(value: unknown): Record<string, unknown> | null {
    return typeof value === "object" && value !== null && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

/** Reads a bounded string array from one known JD-analysis field. */
export function readStringList(record: Record<string, unknown> | null, key: string): string[] {
    const value = record?.[key];
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is string => typeof item === "string").slice(0, 12);
}

/** Reads only public captured-job summaries from a recommendation AgentRun result. */
export function getCaptureRunJobs(run: AgentRun | null): CapturedJobSummary[] {
    const jobs = run?.result?.jobs;
    if (!Array.isArray(jobs)) return [];
    return jobs.filter((item): item is CapturedJobSummary => {
        if (typeof item !== "object" || item === null) return false;
        const record = item as Record<string, unknown>;
        const jobId = record.job_id;
        return typeof record.job_title === "string"
            && typeof record.company_name === "string"
            && (typeof jobId === "number" || jobId === null);
    });
}

/** Merges a child asset run's public result into its current recommendation card. */
export function mergeAssetRun(job: CapturedJobSummary, run: AgentRun): CapturedJobSummary {
    const assetRecord = asRecord(run.result?.assets);
    const jdAnalysis = asRecord(assetRecord?.jd_analysis);
    return {
        ...job,
        asset_status: run.status,
        match_score: typeof jdAnalysis?.overall_match_score === "number"
            ? jdAnalysis.overall_match_score
            : job.match_score,
        custom_resume_id: typeof assetRecord?.custom_resume_id === "number"
            ? assetRecord.custom_resume_id
            : job.custom_resume_id,
        risk_flags: Array.isArray(assetRecord?.risk_flags)
            ? assetRecord.risk_flags.filter((item): item is string => typeof item === "string")
            : job.risk_flags,
    };
}

/** Describes the current import stage without exposing browser credentials or hidden login steps. */
export function captureRunMessage(run: AgentRun, elapsedSeconds: number): string {
    if (run.stage === "validating_import") return "正在校验当前页卡片、官方链接并过滤实习岗位。";
    if (run.stage === "extracting_jobs") return "已确认有限字段岗位卡片，准备进入匹配排序。";
    if (run.stage === "ranking_jobs") return "正在结合基础简历做语义匹配与本地关键词评分。";
    if (run.stage === "awaiting_import") return "采集完成，请确认后一键入库。";
    if (run.stage === "saving_jobs") return "正在保存岗位、薪资、公司人数、职位介绍与匹配度。";
    if (run.stage === "scheduling_assets") return "正在创建可恢复资产任务；Worker 最多并行处理 5 个岗位。";
    return `任务已持久化，当前阶段：${run.stage} · 已等待 ${elapsedSeconds}s`;
}

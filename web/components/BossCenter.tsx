"use client";

import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    AlertTriangle,
    BriefcaseBusiness,
    Building2,
    CheckCircle2,
    ExternalLink,
    FileText,
    Loader2,
    MapPin,
    Monitor,
    RefreshCw,
    Save,
    Search,
    Sparkles,
    Trash2,
    Upload,
} from "lucide-react";
import { toast } from "sonner";

import { PaginationControls } from "@/components/PaginationControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { getAgentRunStatusLabel } from "@/lib/agentRunDisplayGroups";
import type { AgentRun } from "@/lib/api/agentRunTypes";
import { getAgentRun, listAgentRuns } from "@/lib/api/agentRuns";
import {
    captureRecommendations,
    deleteJob,
    exportJobToApplication,
    getBossBrowserTabStatus,
    getJobDetail,
    listJobs,
    openJobInExistingBossTab,
    searchAndCaptureBossBrowserTab,
    updateJobGreeting,
    type BossBrowserChannel,
    type BossTabStatusResponse,
    type CapturedJobSummary,
    type GreetingItem,
    type JobDetail,
    type JobListItem,
} from "@/lib/api/jobs";
import { parseBossDomCapturePayload } from "@/lib/bossDomCapture";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { useInterviewStore } from "@/store/useInterviewStore";

const ACTIVE_RUN_STATUSES = new Set(["queued", "retrying", "running", "cancel_requested"]);
const TONE_LABELS: Record<string, string> = {
    professional: "稳重专业",
    technical: "技术沟通",
    result_oriented: "结果导向",
};
const ASSET_STATUS_LABELS: Record<string, string> = {
    queued: "等待生成",
    retrying: "等待重试",
    running: "生成中",
    succeeded: "资产已完成",
    failed: "资产失败",
    cancelled: "已取消",
    cancel_requested: "取消中",
};

/** BOSS 常用城市代码；选择器展示中文，旁边的只读框始终展示实际提交代码。 */
const BOSS_HOT_CITIES = [
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
function formatDate(value?: string): string {
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
function asRecord(value: unknown): Record<string, unknown> | null {
    return typeof value === "object" && value !== null && !Array.isArray(value)
        ? value as Record<string, unknown>
        : null;
}

/** Reads a bounded string array from one known JD-analysis field. */
function readStringList(record: Record<string, unknown> | null, key: string): string[] {
    const value = record?.[key];
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is string => typeof item === "string").slice(0, 12);
}

/** Reads only public captured-job summaries from a recommendation AgentRun result. */
function getCaptureRunJobs(run: AgentRun | null): CapturedJobSummary[] {
    const jobs = run?.result?.jobs;
    if (!Array.isArray(jobs)) return [];
    return jobs.filter((item): item is CapturedJobSummary => (
        typeof item === "object"
        && item !== null
        && typeof (item as { job_id?: unknown }).job_id === "number"
    ));
}

/** Merges a child asset run's public result into its current recommendation card. */
function mergeAssetRun(job: CapturedJobSummary, run: AgentRun): CapturedJobSummary {
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
        greetings: Array.isArray(assetRecord?.greetings)
            ? assetRecord.greetings as GreetingItem[]
            : job.greetings,
        risk_flags: Array.isArray(assetRecord?.risk_flags)
            ? assetRecord.risk_flags.filter((item): item is string => typeof item === "string")
            : job.risk_flags,
    };
}

/** Describes the current import stage without exposing browser credentials or hidden login steps. */
function captureRunMessage(run: AgentRun, elapsedSeconds: number): string {
    if (run.stage === "validating_import") return "正在校验当前页卡片、官方链接并过滤实习岗位。";
    if (run.stage === "extracting_jobs") return "已确认有限字段岗位卡片，准备进入匹配排序。";
    if (run.stage === "ranking_jobs") return "正在结合基础简历做语义匹配与本地关键词评分。";
    if (run.stage === "saving_jobs") return "正在保存岗位、薪资、公司人数、职位介绍与匹配度。";
    if (run.stage === "scheduling_assets") return "正在创建可恢复资产任务；Worker 最多并行处理 5 个岗位。";
    return `任务已持久化，当前阶段：${run.stage} · 已等待 ${elapsedSeconds}s`;
}

/** Replaces one greeting inside a recommendation result without mutating prior React state. */
function replaceResultGreeting(
    jobs: CapturedJobSummary[],
    jobId: number,
    greetingIndex: number,
    messageText: string,
): CapturedJobSummary[] {
    return jobs.map(job => {
        if (job.job_id !== jobId) return job;
        return {
            ...job,
            greetings: job.greetings.map((greeting, index) => (
                index === greetingIndex ? { ...greeting, message_text: messageText } : greeting
            )),
        };
    });
}

/** Main岗位中心：复用现有登录标签页采集，并管理可编辑投递资产。 */
export function BossCenter() {
    const resume = useInterviewStore(state => state.resume);
    const uploadResume = useInterviewStore(state => state.uploadResume);
    const getApiConfigForRequest = useInterviewStore(state => state.getApiConfigForRequest);
    const resumeFileInputRef = useRef<HTMLInputElement>(null);

    const [query, setQuery] = useState("agent");
    const [resumeContent, setResumeContent] = useState("");
    const [resumeUploading, setResumeUploading] = useState(false);
    const [topN, setTopN] = useState(3);
    const [city, setCity] = useState("101280600");
    const [browserChannel, setBrowserChannel] = useState<BossBrowserChannel>("msedge");
    const [tabStatus, setTabStatus] = useState<BossTabStatusResponse | null>(null);
    const [tabError, setTabError] = useState<string | null>(null);
    const [checkingTab, setCheckingTab] = useState(false);
    const [submittingCapture, setSubmittingCapture] = useState(false);
    const [captureElapsed, setCaptureElapsed] = useState(0);
    const [captureRun, setCaptureRun] = useState<AgentRun | null>(null);
    const [results, setResults] = useState<CapturedJobSummary[]>([]);
    const [jobs, setJobs] = useState<JobListItem[]>([]);
    const [jobsTotal, setJobsTotal] = useState(0);
    const [jobsPage, setJobsPage] = useState(1);
    const [jobsLoading, setJobsLoading] = useState(false);
    const [jobsError, setJobsError] = useState<string | null>(null);
    const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
    const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [actionKey, setActionKey] = useState<string | null>(null);

    const defaultResumeText = useMemo(() => resume?.content || "", [resume]);
    const captureActive = Boolean(captureRun && ACTIVE_RUN_STATUSES.has(captureRun.status));
    const captureBusy = submittingCapture || captureActive;

    useEffect(() => {
        if (!defaultResumeText) return;
        const timer = window.setTimeout(() => setResumeContent(current => current || defaultResumeText), 0);
        return () => window.clearTimeout(timer);
    }, [defaultResumeText]);

    /** Reloads the owner-scoped job library page and preserves the existing page on transient failures. */
    const refreshJobs = useCallback(async (showLoading = true, notify = false) => {
        if (showLoading) setJobsLoading(true);
        try {
            const response = await listJobs({
                limit: DEFAULT_PAGE_SIZE,
                offset: (jobsPage - 1) * DEFAULT_PAGE_SIZE,
            });
            if (response.success) {
                setJobs(response.jobs || []);
                setJobsTotal(response.total);
            }
            setJobsError(null);
        } catch (error) {
            const message = error instanceof Error ? error.message : "";
            const friendly = /failed to fetch/i.test(message)
                ? "无法连接后端，岗位库暂时不可用。"
                : message || "加载岗位库失败";
            setJobsError(friendly);
            if (notify) toast.error(friendly);
        } finally {
            if (showLoading) setJobsLoading(false);
        }
    }, [jobsPage]);

    useEffect(() => {
        const timer = window.setTimeout(() => void refreshJobs(), 0);
        return () => window.clearTimeout(timer);
    }, [refreshJobs]);

    useEffect(() => {
        if (!captureActive) return;
        const timer = window.setInterval(() => setCaptureElapsed(value => value + 1), 1000);
        return () => window.clearInterval(timer);
    }, [captureActive]);

    useEffect(() => {
        let disposed = false;
        void listAgentRuns({ taskType: "job_recommendation_capture", limit: 1 })
            .then(response => {
                const latest = response.runs[0];
                if (disposed || !latest) return;
                setCaptureRun(latest);
                const createdAt = Date.parse(latest.created_at);
                if (ACTIVE_RUN_STATUSES.has(latest.status) && !Number.isNaN(createdAt)) {
                    setCaptureElapsed(Math.max(0, Math.floor((Date.now() - createdAt) / 1000)));
                }
            })
            .catch(() => undefined);
        return () => {
            disposed = true;
        };
    }, []);

    const activeCaptureRunId = captureActive ? captureRun?.run_id : null;
    useEffect(() => {
        if (!activeCaptureRunId) return;
        let disposed = false;
        let timer: number | undefined;
        const refreshRun = async () => {
            try {
                const run = await getAgentRun(activeCaptureRunId);
                if (disposed) return;
                setCaptureRun(run);
                if (ACTIVE_RUN_STATUSES.has(run.status)) {
                    timer = window.setTimeout(() => void refreshRun(), 1200);
                }
            } catch {
                if (!disposed) timer = window.setTimeout(() => void refreshRun(), 2500);
            }
        };
        void refreshRun();
        return () => {
            disposed = true;
            if (timer) window.clearTimeout(timer);
        };
    }, [activeCaptureRunId]);

    useEffect(() => {
        if (captureRun?.status !== "succeeded") return;
        const timer = window.setTimeout(() => {
            setResults(getCaptureRunJobs(captureRun));
            setJobsPage(1);
            void refreshJobs(false);
        }, 0);
        return () => window.clearTimeout(timer);
    }, [captureRun, refreshJobs]);

    const activeAssetRunIds = results
        .filter(job => job.asset_run_id && ACTIVE_RUN_STATUSES.has(job.asset_status || ""))
        .map(job => job.asset_run_id as string)
        .sort()
        .join(",");
    useEffect(() => {
        if (!activeAssetRunIds) return;
        let disposed = false;
        let timer: number | undefined;
        const refreshAssetRuns = async () => {
            const ids = activeAssetRunIds.split(",");
            const settled = await Promise.allSettled(ids.map(id => getAgentRun(id)));
            if (disposed) return;
            const runs = new Map<string, AgentRun>();
            for (const item of settled) {
                if (item.status === "fulfilled") runs.set(item.value.run_id, item.value);
            }
            setResults(current => current.map(job => {
                const run = job.asset_run_id ? runs.get(job.asset_run_id) : undefined;
                return run ? mergeAssetRun(job, run) : job;
            }));
            const stillActive = [...runs.values()].some(run => ACTIVE_RUN_STATUSES.has(run.status));
            if (settled.some(item => item.status === "rejected") || stillActive) {
                timer = window.setTimeout(() => void refreshAssetRuns(), 1500);
            } else {
                void refreshJobs(false);
            }
        };
        void refreshAssetRuns();
        return () => {
            disposed = true;
            if (timer) window.clearTimeout(timer);
        };
    }, [activeAssetRunIds, refreshJobs]);

    /** Returns model settings without logging API keys or the resume body. */
    const requireApiConfig = () => {
        const apiConfig = getApiConfigForRequest();
        if (!apiConfig) {
            toast.error("请先配置 Smart 与 Fast 模型通道");
            return null;
        }
        return apiConfig;
    };

    /** Checks the existing Edge/Chrome BOSS tab; it never starts or closes a browser. */
    const handleConnectBrowserTab = async () => {
        setCheckingTab(true);
        setTabError(null);
        try {
            const status = await getBossBrowserTabStatus(browserChannel);
            setTabStatus(status);
            try {
                const currentUrl = new URL(status.current_url);
                const currentQuery = currentUrl.searchParams.get("query")?.trim();
                const currentCity = currentUrl.searchParams.get("city")?.trim();
                if (currentQuery) setQuery(currentQuery);
                if (currentCity && BOSS_HOT_CITIES.some(item => item.code === currentCity)) setCity(currentCity);
            } catch {
                // 后端已限制为 BOSS 官方 URL；这里只忽略无法展示的异常 URL。
            }
            if (status.page_status === "search_ready") toast.success(status.message);
            else toast.info(status.message);
        } catch (error) {
            setTabStatus(null);
            const message = error instanceof Error ? error.message : "无法连接当前 BOSS 标签页";
            setTabError(message);
            toast.error(message);
        } finally {
            setCheckingTab(false);
        }
    };

    /** Reuses the shared resume parser and copies only parsed text into the matching request. */
    const handleResumeUpload = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        setResumeUploading(true);
        try {
            await uploadResume(file);
            const parsedResume = useInterviewStore.getState().resume;
            if (!parsedResume?.content.trim()) throw new Error("简历未解析出有效文本");
            setResumeContent(parsedResume.content);
            toast.success(`已从 ${file.name} 解析基础简历`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "上传并解析简历失败");
        } finally {
            setResumeUploading(false);
            event.target.value = "";
        }
    };

    /** Navigates and reads the existing BOSS tab, then creates an owner-scoped recoverable import run. */
    const handleRecommendations = async () => {
        if (!query.trim()) {
            toast.error("请填写搜索关键词");
            return;
        }
        if (!resumeContent.trim()) {
            toast.error("请提供基础简历内容");
            return;
        }
        if (city && !/^\d{1,20}$/.test(city)) {
            toast.error("BOSS 城市必须是下拉框产生的数字代码");
            return;
        }
        const apiConfig = requireApiConfig();
        if (!apiConfig) return;

        setCaptureElapsed(0);
        setSubmittingCapture(true);
        setResults([]);
        setTabError(null);
        try {
            toast.info(`正在复用现有 ${browserChannel === "msedge" ? "Edge" : "Chrome"} BOSS 标签页；页面检查间隔至少 5 秒。`);
            const browserCapture = await searchAndCaptureBossBrowserTab({
                query: query.trim(),
                city: city || undefined,
                max_cards: 20,
                browser_channel: browserChannel,
            });
            const domCapture = parseBossDomCapturePayload(browserCapture);
            setTabStatus({
                success: browserCapture.success,
                browser_channel: browserCapture.browser_channel,
                browser_label: browserCapture.browser_label,
                connected: true,
                current_url: browserCapture.source_page_url,
                page_status: browserCapture.page_status,
                ready_state: browserCapture.ready_state,
                visible_card_count: domCapture.cards.length,
                message: browserCapture.message,
            });
            toast.info(`已读取 ${domCapture.cards.length} 张非实习岗位卡片，正在创建可恢复导入任务。`);
            const run = await captureRecommendations({
                query: query.trim(),
                resume_content: resumeContent.trim(),
                source_page_url: domCapture.source_page_url,
                cards: domCapture.cards,
                top_n: Math.min(domCapture.cards.length, 20, Math.max(1, topN)),
                city: city || undefined,
                api_config: apiConfig,
            });
            setCaptureRun(run);
            if (run.status === "succeeded") {
                const importedJobs = getCaptureRunJobs(run);
                setResults(importedJobs);
                toast.success(`已导入 ${importedJobs.length} 个岗位`);
            } else {
                toast.success("导入任务已创建，可切换页面后继续查看");
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : "现有 BOSS 标签页搜索与采集失败";
            setTabError(message);
            toast.error(message);
        } finally {
            setSubmittingCapture(false);
        }
    };

    /** Opens a library row's full persisted assets inside this page. */
    const handleOpenJobDetail = async (jobId: number) => {
        setSelectedJobId(jobId);
        setSelectedJob(null);
        setDetailError(null);
        setDetailLoading(true);
        try {
            const response = await getJobDetail(jobId);
            setSelectedJob(response.job);
        } catch (error) {
            setDetailError(error instanceof Error ? error.message : "加载岗位详情失败");
        } finally {
            setDetailLoading(false);
        }
    };

    /** Deletes one owner-scoped job and removes it from both the library and current results. */
    const handleDelete = async (job: JobListItem) => {
        if (!window.confirm(`确认从岗位库删除「${job.company_name} · ${job.job_title}」？`)) return;
        try {
            await deleteJob(job.id);
            setJobs(current => current.filter(item => item.id !== job.id));
            setResults(current => current.filter(item => item.job_id !== job.id));
            setJobsTotal(current => Math.max(0, current - 1));
            if (selectedJobId === job.id) setSelectedJobId(null);
            if (jobs.length === 1 && jobsPage > 1) setJobsPage(current => current - 1);
            toast.success("岗位已删除");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    /** Persists one edited greeting while keeping result cards and the open detail dialog synchronized. */
    const handleSaveGreeting = async (jobId: number, greetingIndex: number, messageText: string) => {
        if (messageText.trim().length < 20) {
            toast.error("打招呼文案至少需要 20 个字符");
            return;
        }
        const key = `save:${jobId}:${greetingIndex}`;
        setActionKey(key);
        try {
            const response = await updateJobGreeting(jobId, greetingIndex, messageText.trim());
            setResults(current => replaceResultGreeting(current, jobId, greetingIndex, messageText.trim()));
            if (selectedJobId === jobId) setSelectedJob(response.job);
            toast.success("打招呼方案已保存");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "保存文案失败");
        } finally {
            setActionKey(null);
        }
    };

    /** Saves the current text and then adds the job to application tracking as 待投递. */
    const handleExportApplication = async (jobId: number, greetingIndex: number, messageText: string) => {
        if (messageText.trim().length < 20) {
            toast.error("请先补充完整打招呼文案");
            return;
        }
        const key = `export:${jobId}:${greetingIndex}`;
        setActionKey(key);
        try {
            const response = await exportJobToApplication(jobId, greetingIndex, messageText.trim());
            setResults(current => replaceResultGreeting(current, jobId, greetingIndex, messageText.trim()));
            if (selectedJobId === jobId) {
                const refreshed = await getJobDetail(jobId);
                setSelectedJob(refreshed.job);
            }
            toast.success(response.message || "已加入投递管理，状态为待投递");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "加入投递管理失败");
        } finally {
            setActionKey(null);
        }
    };

    /** Navigates the already-open logged-in BOSS tab to a persisted official job URL. */
    const handleOpenExistingBossTab = async (jobId: number) => {
        const key = `open:${jobId}`;
        setActionKey(key);
        try {
            const response = await openJobInExistingBossTab(jobId, browserChannel);
            toast.success(response.message);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "无法在现有 BOSS 标签页打开岗位");
        } finally {
            setActionKey(null);
        }
    };

    /** Updates a greeting in the open library detail without mutating the asset payload. */
    const updateSelectedGreeting = (greetingIndex: number, messageText: string) => {
        setSelectedJob(current => {
            if (!current) return current;
            const assetPayload = current.asset_payload || {};
            const greetings = [...(assetPayload.greetings || [])];
            const greeting = greetings[greetingIndex];
            if (!greeting) return current;
            greetings[greetingIndex] = { ...greeting, message_text: messageText };
            return { ...current, asset_payload: { ...assetPayload, greetings } };
        });
    };

    /** Renders three editable greeting schemes and exposes only save/export actions, never automatic sending. */
    const renderGreetingEditors = (
        jobId: number,
        greetings: GreetingItem[],
        onChange: (index: number, value: string) => void,
    ) => (
        <div className="space-y-3">
            {greetings.map((greeting, index) => (
                <div key={`${jobId}-${greeting.tone}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-semibold text-teal-700">
                            {TONE_LABELS[greeting.tone] || greeting.tone}
                        </div>
                        <div className="text-[10px] text-slate-400">{greeting.message_text.length} 字符</div>
                    </div>
                    <Textarea
                        className="mt-2 min-h-28 bg-white text-sm leading-6"
                        value={greeting.message_text}
                        onChange={event => onChange(index, event.target.value)}
                        maxLength={500}
                    />
                    {greeting.highlights_used && greeting.highlights_used.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                            {greeting.highlights_used.map(item => <Badge key={item} variant="outline">证据：{item}</Badge>)}
                        </div>
                    )}
                    {greeting.risk_notes && <p className="mt-2 text-xs text-amber-700">{greeting.risk_notes}</p>}
                    <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={actionKey !== null}
                            onClick={() => void handleSaveGreeting(jobId, index, greeting.message_text)}
                        >
                            {actionKey === `save:${jobId}:${index}` ? <Loader2 className="animate-spin" /> : <Save />}
                            保存文案
                        </Button>
                        <Button
                            size="sm"
                            className="bg-teal-700 hover:bg-teal-800"
                            disabled={actionKey !== null}
                            onClick={() => void handleExportApplication(jobId, index, greeting.message_text)}
                        >
                            {actionKey === `export:${jobId}:${index}` ? <Loader2 className="animate-spin" /> : <BriefcaseBusiness />}
                            加入投递管理
                        </Button>
                    </div>
                </div>
            ))}
            {greetings.length === 0 && (
                <div className="rounded-xl border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500">
                    资产文案尚未生成，请等待后台任务完成或在任务运行中重试。
                </div>
            )}
        </div>
    );

    /** Renders one current-import result card with its persisted assets and match score. */
    const renderResult = (job: CapturedJobSummary) => (
        <Card key={job.job_id} className="border-slate-200 shadow-sm">
            <CardHeader className="pb-3">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0">
                        <CardTitle className="text-base">{job.job_title}</CardTitle>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                            <span className="font-medium">{job.company_name || "公司未披露"}</span>
                            {job.company_size_text && <span>· {job.company_size_text}</span>}
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            <Badge variant="outline">{job.salary_text || "薪资未披露"}</Badge>
                            {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                            {job.asset_status && <Badge variant="outline">{ASSET_STATUS_LABELS[job.asset_status] || job.asset_status}</Badge>}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                            匹配度 {job.match_score != null ? `${job.match_score}%` : "计算中"}
                        </Badge>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={actionKey !== null}
                            onClick={() => void handleOpenExistingBossTab(job.job_id)}
                        >
                            {actionKey === `open:${job.job_id}` ? <Loader2 className="animate-spin" /> : <ExternalLink />}
                            已有标签页打开
                        </Button>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="space-y-4">
                {job.job_description && (
                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                        <div className="text-xs font-semibold text-slate-700">当前卡片可见职位介绍</div>
                        <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-600">{job.job_description}</p>
                    </div>
                )}
                {["queued", "retrying", "running"].includes(job.asset_status || "") && (
                    <div className="flex items-center gap-2 rounded-xl border border-teal-200 bg-teal-50 p-3 text-xs text-teal-800">
                        <Loader2 className="h-4 w-4 animate-spin" />资产正在后台生成；标准 Worker 最多并行处理 5 个岗位。
                    </div>
                )}
                {job.asset_status === "failed" && (
                    <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                        <AlertTriangle className="h-4 w-4" />资产生成失败，可在“任务运行”中查看原因并重试。
                    </div>
                )}
                {renderGreetingEditors(job.job_id, job.greetings, (index, value) => {
                    setResults(current => replaceResultGreeting(current, job.job_id, index, value));
                })}
                {job.risk_flags.length > 0 && (
                    <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <ul className="space-y-1">{job.risk_flags.map(flag => <li key={flag}>{flag}</li>)}</ul>
                    </div>
                )}
            </CardContent>
        </Card>
    );

    const detailAsset = selectedJob?.asset_payload || null;
    const detailGreetings = detailAsset?.greetings || [];
    const detailJdAnalysis = asRecord(detailAsset?.jd_analysis);
    const detailMatched = readStringList(detailJdAnalysis, "matched_keywords");
    const detailMissing = readStringList(detailJdAnalysis, "missing_keywords");
    const detailStrengths = readStringList(detailJdAnalysis, "strengths");
    const detailRisks = readStringList(detailJdAnalysis, "risks");

    return (
        <div className="mx-auto h-full w-full max-w-7xl p-5 sm:p-6">
            <Tabs defaultValue="recommendations" className="flex h-full flex-col">
                <div className="surface-panel flex flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center">
                    <div>
                        <h1 className="text-lg font-semibold text-slate-950">岗位中心</h1>
                        <p className="mt-1 text-xs text-slate-500">复用现有登录 BOSS 标签页，导入非实习岗位并生成可编辑投递资产。</p>
                    </div>
                    <TabsList>
                        <TabsTrigger value="recommendations">浏览器接管</TabsTrigger>
                        <TabsTrigger value="library">岗位库 {jobsTotal > 0 ? `(${jobsTotal})` : ""}</TabsTrigger>
                    </TabsList>
                </div>

                <TabsContent value="recommendations" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
                        <div className="space-y-4">
                            <Card>
                                <CardHeader>
                                    <CardTitle className="flex items-center gap-2 text-base"><Monitor className="h-4 w-4" />现有 BOSS 标签页</CardTitle>
                                </CardHeader>
                                <CardContent className="space-y-4">
                                    <label className="grid gap-2 text-xs text-slate-600">浏览器
                                        <Select value={browserChannel} onValueChange={value => setBrowserChannel(value as BossBrowserChannel)}>
                                            <SelectTrigger><SelectValue /></SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="msedge">Microsoft Edge</SelectItem>
                                                <SelectItem value="chrome">Google Chrome</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </label>
                                    <Button variant="outline" className="w-full" disabled={checkingTab} onClick={() => void handleConnectBrowserTab()}>
                                        {checkingTab ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                                        检查已打开页面
                                    </Button>
                                    {tabStatus && (
                                        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-800">
                                            <div className="font-semibold">{tabStatus.browser_label} · {tabStatus.page_status}</div>
                                            <div>{tabStatus.message}</div>
                                            {tabStatus.visible_card_count > 0 && <div>当前识别 {tabStatus.visible_card_count} 张岗位卡片</div>}
                                        </div>
                                    )}
                                    {tabError && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">{tabError}</div>}
                                </CardContent>
                            </Card>

                            <Card>
                                <CardHeader>
                                    <CardTitle className="flex items-center gap-2 text-base"><Search className="h-4 w-4" />搜索与简历匹配</CardTitle>
                                </CardHeader>
                                <CardContent className="space-y-4">
                                    <label className="grid gap-2 text-xs text-slate-600">搜索关键词
                                        <Input value={query} onChange={event => setQuery(event.target.value)} maxLength={200} placeholder="例如 Agent 后端工程师" />
                                    </label>
                                    <div className="grid gap-3 sm:grid-cols-[1fr_130px] xl:grid-cols-1">
                                        <label className="grid gap-2 text-xs text-slate-600">热门城市（中文选择）
                                            <Select value={city || "reuse-current"} onValueChange={value => setCity(value === "reuse-current" ? "" : value)}>
                                                <SelectTrigger><SelectValue /></SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="reuse-current">复用当前页城市</SelectItem>
                                                    {BOSS_HOT_CITIES.map(item => (
                                                        <SelectItem key={item.code} value={item.code}>{item.name}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </label>
                                        <label className="grid gap-2 text-xs text-slate-600">已选城市代码
                                            <Input value={city} readOnly placeholder="复用当前页" className="font-mono" />
                                        </label>
                                    </div>
                                    <label className="grid gap-2 text-xs text-slate-600">结果数量（最多 20）
                                        <Input
                                            type="number"
                                            min={1}
                                            max={20}
                                            value={topN}
                                            onChange={event => setTopN(Math.min(20, Math.max(1, Number(event.target.value) || 1)))}
                                        />
                                    </label>
                                    <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-900">
                                        基础简历会参与筛选：先计算透明关键词重合分，再由 Fast 模型做语义匹配，默认按 20% 关键词分 + 80% 语义分排序；模型解析失败时自动回退本地关键词分。
                                    </div>
                                    <div className="space-y-2">
                                        <div className="flex items-center justify-between gap-2">
                                            <span className="text-xs text-slate-600">基础简历</span>
                                            <input ref={resumeFileInputRef} type="file" className="hidden" accept=".pdf,.doc,.docx,.txt,.md" onChange={event => void handleResumeUpload(event)} />
                                            <Button type="button" variant="outline" size="sm" disabled={resumeUploading} onClick={() => resumeFileInputRef.current?.click()}>
                                                {resumeUploading ? <Loader2 className="animate-spin" /> : <Upload />}
                                                {resumeUploading ? "解析中" : "上传并解析"}
                                            </Button>
                                        </div>
                                        <Textarea
                                            className="min-h-56 text-xs leading-5"
                                            value={resumeContent}
                                            onChange={event => setResumeContent(event.target.value)}
                                            placeholder="粘贴基础简历；它会用于岗位排序、匹配度分析、定制简历和打招呼文案。"
                                        />
                                    </div>
                                    <Button className="w-full bg-teal-700 hover:bg-teal-800" onClick={() => void handleRecommendations()} disabled={captureBusy || checkingTab}>
                                        {captureBusy ? <Loader2 className="animate-spin" /> : <Sparkles />}
                                        接管页面并采集
                                    </Button>
                                </CardContent>
                            </Card>
                        </div>

                        <div className="space-y-4">
                            {captureRun && (
                                <div className={`surface-panel border p-4 ${captureRun.status === "failed" ? "border-red-200" : "border-slate-200"}`}>
                                    <div className="flex flex-wrap items-start justify-between gap-3">
                                        <div>
                                            <div className="text-sm font-semibold text-slate-900">{captureRun.title}</div>
                                            <p className="mt-1 text-xs text-slate-500">{captureRunMessage(captureRun, captureElapsed)}</p>
                                            {captureRun.error_message && <p className="mt-2 text-xs text-red-700">{captureRun.error_message}</p>}
                                        </div>
                                        <Badge variant="outline">{getAgentRunStatusLabel(captureRun)}</Badge>
                                    </div>
                                    <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                                        {captureRun.plan.map(step => (
                                            <li key={step.id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                                                step.status === "completed"
                                                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                                                    : step.status === "running"
                                                        ? "border-teal-200 bg-teal-50 text-teal-800"
                                                        : step.status === "failed"
                                                            ? "border-red-200 bg-red-50 text-red-800"
                                                            : "border-slate-200 bg-slate-50 text-slate-500"
                                            }`}>
                                                {step.status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                                                {step.status === "completed" && <CheckCircle2 className="h-3.5 w-3.5" />}
                                                {step.status === "failed" && <AlertTriangle className="h-3.5 w-3.5" />}
                                                {step.status === "pending" && <span className="h-2 w-2 rounded-full bg-slate-300" />}
                                                {step.title}
                                            </li>
                                        ))}
                                    </ol>
                                </div>
                            )}
                            {results.length === 0 && !captureRun ? (
                                <div className="surface-panel flex min-h-72 flex-col items-center justify-center text-center">
                                    <Sparkles className="h-9 w-9 text-slate-300" />
                                    <div className="mt-3 text-sm font-medium text-slate-900">等待本次采集结果</div>
                                    <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">这里会显示岗位、薪资、公司人数、职位介绍、匹配度和三种可编辑打招呼方案。</p>
                                </div>
                            ) : results.map(renderResult)}
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="library" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <section className="surface-panel overflow-hidden">
                        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                            <div>
                                <h2 className="text-sm font-semibold">已导入岗位</h2>
                                <p className="mt-1 text-xs text-slate-500">点击岗位查看完整资产、编辑文案并加入投递管理。</p>
                            </div>
                            <Button variant="outline" size="sm" onClick={() => void refreshJobs(true, true)} disabled={jobsLoading}>
                                {jobsLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}刷新
                            </Button>
                        </div>
                        {jobsError && <div className="border-b border-red-100 bg-red-50 px-5 py-3 text-xs text-red-700">{jobsError}</div>}
                        <div className="divide-y divide-slate-100">
                            {!jobsLoading && jobs.length === 0 && <div className="py-16 text-center text-sm text-slate-400">岗位库为空</div>}
                            {jobs.map(job => (
                                <div key={job.id} className="flex items-center gap-2 px-3 py-2 hover:bg-slate-50">
                                    <button type="button" className="min-w-0 flex-1 rounded-lg px-2 py-2 text-left" onClick={() => void handleOpenJobDetail(job.id)}>
                                        <div className="flex flex-wrap items-start justify-between gap-3">
                                            <div className="min-w-0">
                                                <div className="truncate text-sm font-medium text-slate-900">{job.job_title}</div>
                                                <div className="mt-1 text-xs text-slate-600">
                                                    {job.company_name || "公司未披露"}{job.company_size_text ? ` · ${job.company_size_text}` : ""}
                                                </div>
                                            </div>
                                            <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                                                匹配度 {job.match_score != null ? `${job.match_score}%` : "待分析"}
                                            </Badge>
                                        </div>
                                        <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                                            <Badge variant="outline">{job.salary_text || "薪资未披露"}</Badge>
                                            {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                                            {job.asset_status && <Badge variant="outline">{ASSET_STATUS_LABELS[job.asset_status] || job.asset_status}</Badge>}
                                            <span>{formatDate(job.captured_at)}</span>
                                        </div>
                                    </button>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-8 w-8 shrink-0 text-red-500 hover:bg-red-50 hover:text-red-700"
                                        onClick={() => void handleDelete(job)}
                                        aria-label={`删除 ${job.job_title}`}
                                    >
                                        <Trash2 className="h-4 w-4" />
                                    </Button>
                                </div>
                            ))}
                        </div>
                        <PaginationControls
                            className="border-t border-slate-100 px-5 py-4"
                            page={jobsPage}
                            total={jobsTotal}
                            loading={jobsLoading}
                            onPageChange={setJobsPage}
                        />
                    </section>
                </TabsContent>
            </Tabs>

            <Dialog open={selectedJobId !== null} onOpenChange={open => {
                if (!open) {
                    setSelectedJobId(null);
                    setSelectedJob(null);
                    setDetailError(null);
                }
            }}>
                <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>岗位资产详情</DialogTitle>
                        <DialogDescription>这里只展示和编辑投递资产；不会预览、填写或发送 BOSS 消息。</DialogDescription>
                    </DialogHeader>
                    {detailLoading && <div className="flex items-center justify-center py-20 text-sm text-slate-500"><Loader2 className="mr-2 animate-spin" />加载岗位资产...</div>}
                    {detailError && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{detailError}</div>}
                    {selectedJob && (
                        <div className="space-y-5">
                            <section className="rounded-xl border border-slate-200 p-4">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div>
                                        <h3 className="text-lg font-semibold text-slate-950">{selectedJob.job_title}</h3>
                                        <div className="mt-1 flex items-center gap-2 text-sm text-slate-600">
                                            <Building2 className="h-4 w-4" />
                                            {selectedJob.company_name || "公司未披露"}
                                            {selectedJob.company_size_text && <span>· {selectedJob.company_size_text}</span>}
                                        </div>
                                    </div>
                                    <Badge className="bg-teal-50 text-teal-700 hover:bg-teal-50">
                                        匹配度 {selectedJob.match_score != null ? `${selectedJob.match_score}%` : "待分析"}
                                    </Badge>
                                </div>
                                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                    <Badge variant="outline">{selectedJob.salary_text || "薪资未披露"}</Badge>
                                    {selectedJob.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{selectedJob.city}</span>}
                                    {selectedJob.asset_status && <Badge variant="outline">{ASSET_STATUS_LABELS[selectedJob.asset_status] || selectedJob.asset_status}</Badge>}
                                    {detailAsset?.custom_resume_id && <Badge variant="outline">定制简历 #{detailAsset.custom_resume_id}</Badge>}
                                </div>
                                <div className="mt-4 flex flex-wrap gap-2">
                                    <Button variant="outline" disabled={actionKey !== null} onClick={() => void handleOpenExistingBossTab(selectedJob.id)}>
                                        {actionKey === `open:${selectedJob.id}` ? <Loader2 className="animate-spin" /> : <ExternalLink />}
                                        在已有 BOSS 标签页打开
                                    </Button>
                                </div>
                                {selectedJob.source_url && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">{selectedJob.source_url}</p>}
                            </section>

                            <section className="rounded-xl border border-slate-200 p-4">
                                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><FileText className="h-4 w-4" />职位介绍</h3>
                                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{selectedJob.job_description || "当前岗位没有可展示的职位介绍。"}</p>
                            </section>

                            <section className="rounded-xl border border-slate-200 p-4">
                                <h3 className="text-sm font-semibold text-slate-900">JD 匹配分析</h3>
                                {!detailJdAnalysis ? (
                                    <p className="mt-3 text-sm text-slate-500">详细 JD 分析尚未生成；岗位库仍保留初筛匹配度。</p>
                                ) : (
                                    <div className="mt-3 grid gap-4 md:grid-cols-2">
                                        <div>
                                            <div className="text-xs font-semibold text-emerald-700">匹配关键词</div>
                                            <div className="mt-2 flex flex-wrap gap-1">{detailMatched.map(item => <Badge key={item} variant="outline">{item}</Badge>)}</div>
                                        </div>
                                        <div>
                                            <div className="text-xs font-semibold text-amber-700">缺失关键词</div>
                                            <div className="mt-2 flex flex-wrap gap-1">{detailMissing.map(item => <Badge key={item} variant="outline">{item}</Badge>)}</div>
                                        </div>
                                        {detailStrengths.length > 0 && <div><div className="text-xs font-semibold text-slate-700">优势</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{detailStrengths.map(item => <li key={item}>{item}</li>)}</ul></div>}
                                        {detailRisks.length > 0 && <div><div className="text-xs font-semibold text-red-700">风险</div><ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{detailRisks.map(item => <li key={item}>{item}</li>)}</ul></div>}
                                    </div>
                                )}
                            </section>

                            <section>
                                <h3 className="mb-3 text-sm font-semibold text-slate-900">打招呼方案（可编辑）</h3>
                                {renderGreetingEditors(selectedJob.id, detailGreetings, updateSelectedGreeting)}
                            </section>
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}

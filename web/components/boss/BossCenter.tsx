"use client";

// 已知超限:职责单一(页面聚合器),暂不拆分
import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { BossCaptureRunPanel } from "@/components/boss/BossCaptureRunPanel";
import { BossImportBanner } from "@/components/boss/BossImportBanner";
import { BossJobDetailDialog } from "@/components/boss/BossJobDetailDialog";
import { BossLibraryPanel } from "@/components/boss/BossLibraryPanel";
import { BossResultsArea } from "@/components/boss/BossResultsArea";
import { BossSearchCapturePanel } from "@/components/boss/BossSearchCapturePanel";
import { BossTabStatusCard } from "@/components/boss/BossTabStatusCard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AgentRun } from "@/lib/api/agentRunTypes";
import { getAgentRun, listAgentRuns } from "@/lib/api/agentRuns";
import { getUserId } from "@/lib/api/config";
import {
    captureRecommendations,
    deleteJob,
    getBossBrowserTabStatus,
    getJobDetail,
    importCardsToLibrary,
    listJobs,
    openJobInExistingBossTab,
    searchAndCaptureBossBrowserTab,
    type BossBrowserChannel,
    type BossTabStatusResponse,
    type CapturedJobSummary,
    type JobDetail,
    type JobListItem,
} from "@/lib/api/jobs";
import { parseBossDomCapturePayload } from "@/lib/bossDomCapture";
import {
    ACTIVE_RUN_STATUSES,
    BOSS_HOT_CITIES,
    CAPTURE_STATE_KEY,
    getCaptureRunJobs,
    mergeAssetRun,
} from "@/lib/bossCenter";
import { buildJobContextSnapshot, type JobContextSnapshot } from "@/lib/jobContextHandoff";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { extractProfessionalSkills } from "@/lib/bossResume";
import { useInterviewStore } from "@/store/useInterviewStore";

interface BossCenterProps {
    initialJobId?: number | null;
    onInitialJobConsumed?: () => void;
    onUseInInterview: (snapshot: JobContextSnapshot) => void;
    onImportToResume: (snapshot: JobContextSnapshot) => void;
}

/** Main岗位中心：复用现有登录标签页采集，并管理可编辑岗位资料。 */
export function BossCenter({ initialJobId, onInitialJobConsumed, onUseInInterview, onImportToResume }: BossCenterProps) {
    const resume = useInterviewStore(state => state.resume);
    const uploadResume = useInterviewStore(state => state.uploadResume);
    const getApiConfigForRequest = useInterviewStore(state => state.getApiConfigForRequest);

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
    const pendingCardCount = results.filter(job => job.job_id == null).length;

    /** 标记本次挂载是否恢复了会话中的采集任务，用于避免被「最近任务」查询覆盖。 */
    const restoredCaptureRunRef = useRef(false);

    useEffect(() => {
        if (!defaultResumeText) return;
        const timer = window.setTimeout(() => setResumeContent(current => {
            if (current) return current;
            return extractProfessionalSkills(defaultResumeText).content;
        }), 0);
        return () => window.clearTimeout(timer);
    }, [defaultResumeText]);

    /** 切换主页面后恢复上次采集结果与任务状态；仅当存储用户与当前用户一致时生效。 */
    useEffect(() => {
        const timer = window.setTimeout(() => {
            try {
                const raw = sessionStorage.getItem(CAPTURE_STATE_KEY);
                if (!raw) return;
                const saved = JSON.parse(raw) as { userId?: string; results?: unknown; captureRun?: unknown } | null;
                if (!saved || saved.userId !== getUserId()) return;
                if (Array.isArray(saved.results)) setResults(saved.results as CapturedJobSummary[]);
                if (saved.captureRun && typeof saved.captureRun === "object") {
                    setCaptureRun(saved.captureRun as AgentRun);
                    restoredCaptureRunRef.current = true;
                }
            } catch {
                // 损坏或不可用的会话存储不阻断岗位中心。
            }
        }, 0);
        return () => window.clearTimeout(timer);
    }, []);

    /** 采集结果与任务状态写入会话存储；新采集、入库或删除时自动同步。 */
    useEffect(() => {
        try {
            sessionStorage.setItem(CAPTURE_STATE_KEY, JSON.stringify({ userId: getUserId(), results, captureRun }));
        } catch {
            // 隐私模式或配额限制时仅跳过持久化。
        }
    }, [results, captureRun]);

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
        // 会话中已有恢复的采集任务时，不再用「最近一次任务」覆盖展示。
        if (restoredCaptureRunRef.current) return;
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
            const extracted = extractProfessionalSkills(parsedResume.content);
            setResumeContent(extracted.content);
            toast.success(extracted.matched ? `已从 ${file.name} 提取专业技能` : `已从 ${file.name} 解析简历；未识别到专业技能段落，暂保留原文`);
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
        const resumeExtraction = extractProfessionalSkills(resumeContent);
        const effectiveResumeContent = resumeExtraction.content;
        if (resumeExtraction.matched && effectiveResumeContent !== resumeContent.trim()) {
            setResumeContent(effectiveResumeContent);
            toast.info("已按专业技能收敛基础简历，岗位采集不会使用其他简历段落。");
        } else if (!resumeExtraction.matched) {
            toast.info("未识别到专业技能段落，将保留当前原文继续匹配。");
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
                resume_content: effectiveResumeContent.trim(),
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
                toast.success(`已采集 ${importedJobs.length} 个岗位，确认后可一键入库`);
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

    /** 一键入库：只保存岗位与初筛信息；成功后卡片从结果区消失且不触发模型任务。 */
    const handleImportAll = async () => {
        const pending = results.filter(job => job.job_id == null);
        if (pending.length === 0) return;
        setActionKey("import:all");
        try {
            const response = await importCardsToLibrary({
                cards: pending.map(job => ({
                    company_name: job.company_name,
                    company_size_text: job.company_size_text || "",
                    job_title: job.job_title,
                    salary_text: job.salary_text,
                    city: job.city,
                    job_description: job.job_description || "",
                    source_url: job.source_url || "",
                    preliminary_match_score: job.match_score ?? undefined,
                })),
                city: city || undefined,
            });
            const failedUrls = new Set(response.failed.map(item => item.source_url));
            setResults(current => current.filter(job => (
                job.job_id != null || Boolean(job.source_url && failedUrls.has(job.source_url))
            )));
            if (response.total > 0) {
                setJobsPage(1);
                void refreshJobs(false);
            }
            toast.success(response.message || `已入库 ${response.total} 个岗位`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "一键入库失败");
        } finally {
            setActionKey(null);
        }
    };

    /** 删除一张尚未入库的采集卡片；删除的岗位不会进入岗位库。 */
    const handleDeletePending = (job: CapturedJobSummary) => {
        if (!job.source_url) return;
        if (!window.confirm(`确认删除「${job.company_name || "公司未披露"} · ${job.job_title}」？该岗位不会进入岗位库。`)) return;
        setResults(current => current.filter(item => item.source_url !== job.source_url));
        toast.success("已删除待入库卡片");
    };

    useEffect(() => {
        if (!initialJobId) return;
        queueMicrotask(() => {
            void handleOpenJobDetail(initialJobId).finally(() => onInitialJobConsumed?.());
        });
    }, [initialJobId, onInitialJobConsumed]);

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



    return (
        <div className="mx-auto h-full w-full max-w-7xl p-5 sm:p-6">
            <Tabs defaultValue="recommendations" className="flex h-full flex-col">
                <div className="surface-panel flex flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center">
                    <div>
                        <h1 className="text-lg font-semibold text-slate-950">岗位中心</h1>
                        <p className="mt-1 text-xs text-slate-500">复用现有登录 BOSS 标签页，导入非实习岗位并整理可用的岗位资料。</p>
                    </div>
                    <TabsList>
                        <TabsTrigger value="recommendations">浏览器接管</TabsTrigger>
                        <TabsTrigger value="library">岗位库 {jobsTotal > 0 ? `(${jobsTotal})` : ""}</TabsTrigger>
                    </TabsList>
                </div>

                <TabsContent value="recommendations" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
                        <div className="space-y-4">
                            <BossTabStatusCard
                                browserChannel={browserChannel}
                                onBrowserChannelChange={setBrowserChannel}
                                checkingTab={checkingTab}
                                onCheckTab={() => void handleConnectBrowserTab()}
                                tabStatus={tabStatus}
                                tabError={tabError}
                            />
                            <BossSearchCapturePanel
                                query={query}
                                onQueryChange={setQuery}
                                city={city}
                                onCityChange={setCity}
                                topN={topN}
                                onTopNChange={setTopN}
                                resumeContent={resumeContent}
                                onResumeContentChange={setResumeContent}
                                resumeUploading={resumeUploading}
                                onResumeUpload={event => void handleResumeUpload(event)}
                                captureBusy={captureBusy}
                                checkingTab={checkingTab}
                                onCapture={() => void handleRecommendations()}
                            />
                        </div>

                        <div className="space-y-4">
                            {captureRun && (
                                <BossCaptureRunPanel captureRun={captureRun} captureElapsed={captureElapsed} />
                            )}
                            {pendingCardCount > 0 && (
                                <BossImportBanner
                                    pendingCardCount={pendingCardCount}
                                    actionKey={actionKey}
                                    onImportAll={() => void handleImportAll()}
                                />
                            )}
                            <BossResultsArea
                                results={results}
                                captureRun={captureRun}
                                actionKey={actionKey}
                                onDeletePending={handleDeletePending}
                                onOpenExistingBossTab={jobId => void handleOpenExistingBossTab(jobId)}
                            />
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="library" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <BossLibraryPanel
                        jobs={jobs}
                        jobsLoading={jobsLoading}
                        jobsError={jobsError}
                        jobsTotal={jobsTotal}
                        jobsPage={jobsPage}
                        onPageChange={setJobsPage}
                        onRefresh={() => void refreshJobs(true, true)}
                        onOpenDetail={jobId => void handleOpenJobDetail(jobId)}
                        onDelete={job => void handleDelete(job)}
                    />
                </TabsContent>
            </Tabs>

            <BossJobDetailDialog
                open={selectedJobId !== null}
                onClose={() => {
                    setSelectedJobId(null);
                    setSelectedJob(null);
                    setDetailError(null);
                }}
                selectedJob={selectedJob}
                loading={detailLoading}
                error={detailError}
                actionKey={actionKey}
                onOpenExistingBossTab={jobId => void handleOpenExistingBossTab(jobId)}
                onUseInInterview={() => {
                    if (selectedJob) onUseInInterview(buildJobContextSnapshot(selectedJob));
                }}
                onImportToResume={() => {
                    if (selectedJob) onImportToResume(buildJobContextSnapshot(selectedJob));
                }}
            />
        </div>
    );
}

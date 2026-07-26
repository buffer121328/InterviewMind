"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
    AlertTriangle,
    BriefcaseBusiness,
    CheckCircle2,
    FileSearch,
    Loader2,
    MapPin,
    RefreshCw,
    Search,
    Send,
    ShieldCheck,
    Sparkles,
    Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import {
    captureJob,
    captureRecommendations,
    deleteJob,
    listJobs,
    previewJobApplication,
    sendJobApplication,
    type ApplyResponse,
    type CapturedJobSummary,
    type JobCaptureResponse,
    type JobListItem,
} from "@/lib/api/jobs";
import { useInterviewStore } from "@/store/useInterviewStore";

type ApplyDraft = {
    job: CapturedJobSummary;
    greetingIndex: number;
    greetingText: string;
};

function formatDate(value?: string) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function BossCenter() {
    const resume = useInterviewStore(state => state.resume);
    const getApiConfigForRequest = useInterviewStore(state => state.getApiConfigForRequest);

    const [query, setQuery] = useState("");
    const [resumeContent, setResumeContent] = useState("");
    const [topN, setTopN] = useState(3);
    const [city, setCity] = useState("");
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState<CapturedJobSummary[]>([]);
    const [jobs, setJobs] = useState<JobListItem[]>([]);
    const [jobsLoading, setJobsLoading] = useState(false);
    const [jobsError, setJobsError] = useState<string | null>(null);

    const [captureMode, setCaptureMode] = useState<"text" | "url">("text");
    const [manualForm, setManualForm] = useState({
        source_url: "",
        job_description: "",
        platform: "boss",
        company_name_hint: "",
        job_title_hint: "",
    });
    const [manualResult, setManualResult] = useState<JobCaptureResponse | null>(null);
    const [manualLoading, setManualLoading] = useState(false);

    const [applyDraft, setApplyDraft] = useState<ApplyDraft | null>(null);
    const [applyPreview, setApplyPreview] = useState<ApplyResponse | null>(null);
    const [applyLoading, setApplyLoading] = useState(false);

    const defaultResumeText = useMemo(() => resume?.content || "", [resume]);

    useEffect(() => {
        if (!defaultResumeText) return;
        const timer = window.setTimeout(() => setResumeContent(current => current || defaultResumeText), 0);
        return () => window.clearTimeout(timer);
    }, [defaultResumeText]);

    const refreshJobs = useCallback(async (showLoading = true, notify = false) => {
        if (showLoading) setJobsLoading(true);
        try {
            const response = await listJobs({ limit: 100 });
            if (response.success) setJobs(response.jobs || []);
            setJobsError(null);
        } catch (error) {
            const message = error instanceof Error ? error.message : "";
            const friendly = /failed to fetch/i.test(message) ? "无法连接后端，岗位库暂时不可用。" : message || "加载岗位库失败";
            setJobsError(friendly);
            if (notify) toast.error(friendly);
        } finally {
            if (showLoading) setJobsLoading(false);
        }
    }, []);

    useEffect(() => {
        const timer = window.setTimeout(() => void refreshJobs(), 0);
        return () => window.clearTimeout(timer);
    }, [refreshJobs]);

    const requireApiConfig = () => {
        const apiConfig = getApiConfigForRequest();
        if (!apiConfig) {
            toast.error("请先配置 Smart 与 Fast 模型通道");
            return null;
        }
        return apiConfig;
    };

    const handleRecommendations = async () => {
        if (!query.trim()) {
            toast.error("请填写搜索关键词");
            return;
        }
        if (!resumeContent.trim()) {
            toast.error("请提供基础简历内容");
            return;
        }
        const apiConfig = requireApiConfig();
        if (!apiConfig) return;

        setLoading(true);
        try {
            toast.info("正在请求宿主机 Playwright 服务；若出现验证码，请在项目专用浏览器中手动完成。");
            const response = await captureRecommendations({
                query: query.trim(),
                resume_content: resumeContent.trim(),
                top_n: Math.min(10, Math.max(1, topN)),
                city: city.trim() || undefined,
                api_config: apiConfig,
            });
            if (!response.success || response.jobs.length === 0) {
                toast.warning(response.message || "没有采集到匹配岗位");
                return;
            }
            setResults(response.jobs);
            const queued = response.jobs.filter(job => ["queued", "retrying", "running"].includes(job.asset_status || "")).length;
            toast.success(queued > 0 ? `已采集 ${response.total} 个岗位，${queued} 个资产任务进入任务运行` : `已采集并处理 ${response.total} 个岗位`);
            void refreshJobs(false);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "批量采集失败");
        } finally {
            setLoading(false);
        }
    };

    const handleManualCapture = async () => {
        const source = captureMode === "url" ? manualForm.source_url.trim() : manualForm.job_description.trim();
        if (!source) {
            toast.error(captureMode === "url" ? "请填写岗位 URL" : "请粘贴 JD 内容");
            return;
        }
        const apiConfig = requireApiConfig();
        if (!apiConfig) return;

        setManualLoading(true);
        setManualResult(null);
        try {
            const response = await captureJob({
                source_url: captureMode === "url" ? source : undefined,
                job_description: captureMode === "text" ? source : undefined,
                platform: manualForm.platform.trim() || "manual",
                company_name_hint: manualForm.company_name_hint.trim() || undefined,
                job_title_hint: manualForm.job_title_hint.trim() || undefined,
                api_config: apiConfig,
                headless: true,
            });
            setManualResult(response);
            if (response.success) {
                toast.success(response.is_duplicate ? "岗位已存在，已返回现有记录" : "岗位已采集并标准化");
                void refreshJobs(false);
            } else {
                toast.error(response.message || "岗位采集失败");
            }
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "岗位采集失败");
        } finally {
            setManualLoading(false);
        }
    };

    const handleDelete = async (job: JobListItem) => {
        if (!window.confirm(`确认从岗位库删除「${job.company_name} · ${job.job_title}」？`)) return;
        try {
            await deleteJob(job.id);
            setJobs(current => current.filter(item => item.id !== job.id));
            toast.success("岗位已删除");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "删除失败");
        }
    };

    const openApplyPreview = async (draft: ApplyDraft) => {
        setApplyDraft(draft);
        setApplyPreview(null);
        setApplyLoading(true);
        try {
            const response = await previewJobApplication({
                job_id: draft.job.job_id,
                greeting_index: draft.greetingIndex,
                greeting_text: draft.greetingText,
                resume_id: draft.job.custom_resume_id || undefined,
            });
            setApplyPreview(response);
            if (!response.success) toast.error(response.message || response.error || "生成投递预览失败");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "生成投递预览失败");
        } finally {
            setApplyLoading(false);
        }
    };

    const confirmApply = async () => {
        if (!applyDraft || !applyPreview?.approval_token || !applyPreview.send_ready) return;
        setApplyLoading(true);
        try {
            const response = await sendJobApplication({
                job_id: applyDraft.job.job_id,
                greeting_index: applyDraft.greetingIndex,
                greeting_text: applyDraft.greetingText,
                resume_id: applyDraft.job.custom_resume_id || undefined,
                approval_token: applyPreview.approval_token,
                confirmed: true,
            });
            setApplyPreview(response);
            if (response.success && response.send_status === "sent") {
                toast.success("投递动作已完成，请在 BOSS 页面复核");
                setApplyDraft(null);
            } else {
                toast.warning(response.message || response.error || `发送状态：${response.send_status}`);
            }
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "发送失败；若状态不明确，请人工复核后再操作");
        } finally {
            setApplyLoading(false);
        }
    };

    const renderResult = (job: CapturedJobSummary) => (
        <Card key={job.job_id} className="border-slate-200 shadow-sm">
            <CardHeader className="pb-3">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                    <div>
                        <CardTitle className="text-base">{job.job_title} · {job.company_name}</CardTitle>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            {job.salary_text && <Badge variant="outline">{job.salary_text}</Badge>}
                            {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                            {job.custom_resume_id && <Badge variant="outline">定制简历 #{job.custom_resume_id}</Badge>}
                        </div>
                    </div>
                    {job.match_score != null && <Badge className="w-fit bg-teal-50 text-teal-700 hover:bg-teal-50">匹配度 {job.match_score}%</Badge>}
                </div>
            </CardHeader>
            <CardContent className="space-y-3">
                {["queued", "retrying", "running"].includes(job.asset_status || "") && (
                    <div className="flex items-center gap-2 rounded-xl border border-teal-200 bg-teal-50 p-3 text-xs text-teal-800">
                        <Loader2 className="h-4 w-4 animate-spin" />投递资产正在后台生成，可前往“任务运行”查看阶段。
                    </div>
                )}
                {job.asset_status === "failed" && (
                    <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                        <AlertTriangle className="h-4 w-4" />资产生成失败，可在“任务运行”中查看原因和重试条件。
                    </div>
                )}
                {job.greetings.map((greeting, index) => (
                    <div key={`${job.job_id}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                        <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                                <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-teal-700">{greeting.tone}</div>
                                <p className="mt-1 text-xs leading-5 text-slate-700">{greeting.message_text}</p>
                                {greeting.risk_notes && <p className="mt-2 text-[10px] text-amber-700">{greeting.risk_notes}</p>}
                            </div>
                            <Button variant="outline" size="sm" className="shrink-0" onClick={() => void openApplyPreview({ job, greetingIndex: index, greetingText: greeting.message_text })}>
                                <ShieldCheck className="h-3.5 w-3.5" />投递预览
                            </Button>
                        </div>
                    </div>
                ))}
                {job.risk_flags.length > 0 && (
                    <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <ul className="space-y-1">{job.risk_flags.map(flag => <li key={flag}>{flag}</li>)}</ul>
                    </div>
                )}
            </CardContent>
        </Card>
    );

    return (
        <div className="mx-auto h-full w-full max-w-7xl p-5 sm:p-6">
            <Tabs defaultValue="recommendations" className="flex h-full flex-col">
                <div className="surface-panel flex flex-col justify-between gap-4 p-4 sm:flex-row sm:items-center">
                    <div>
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><BriefcaseBusiness className="h-4 w-4 text-teal-700" />岗位采集与投递资产</div>
                        <p className="mt-1 text-xs text-slate-500">BOSS 自动化是可选宿主机能力，真实发送始终需要预览和再次确认。</p>
                    </div>
                    <TabsList className="h-auto bg-slate-100 p-1">
                        <TabsTrigger value="recommendations">推荐采集</TabsTrigger>
                        <TabsTrigger value="manual">单 JD 采集</TabsTrigger>
                        <TabsTrigger value="library">岗位库 {jobs.length}</TabsTrigger>
                    </TabsList>
                </div>

                {jobsError && <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">{jobsError}</div>}

                <TabsContent value="recommendations" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <div className="grid gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
                        <Card className="h-fit border-slate-200 shadow-sm">
                            <CardHeader><CardTitle className="text-base">搜索推荐页</CardTitle></CardHeader>
                            <CardContent className="space-y-4">
                                <label className="grid gap-2 text-xs text-slate-600">搜索关键词
                                    <Input value={query} onChange={event => setQuery(event.target.value)} placeholder="例如 AI Agent 后端工程师" />
                                </label>
                                <div className="grid grid-cols-2 gap-3">
                                    <label className="grid gap-2 text-xs text-slate-600">城市
                                        <Input value={city} onChange={event => setCity(event.target.value)} placeholder="可选" />
                                    </label>
                                    <label className="grid gap-2 text-xs text-slate-600">结果数量
                                        <Input type="number" min={1} max={10} value={topN} onChange={event => setTopN(Number(event.target.value) || 3)} />
                                    </label>
                                </div>
                                <label className="grid gap-2 text-xs text-slate-600">基础简历
                                    <Textarea rows={10} value={resumeContent} onChange={event => setResumeContent(event.target.value)} placeholder="用于匹配评分、定制简历和招呼语生成" />
                                </label>
                                <Button className="w-full bg-teal-700 hover:bg-teal-800" onClick={() => void handleRecommendations()} disabled={loading}>
                                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                                    {loading ? "采集中，请在浏览器完成必要验证" : "采集并生成投递资产"}
                                </Button>
                                <p className="text-[10px] leading-5 text-slate-500">需要后端已配置宿主机 Playwright 服务，并使用项目专用登录 profile。系统不会绕过验证码。</p>
                            </CardContent>
                        </Card>
                        <div className="space-y-3">
                            {results.length === 0 ? (
                                <div className="surface-panel flex min-h-72 flex-col items-center justify-center text-center">
                                    <Sparkles className="h-9 w-9 text-slate-300" />
                                    <div className="mt-3 text-sm font-medium text-slate-900">等待本次采集结果</div>
                                    <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">岗位会按匹配结果展示；资产长任务可在“任务运行”继续追踪。</p>
                                </div>
                            ) : results.map(renderResult)}
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="manual" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
                        <Card className="border-slate-200 shadow-sm">
                            <CardHeader><CardTitle className="text-base">采集一个岗位</CardTitle></CardHeader>
                            <CardContent className="space-y-4">
                                <div className="grid grid-cols-2 gap-2">
                                    <button type="button" className={`rounded-lg border px-3 py-2 text-xs ${captureMode === "text" ? "border-teal-600 bg-teal-50 text-teal-800" : "border-slate-200 text-slate-600"}`} onClick={() => setCaptureMode("text")}>粘贴 JD</button>
                                    <button type="button" className={`rounded-lg border px-3 py-2 text-xs ${captureMode === "url" ? "border-teal-600 bg-teal-50 text-teal-800" : "border-slate-200 text-slate-600"}`} onClick={() => setCaptureMode("url")}>岗位 URL</button>
                                </div>
                                {captureMode === "text" ? (
                                    <label className="grid gap-2 text-xs text-slate-600">JD 正文
                                        <Textarea rows={12} value={manualForm.job_description} onChange={event => setManualForm(current => ({ ...current, job_description: event.target.value }))} placeholder="粘贴完整岗位描述" />
                                    </label>
                                ) : (
                                    <label className="grid gap-2 text-xs text-slate-600">岗位 URL
                                        <Input value={manualForm.source_url} onChange={event => setManualForm(current => ({ ...current, source_url: event.target.value }))} placeholder="https://..." />
                                    </label>
                                )}
                                <div className="grid gap-3 sm:grid-cols-3">
                                    <label className="grid gap-2 text-xs text-slate-600">平台
                                        <Input value={manualForm.platform} onChange={event => setManualForm(current => ({ ...current, platform: event.target.value }))} />
                                    </label>
                                    <label className="grid gap-2 text-xs text-slate-600">公司提示
                                        <Input value={manualForm.company_name_hint} onChange={event => setManualForm(current => ({ ...current, company_name_hint: event.target.value }))} />
                                    </label>
                                    <label className="grid gap-2 text-xs text-slate-600">岗位提示
                                        <Input value={manualForm.job_title_hint} onChange={event => setManualForm(current => ({ ...current, job_title_hint: event.target.value }))} />
                                    </label>
                                </div>
                                <Button className="bg-teal-700 hover:bg-teal-800" onClick={() => void handleManualCapture()} disabled={manualLoading}>
                                    {manualLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}采集并标准化
                                </Button>
                            </CardContent>
                        </Card>
                        <Card className="h-fit border-slate-200 shadow-sm">
                            <CardHeader><CardTitle className="text-base">标准化结果</CardTitle></CardHeader>
                            <CardContent>
                                {!manualResult ? (
                                    <p className="text-xs leading-6 text-slate-500">后端会提取公司、岗位、城市、薪资、标签和 JD 正文，并按用户隔离保存。</p>
                                ) : manualResult.success && manualResult.normalized_job ? (
                                    <div className="space-y-3 text-xs">
                                        <div className="flex items-center gap-2 text-emerald-700"><CheckCircle2 className="h-4 w-4" />{manualResult.is_duplicate ? "已匹配现有岗位" : "采集成功"}</div>
                                        <dl className="space-y-2 rounded-xl bg-slate-50 p-3">
                                            <div><dt className="text-slate-400">公司</dt><dd className="mt-0.5 text-slate-800">{manualResult.normalized_job.company_name || "-"}</dd></div>
                                            <div><dt className="text-slate-400">岗位</dt><dd className="mt-0.5 text-slate-800">{manualResult.normalized_job.job_title || "-"}</dd></div>
                                            <div><dt className="text-slate-400">地点 / 薪资</dt><dd className="mt-0.5 text-slate-800">{[manualResult.normalized_job.city, manualResult.normalized_job.salary_text].filter(Boolean).join(" · ") || "-"}</dd></div>
                                        </dl>
                                    </div>
                                ) : (
                                    <div className="text-xs text-red-700">{manualResult.message || "采集失败"}</div>
                                )}
                            </CardContent>
                        </Card>
                    </div>
                </TabsContent>

                <TabsContent value="library" className="min-h-0 flex-1 overflow-y-auto pt-4">
                    <section className="surface-panel overflow-hidden">
                        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                            <div><h2 className="text-sm font-semibold">已采集岗位</h2><p className="mt-1 text-xs text-slate-500">来自 URL、JD 文本和推荐页采集。</p></div>
                            <Button variant="outline" size="sm" onClick={() => void refreshJobs(true, true)} disabled={jobsLoading}>{jobsLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}刷新</Button>
                        </div>
                        <div className="divide-y divide-slate-100">
                            {!jobsLoading && jobs.length === 0 && <div className="py-16 text-center text-sm text-slate-400">岗位库为空</div>}
                            {jobs.map(job => (
                                <div key={job.id} className="flex items-start justify-between gap-4 px-5 py-4 hover:bg-slate-50">
                                    <div className="min-w-0">
                                        <div className="truncate text-sm font-medium text-slate-900">{job.job_title} · {job.company_name}</div>
                                        <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                                            {job.salary_text && <Badge variant="outline">{job.salary_text}</Badge>}
                                            {job.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.city}</span>}
                                            {job.platform && <Badge variant="outline">{String(job.platform)}</Badge>}
                                            {job.status && <Badge variant="outline">{job.status}</Badge>}
                                            <span>{formatDate(job.captured_at)}</span>
                                        </div>
                                    </div>
                                    <Button variant="ghost" size="icon" className="h-8 w-8 text-red-500 hover:bg-red-50 hover:text-red-700" onClick={() => void handleDelete(job)}><Trash2 className="h-4 w-4" /></Button>
                                </div>
                            ))}
                        </div>
                    </section>
                </TabsContent>
            </Tabs>

            <AlertDialog open={applyDraft !== null} onOpenChange={open => {
                if (!open && !applyLoading) {
                    setApplyDraft(null);
                    setApplyPreview(null);
                }
            }}>
                <AlertDialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
                    <AlertDialogHeader>
                        <AlertDialogTitle>真实投递前预览</AlertDialogTitle>
                        <AlertDialogDescription>后端只会在你点击“确认并发送”后消费本次短期许可。文案、岗位或简历发生变化时必须重新预览。</AlertDialogDescription>
                    </AlertDialogHeader>
                    {applyDraft && (
                        <div className="space-y-4">
                            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                                <div className="text-xs font-semibold text-slate-900">{applyDraft.job.job_title} · {applyDraft.job.company_name}</div>
                                <p className="mt-2 text-sm leading-6 text-slate-700">{applyDraft.greetingText}</p>
                                {applyDraft.job.custom_resume_id && <div className="mt-2 text-xs text-slate-500">定制简历 #{applyDraft.job.custom_resume_id}</div>}
                            </div>
                            {applyLoading && !applyPreview && <div className="flex items-center justify-center py-8 text-sm text-slate-500"><Loader2 className="mr-2 h-4 w-4 animate-spin" />生成浏览器预览...</div>}
                            {applyPreview?.screenshot_base64 && (
                                <div className="overflow-hidden rounded-xl border border-slate-200">
                                    <Image src={`data:image/png;base64,${applyPreview.screenshot_base64}`} alt="BOSS 投递预览" width={1200} height={760} unoptimized className="h-auto w-full" />
                                </div>
                            )}
                            {applyPreview && (
                                <div className={`rounded-xl border p-3 text-xs ${applyPreview.send_ready ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
                                    {applyPreview.message || applyPreview.error || `预览状态：${applyPreview.send_status}`}
                                    {applyPreview.approval_expires_in && <div className="mt-1">许可将在 {applyPreview.approval_expires_in} 秒后过期。</div>}
                                </div>
                            )}
                        </div>
                    )}
                    <AlertDialogFooter>
                        <AlertDialogCancel disabled={applyLoading}>取消</AlertDialogCancel>
                        <AlertDialogAction
                            className="bg-red-600 hover:bg-red-700"
                            disabled={applyLoading || !applyPreview?.send_ready || !applyPreview.approval_token}
                            onClick={event => {
                                event.preventDefault();
                                void confirmApply();
                            }}
                        >
                            {applyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                            确认并发送
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}

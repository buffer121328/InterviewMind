"use client";

/**
 * BOSS 半自动化中心
 *
 * 功能：
 * 1. 一键批量抓取 BOSS 推荐页/搜索页前 N 个匹配度最高的岗位
 * 2. 自动生成每个岗位的投递资产（匹配度分析 + 定制简历 + 3 条打招呼文案）
 * 3. 显示已采集岗位列表 / 删除单个岗位
 *
 * 依赖：
 * - lib/api/jobs.ts: 与后端 /api/jobs/capture-recommendations 等接口对接
 * - 需要在 macOS + 已登录 BOSS 的 Chrome + AppleScript JS 权限开启下运行
 */

import { useEffect, useState, useMemo, useCallback } from "react";
import { Search, Loader2, Briefcase, MapPin, Sparkles, Trash2, RefreshCw, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
    captureRecommendations,
    listJobs,
    deleteJob,
    type CapturedJobSummary,
    type JobListItem,
} from "@/lib/api/jobs";
import { useInterviewStore } from "@/store/useInterviewStore";

export function BossCenter() {
    // 简易状态
    const [query, setQuery] = useState("");
    const [resumeContent, setResumeContent] = useState("");
    const [topN, setTopN] = useState(3);
    const [city, setCity] = useState("");
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState<CapturedJobSummary[]>([]);
    const [jobs, setJobs] = useState<JobListItem[]>([]);
    const [jobsLoading, setJobsLoading] = useState(false);

    // 从 store 拿简历文本作默认值
    const resume = useInterviewStore((s) => s.resume);
    const apiConfig = useInterviewStore((s) => s.apiConfig);

    // useMemo 推导默认简历文本（避免 setState-in-effect 警告）
    const defaultResumeText = useMemo(() => {
        if (!resume) return "";
        // ResumeInfo 对象，用 content 字段
        const r = resume as { content?: string };
        return r.content || "";
    }, [resume]);

    // 异步同步默认简历内容（仅在用户没填过时回填一次）
    useEffect(() => {
        if (!defaultResumeText) return;
        const timer = setTimeout(() => {
            setResumeContent((prev) => prev || defaultResumeText);
        }, 0);
        return () => clearTimeout(timer);
    }, [defaultResumeText]);

    // 加载历史采集列表（用 useCallback 避免重复创建）
    const refreshJobs = useCallback(async (showLoading = true) => {
        if (showLoading) setJobsLoading(true);
        try {
            const resp = await listJobs({ platform: "boss", limit: 50 });
            if (resp.success) {
                setJobs(resp.jobs);
            }
        } catch (e) {
            console.error("加载岗位列表失败", e);
        } finally {
            if (showLoading) setJobsLoading(false);
        }
    }, []);

    // 首次挂载加载一次（用异步 IIFE + mounted flag 避免 setState-in-effect 警告）
    useEffect(() => {
        let mounted = true;
        (async () => {
            try {
                const resp = await listJobs({ platform: "boss", limit: 50 });
                if (mounted && resp.success) setJobs(resp.jobs);
            } catch (e) {
                console.error("加载岗位列表失败", e);
            } finally {
                if (mounted) setJobsLoading(false);
            }
        })();
        return () => { mounted = false; };
    }, []);

    // 触发批量抓取
    const handleCapture = async () => {
        if (!query.trim()) {
            toast.error("请填写搜索关键词");
            return;
        }
        if (!resumeContent.trim()) {
            toast.error("请提供简历内容");
            return;
        }
        setLoading(true);
        try {
            toast.info("后端将在 Chrome 中新开 BOSS 搜索页，若弹滑动验证码请手动完成（最长等 3 分钟）...");
            const resp = await captureRecommendations({
                query: query.trim(),
                resume_content: resumeContent,
                top_n: topN,
                city: city.trim() || undefined,
                api_config: apiConfig as unknown as Record<string, unknown>,
            });
            if (resp.success && resp.jobs.length > 0) {
                setResults(resp.jobs);
                toast.success(`抓取成功，共 ${resp.total} 个岗位，已生成投递资产`);
                refreshJobs();
            } else {
                toast.warning(resp.message || "抓取失败或未匹配到岗位");
            }
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            toast.error(`抓取失败: ${msg}`);
        } finally {
            setLoading(false);
        }
    };

    // 删除岗位
    const handleDelete = async (jobId: number) => {
        try {
            await deleteJob(jobId);
            toast.success("已删除");
            refreshJobs();
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            toast.error(`删除失败: ${msg}`);
        }
    };

    // 把新结果中第 i 项整理成展示卡片
    const renderSummary = (j: CapturedJobSummary, idx: number) => {
        const topGreeting = j.greetings?.[0];
        return (
            <Card key={`${j.job_id}-${idx}`} className="mb-3">
                <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                        <CardTitle className="text-base flex items-center gap-2">
                            <Briefcase size={16} className="text-orange-600" />
                            {j.job_title} @ {j.company_name}
                        </CardTitle>
                        {j.match_score != null && (
                            <Badge variant="secondary" className="text-emerald-700">
                                匹配度 {j.match_score}%
                            </Badge>
                        )}
                    </div>
                </CardHeader>
                <CardContent className="text-sm space-y-2">
                    <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                        {j.salary_text && <Badge variant="outline">{j.salary_text}</Badge>}
                        {j.city && <span className="inline-flex items-center gap-1"><MapPin size={12} />{j.city}</span>}
                        {j.greetings?.length > 0 && <Badge variant="outline">{j.greetings.length} 条打招呼</Badge>}
                        {j.custom_resume_id && <Badge variant="outline">简历 ID: {j.custom_resume_id}</Badge>}
                    </div>

                    {topGreeting && (
                        <div className="rounded-md bg-muted p-2 text-xs">
                            <div className="flex items-center gap-1 font-medium">
                                <Sparkles size={12} />
                                [{topGreeting.tone}] 打招呼文案
                            </div>
                            <p className="mt-1 text-foreground/90">{topGreeting.message_text}</p>
                        </div>
                    )}

                    {j.greetings.length > 1 && (
                        <ul className="text-xs space-y-1 text-muted-foreground">
                            {j.greetings.slice(1).map((g, i) => (
                                <li key={i} className="truncate">[{g.tone}] {g.message_text}</li>
                            ))}
                        </ul>
                    )}

                    {j.risk_flags?.length > 0 && (
                        <div className="flex items-start gap-2 text-xs text-amber-700">
                            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                            <div>
                                {j.risk_flags.map((r, i) => (
                                    <div key={i}>{r}</div>
                                ))}
                            </div>
                        </div>
                    )}
                </CardContent>
            </Card>
        );
    };

    return (
        <div className="flex h-full flex-col">
            {/* Header */}
            <div className="border-b px-4 py-3 flex items-center gap-2">
                <Briefcase size={20} className="text-orange-600" />
                <h2 className="text-lg font-semibold">BOSS 半自动化</h2>
                <span className="text-xs text-muted-foreground ml-2">
                    搜索页抓取 → 匹配度排序 → 生成投递资产
                </span>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-hidden">
                <Tabs defaultValue="capture" className="h-full flex flex-col">
                    <TabsList className="mx-4 mt-3">
                        <TabsTrigger value="capture">批量抓取</TabsTrigger>
                        <TabsTrigger value="history">已采集岗位 ({jobs.length})</TabsTrigger>
                    </TabsList>

                    {/* 批量抓取 Tab */}
                    <TabsContent value="capture" className="flex-1 overflow-y-auto p-4 pt-2 space-y-4">
                        <Card>
                            <CardHeader>
                                <CardTitle className="text-base">输入参数</CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-3">
                                <div className="grid grid-cols-3 gap-2">
                                    <div className="col-span-2">
                                        <label className="text-xs text-muted-foreground mb-1 block">搜索关键词 *</label>
                                        <Input
                                            value={query}
                                            onChange={(e) => setQuery(e.target.value)}
                                            placeholder='如 "Java架构师"'
                                        />
                                    </div>
                                    <div>
                                        <label className="text-xs text-muted-foreground mb-1 block">城市（可选）</label>
                                        <Input
                                            value={city}
                                            onChange={(e) => setCity(e.target.value)}
                                            placeholder="如 广州"
                                        />
                                    </div>
                                </div>
                                <div className="grid grid-cols-3 gap-2">
                                    <div>
                                        <label className="text-xs text-muted-foreground mb-1 block">取前 N 个</label>
                                        <Input
                                            type="number"
                                            min={1}
                                            max={10}
                                            value={topN}
                                            onChange={(e) => setTopN(Number(e.target.value) || 3)}
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="text-xs text-muted-foreground mb-1 block">简历内容 *</label>
                                    <Textarea
                                        rows={5}
                                        value={resumeContent}
                                        onChange={(e) => setResumeContent(e.target.value)}
                                        placeholder="候选人简历，会用作匹配度评分和打招呼文案定制"
                                    />
                                </div>
                                <div className="flex items-center gap-2">
                                    <Button onClick={handleCapture} disabled={loading}>
                                        {loading ? (
                                            <>
                                                <Loader2 className="animate-spin" size={16} />
                                                抓取中（最长等 3 分钟）...
                                            </>
                                        ) : (
                                            <>
                                                <Search size={16} />
                                                一键批量抓取
                                            </>
                                        )}
                                    </Button>
                                    <span className="text-xs text-muted-foreground">
                                        需要 macOS + 已登录 BOSS 的 Chrome
                                    </span>
                                </div>
                            </CardContent>
                        </Card>

                        {results.length > 0 && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium flex items-center gap-2">
                                    <Sparkles size={14} className="text-emerald-600" />
                                    本次抓取结果 ({results.length})
                                </h3>
                                {results.map((j, i) => renderSummary(j, i))}
                            </div>
                        )}
                    </TabsContent>

                    {/* 已采集岗位 Tab */}
                    <TabsContent value="history" className="flex-1 overflow-hidden">
                        <div className="flex items-center justify-between px-4 py-2">
                            <h3 className="text-sm font-medium">已采集岗位列表（库中）</h3>
                            <Button variant="ghost" size="sm" onClick={() => refreshJobs()} disabled={jobsLoading}>
                                {jobsLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                                刷新
                            </Button>
                        </div>
                        <ScrollArea className="h-[calc(100vh-220px)]">
                            <div className="px-4 pb-4 space-y-2">
                                {jobs.length === 0 && !jobsLoading && (
                                    <div className="text-center text-sm text-muted-foreground py-8">
                                        还没有采集过任何岗位，去「批量抓取」试试吧
                                    </div>
                                )}
                                {jobs.map((j) => (
                                    <Card key={j.id} className="mb-2">
                                        <CardContent className="py-3 text-sm">
                                            <div className="flex items-start justify-between gap-2">
                                                <div className="flex-1">
                                                    <div className="font-medium">
                                                        {j.job_title} @ {j.company_name}
                                                    </div>
                                                    <div className="flex flex-wrap gap-2 mt-1 text-xs text-muted-foreground">
                                                        {j.salary_text && <Badge variant="outline">{j.salary_text}</Badge>}
                                                        {j.city && <span><MapPin size={10} className="inline" /> {j.city}</span>}
                                                        {j.status && <Badge variant="outline">{j.status}</Badge>}
                                                        <span>{new Date(j.captured_at).toLocaleString()}</span>
                                                    </div>
                                                </div>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => handleDelete(j.id)}
                                                >
                                                    <Trash2 size={14} className="text-red-500" />
                                                </Button>
                                            </div>
                                        </CardContent>
                                    </Card>
                                ))}
                            </div>
                        </ScrollArea>
                    </TabsContent>
                </Tabs>
            </div>
        </div>
    );
}
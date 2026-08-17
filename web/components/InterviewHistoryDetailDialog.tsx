'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { toast } from 'sonner';
import {
    AlertTriangle,
    BarChart3,
    BriefcaseBusiness,
    CalendarDays,
    Download,
    FileCode2,
    FileText,
    Loader2,
    MessagesSquare,
    RefreshCw,
    ShieldCheck,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { DialogueReview } from '@/components/DialogueReview';
import { getSessionDetail, type SessionDetail } from '@/lib/api/sessions';
import { getSessionInterviewReport, saveSessionReportQuestions, type SessionMarkdownReport } from '@/lib/api/interviewReport';
import { normalizeStructuredInterviewReport } from '@/lib/interviewReportStructured';
import {
    createInterviewReportRun,
    listAgentRuns,
    pollAgentRun,
    type AgentRun,
} from '@/lib/api/agentRuns';
import { downloadArtifact, exportArtifact, type ArtifactFormat } from '@/lib/api/artifacts';
import { getRequestApiConfig } from '@/store/interviewFacade';
import { InterviewHistoryEvaluationPanel } from '@/components/evaluations/InterviewHistoryEvaluationPanel';

type InterviewDialogTab = 'overview' | 'dialogue' | 'report' | 'evaluation';

interface InterviewHistoryDetailDialogProps {
    sessionId: string | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Allows report buttons to land directly on the Markdown preview. */
    initialTab?: InterviewDialogTab;
    onOpenEvaluationCenter?: (datasetId: string) => void;
}

const ACTIVE_RUN_STATUSES = new Set<AgentRun['status']>([
    'queued',
    'retrying',
    'running',
    'cancel_requested',
]);

export const INTERVIEW_CLOSING_MESSAGE = '感谢你的分享，你的规划很有条理。本次面试到此结束，后续我们会尽快联系你。';

/** Formats date into the stable display representation used by this view. */
function formatDate(value?: string | null) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
}

/** Keeps legacy completed sessions consistent with the single approved closing sentence. */
function normalizedDialogue(session: SessionDetail | null) {
    const messages = (session?.messages || [])
        .filter(message => message.role === 'user' || message.role === 'assistant')
        .map(message => ({
            role: message.role as 'user' | 'assistant',
            content: message.content,
            timestamp: message.timestamp,
            audio_url: message.audio_url,
        }));
    if (session?.metadata.status !== 'completed') return messages;
    const closingTimestamp = [...messages].reverse().find(message => message.role === 'assistant')?.timestamp;
    let lastUserIndex = -1;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        if (messages[index]?.role === 'user') {
            lastUserIndex = index;
            break;
        }
    }
    const normalized = lastUserIndex >= 0 ? messages.slice(0, lastUserIndex + 1) : [];
    normalized.push({
        role: 'assistant',
        content: INTERVIEW_CLOSING_MESSAGE,
        timestamp: closingTimestamp || session.updated_at || new Date().toISOString(),
        audio_url: undefined,
    });
    return normalized;
}

/** Renders one interview session as overview, normalized Q&A, and one downloadable Markdown report. */
export function InterviewHistoryDetailDialog({
    sessionId,
    open,
    onOpenChange,
    initialTab = 'overview',
    onOpenEvaluationCenter,
}: InterviewHistoryDetailDialogProps) {
    const [session, setSession] = useState<SessionDetail | null>(null);
    const [report, setReport] = useState<SessionMarkdownReport | null>(null);
    const [reportView, setReportView] = useState<'structured' | 'markdown'>('structured');
    const [selectedQuestionIndices, setSelectedQuestionIndices] = useState<number[]>([]);
    const [savingQuestions, setSavingQuestions] = useState(false);
    const [reportRun, setReportRun] = useState<AgentRun | null>(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [exportingFormat, setExportingFormat] = useState<ArtifactFormat | null>(null);
    const [error, setError] = useState<string | null>(null);
    const pollAbortRef = useRef<AbortController | null>(null);

    /** Reloads the persisted Markdown after a report task completes. */
    const loadReport = useCallback(async () => {
        if (!sessionId) return;
        setReport(await getSessionInterviewReport(sessionId));
    }, [sessionId]);

    /** Follows one recoverable report run and refreshes the Markdown at its terminal state. */
    const monitorRun = useCallback(async (runId: string, signal: AbortSignal) => {
        try {
            const completed = await pollAgentRun(runId, setReportRun, signal);
            setReportRun(completed);
            if (completed.status === 'succeeded') {
                await loadReport();
                setError(null);
            } else {
                setError(completed.error_message || '面试报告任务执行失败');
            }
        } catch (cause) {
            if (cause instanceof Error && cause.name === 'AbortError') return;
            setError(cause instanceof Error ? cause.message : '读取报告任务状态失败');
        }
    }, [loadReport]);

    useEffect(() => {
        if (!open || !sessionId) return;
        let cancelled = false;
        pollAbortRef.current?.abort();
        const controller = new AbortController();
        pollAbortRef.current = controller;
        const timer = window.setTimeout(() => {
            setLoading(true);
            setError(null);
            void Promise.all([
            getSessionDetail(sessionId),
            getSessionInterviewReport(sessionId),
            listAgentRuns({ taskType: 'interview_report', sessionId, limit: 1 })
                .catch(() => ({ runs: [], total: 0, limit: 1, offset: 0 })),
        ]).then(([sessionResult, reportResult, runsResponse]) => {
            if (cancelled) return;
            if (!sessionResult) {
                setError('无法读取该场面试记录，请稍后重试');
                return;
            }
            const latestRun = runsResponse.runs[0] || null;
            setSession(sessionResult);
            setReport(reportResult);
            setReportRun(latestRun);
            if (latestRun && ACTIVE_RUN_STATUSES.has(latestRun.status)) {
                setSubmitting(true);
                void monitorRun(latestRun.run_id, controller.signal).finally(() => {
                    if (!controller.signal.aborted) setSubmitting(false);
                });
            }
        }).catch(cause => {
            if (!cancelled) setError(cause instanceof Error ? cause.message : '加载面试详情失败');
            }).finally(() => {
                if (!cancelled) setLoading(false);
            });
        }, 0);

        return () => {
            cancelled = true;
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [monitorRun, open, sessionId]);

    /** Starts the single AgentRun that persists both structured report artifacts. */
    const handleGenerateReport = useCallback(async () => {
        if (!sessionId || (reportRun && ACTIVE_RUN_STATUSES.has(reportRun.status))) return;
        const apiConfig = getRequestApiConfig();
        if (!apiConfig) {
            setError('请先在设置中配置 API Key');
            return;
        }
        setSubmitting(true);
        setError(null);
        pollAbortRef.current?.abort();
        const controller = new AbortController();
        pollAbortRef.current = controller;
        try {
            const created = await createInterviewReportRun({ session_id: sessionId, api_config: apiConfig });
            if ('run_id' in created) {
                setReportRun(created);
                await monitorRun(created.run_id, controller.signal);
            } else {
                await loadReport();
            }
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : '生成面试报告失败');
        } finally {
            if (!controller.signal.aborted) setSubmitting(false);
        }
    }, [loadReport, monitorRun, reportRun, sessionId]);

    /** Generates and downloads an owner-scoped private HTML or PDF artifact. */
    const handleDownload = useCallback(async (format: ArtifactFormat) => {
        if (!sessionId || !report?.success) return;
        setExportingFormat(format);
        setError(null);
        try {
            const artifact = await exportArtifact('interview_report', sessionId, format);
            await downloadArtifact(artifact);
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : '下载面试报告失败');
        } finally {
            setExportingFormat(null);
        }
    }, [report?.success, sessionId]);

    const structuredReport = useMemo(() => normalizeStructuredInterviewReport(report), [report]);
    const recommendedQuestions = structuredReport.weaknessReport.recommendedQuestions;
    const handleSaveQuestions = useCallback(async () => {
        if (!sessionId || !selectedQuestionIndices.length) return;
        setSavingQuestions(true);
        try { const result = await saveSessionReportQuestions(sessionId, selectedQuestionIndices); toast.success(`已加入 ${result.saved_count} 道题，跳过 ${result.skipped_count} 道重复题`); }
        catch (cause) { toast.error(cause instanceof Error ? cause.message : '加入题库失败'); }
        finally { setSavingQuestions(false); }
    }, [selectedQuestionIndices, sessionId]);
    const dialogueMessages = useMemo(() => normalizedDialogue(session), [session]);
    const answeredCount = useMemo(
        () => dialogueMessages.filter(message => message.role === 'user').length,
        [dialogueMessages],
    );
    const generating = submitting || Boolean(reportRun && ACTIVE_RUN_STATUSES.has(reportRun.status));

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[92vh] w-[min(96vw,76rem)] max-w-6xl flex-col overflow-hidden p-0">
                <DialogHeader className="border-b border-gray-100 px-6 py-5 pr-12">
                    <DialogTitle className="text-xl">{session?.title || '面试会话'}</DialogTitle>
                    <DialogDescription>查看本场面试概览、完整问答和统一 Markdown 报告。</DialogDescription>
                </DialogHeader>

                {loading ? (
                    <div className="flex flex-1 items-center justify-center gap-2 text-sm text-gray-500">
                        <Loader2 className="h-5 w-5 animate-spin text-orange-500" />
                        正在加载面试会话...
                    </div>
                ) : error && !session ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                        <AlertTriangle className="h-8 w-8 text-amber-500" />
                        <p className="text-sm text-gray-600">{error}</p>
                    </div>
                ) : session ? (
                    <Tabs defaultValue={initialTab} className="min-h-0 flex-1 gap-0">
                        <div className="border-b border-gray-100 px-6 py-3">
                            <TabsList className="grid w-full max-w-2xl grid-cols-4">
                                <TabsTrigger value="overview"><FileText />概览</TabsTrigger>
                                <TabsTrigger value="dialogue"><MessagesSquare />面试问答</TabsTrigger>
                                <TabsTrigger value="report"><BarChart3 />面试报告</TabsTrigger>
                                <TabsTrigger value="evaluation"><ShieldCheck />加入评测集</TabsTrigger>
                            </TabsList>
                        </div>

                        <TabsContent value="overview" className="min-h-0 flex-1 overflow-hidden">
                            <ScrollArea className="h-full">
                                <div className="space-y-6 p-6">
                                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                                        <InfoCard label="状态" value={session.metadata.status === 'completed' ? '已完成' : session.metadata.status === 'active' ? '进行中' : '已归档'} />
                                        <InfoCard label="面试形式" value={session.metadata.mode === 'voice' ? '语音面试' : '文字面试'} />
                                        <InfoCard label="轮次" value={`第 ${session.metadata.round_index || 1} 轮`} />
                                        <InfoCard label="已回答" value={`${answeredCount} 题`} />
                                    </div>
                                    <div className="grid gap-4 lg:grid-cols-2">
                                        <section className="rounded-xl border border-gray-200 bg-white p-5">
                                            <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900">
                                                <CalendarDays className="h-4 w-4 text-orange-500" />会话信息
                                            </h3>
                                            <dl className="space-y-3 text-sm">
                                                <InfoRow label="创建时间" value={formatDate(session.created_at)} />
                                                <InfoRow label="最后更新" value={formatDate(session.updated_at)} />
                                                <InfoRow label="消息数量" value={`${dialogueMessages.length} 条`} />
                                                <InfoRow label="目标题数" value={`${session.metadata.max_questions} 题`} />
                                                <InfoRow label="简历" value={session.metadata.resume_filename || '未记录'} />
                                                <InfoRow label="公司" value={session.metadata.company_info || '未记录'} />
                                            </dl>
                                        </section>
                                        <section className="rounded-xl border border-gray-200 bg-white p-5">
                                            <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900">
                                                <BriefcaseBusiness className="h-4 w-4 text-orange-500" />目标岗位
                                            </h3>
                                            <p className="max-h-64 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-gray-600">
                                                {session.metadata.job_description || '本场面试未保存岗位描述。'}
                                            </p>
                                        </section>
                                    </div>
                                </div>
                            </ScrollArea>
                        </TabsContent>

                        <TabsContent value="dialogue" className="min-h-0 flex-1 overflow-hidden">
                            <ScrollArea className="h-full">
                                <div className="p-6"><DialogueReview messages={dialogueMessages} /></div>
                            </ScrollArea>
                        </TabsContent>

                        <TabsContent value="evaluation" className="min-h-0 flex-1 overflow-hidden">
                            <ScrollArea className="h-full">
                                <InterviewHistoryEvaluationPanel
                                    sessionId={session.session_id}
                                    completed={session.metadata.status === 'completed'}
                                    onOpenEvaluationCenter={onOpenEvaluationCenter}
                                />
                            </ScrollArea>
                        </TabsContent>

                        <TabsContent value="report" className="min-h-0 flex-1 overflow-hidden">
                            <div className="flex h-full min-h-0 flex-col">
                                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-6 py-3">
                                    <div>
                                        <p className="text-sm font-medium text-gray-900">结构化面试复盘</p>
                                        <p className="text-xs text-gray-500">
                                            {report?.generated_at ? `更新时间：${formatDate(report.generated_at)}` : '能力画像与短板地图将合并生成'}
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        <Button variant="outline" size="sm" onClick={() => void handleGenerateReport()} disabled={generating || session.metadata.status !== 'completed'}>
                                            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                            {report?.success ? '重新生成' : '生成报告'}
                                        </Button>
                                        {report?.success && <Button variant="outline" size="sm" onClick={() => setReportView(value => value === 'structured' ? 'markdown' : 'structured')}>{reportView === 'structured' ? '查看 Markdown' : '查看结构化复盘'}</Button>}
                                        {report?.success && selectedQuestionIndices.length > 0 && <Button variant="outline" size="sm" onClick={() => void handleSaveQuestions()} disabled={savingQuestions}>{savingQuestions ? '保存中...' : '加入题库'}</Button>}
                                        <Button variant="outline" size="sm" onClick={() => void handleDownload('html')} disabled={!report?.success || exportingFormat !== null}>
                                            {exportingFormat === 'html' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCode2 className="h-4 w-4" />}下载 HTML
                                        </Button>
                                        <Button variant="outline" size="sm" onClick={() => void handleDownload('pdf')} disabled={!report?.success || exportingFormat !== null}>
                                            {exportingFormat === 'pdf' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}下载 PDF
                                        </Button>
                                    </div>
                                </div>
                                {error && (
                                    <div role="alert" className="mx-6 mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
                                )}
                                <ScrollArea className="min-h-0 flex-1 bg-slate-100/70">
                                    {report?.success && report.markdown ? (
                                        reportView === 'markdown' ? (
                                            <article className="prose prose-slate mx-auto my-6 min-h-[297mm] w-[min(100%,210mm)] max-w-none bg-white px-8 py-10 shadow-sm sm:px-14"><ReactMarkdown>{report.markdown}</ReactMarkdown></article>
                                        ) : (
                                            <div className="mx-auto my-6 w-[min(100%,900px)] space-y-5 px-4">
                                                <ReportSection title="综合结论"><p>{structuredReport.profile.overall_assessment || '暂无综合结论'}</p><p className="mt-2 text-sm text-teal-700">{structuredReport.profile.recommendation}</p></ReportSection>
                                                <ReportSection title="能力画像"><div className="grid gap-3 sm:grid-cols-2">{Object.entries(structuredReport.profile.dimensions).map(([key, value]) => <div key={key} className="rounded-lg bg-slate-50 p-3"><strong>{key}</strong><p className="text-sm">评分：{String(value.score ?? '-')}</p><p className="text-xs text-slate-500">{String(value.evidence ?? value.reason ?? '')}</p></div>)}</div></ReportSection>
                                                <ReportSection title="重点短板">{structuredReport.weaknessReport.weaknessCategories.map((item, index) => <div key={index} className="mb-2 rounded-lg border border-amber-200 bg-amber-50 p-3"><strong>{String(item.category || '未分类')}</strong><p className="text-sm">{String(item.description || '')}</p></div>)}</ReportSection>
                                                <ReportSection title="典型问答">{structuredReport.weaknessReport.questionFailures.map((item, index) => <div key={index} className="mb-3"><strong>{String(item.question || `问题 ${index + 1}`)}</strong><p className="text-sm text-rose-700">{String(item.issue || '')}</p><p className="text-sm text-slate-600">{String(item.better_example || '')}</p></div>)}</ReportSection>
                                                <ReportSection title="逐题证据">{structuredReport.weaknessReport.questionEvidence.map((item, index) => <div key={index} className="mb-2 rounded-lg bg-slate-50 p-3"><strong>{String(item.question_id || `Q${index + 1}`)} · {String(item.question_summary || '')}</strong><p className="text-xs text-slate-500">缺失证据：{Array.isArray(item.missing_evidence) ? item.missing_evidence.join('、') : '-'}</p></div>)}</ReportSection>
                                                <ReportSection title="改进行动"><ol className="list-decimal space-y-2 pl-5">{structuredReport.weaknessReport.improvementActions.map((item, index) => <li key={index}>{String(item.action || '')} <span className="text-xs text-slate-400">{String(item.estimated_effort || '')}</span></li>)}</ol></ReportSection>
                                                <ReportSection title="推荐练习题"><div className="space-y-2">{recommendedQuestions.map((question, index) => <label key={index} className="flex gap-3 rounded-lg border border-slate-200 bg-white p-3"><input type="checkbox" checked={selectedQuestionIndices.includes(index)} onChange={() => setSelectedQuestionIndices(current => current.includes(index) ? current.filter(value => value !== index) : [...current, index])} /><span>{question}</span></label>)}</div></ReportSection>
                                            </div>
                                        )
                                    ) : (
                                        <div className="flex min-h-80 flex-col items-center justify-center p-10 text-center">
                                            <BarChart3 className="h-10 w-10 text-gray-300" />
                                            <h3 className="mt-4 font-medium text-gray-800">本场面试尚无报告</h3>
                                            <p className="mt-1 max-w-md text-sm text-gray-500">{report?.message || '面试完成后可生成统一报告。'}</p>
                                        </div>
                                    )}
                                </ScrollArea>
                            </div>
                        </TabsContent>
                    </Tabs>
                ) : null}
            </DialogContent>
        </Dialog>
    );
}

function ReportSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="mb-3 font-semibold text-slate-900">{title}</h3>{children}</section>; }

/** Renders one compact overview metric card. */
function InfoCard({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-4">
            <div className="text-xs text-gray-400">{label}</div>
            <div className="mt-1 font-semibold text-gray-900">{value}</div>
        </div>
    );
}

/** Renders one key/value row in the overview metadata list. */
function InfoRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex items-start justify-between gap-4">
            <dt className="shrink-0 text-gray-400">{label}</dt>
            <dd className="text-right text-gray-700">{value}</dd>
        </div>
    );
}

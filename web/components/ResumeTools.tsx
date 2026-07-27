"use client";

import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { useInterviewStore } from "@/store/useInterviewStore";
import { ResumeGenerationDialog } from "./ResumeGenerationDialog";
import { ResumePreviewDialog } from "./ResumePreviewDialog";
import { ResumeProcessingView } from "./ResumeProcessingView";
import { ResumeInputPanel } from "./resume-tools/ResumeInputPanel";
import { ResumeSessionPicker } from "./resume-tools/ResumeSessionPicker";
import { ResumeToolEmptyState } from "./resume-tools/ResumeToolEmptyState";
import { ResumeAnalyzeResultPanel, ResumeJDMatchResultPanel, ResumeOptimizeResultPanel } from "./resume-tools/ResumeResultPanels";
import { refreshGeneratedResumes } from "@/store/interviewFacade";
import { API_BASE_URL, getUserId } from "@/lib/api/config";
import {
    getResumeReview, runResumeWorkspace, submitResumeReview, updateGeneratedResume,
    type ApiConfig, type ResumeAnalyzeResult, type ResumeOptimizeMode, type ResumeOptimizeResult,
    type ResumeReviewDecision, type ResumeReviewState, type ResumeWorkspaceResult,
} from "@/lib/api/resume";

interface ResumeToolsProps { apiConfig: ApiConfig | null; resumeContent: string; onResumeChange?: (content: string) => void; }
type ResumeWorkspaceView = Pick<ResumeWorkspaceResult, "success"> & Partial<Omit<ResumeWorkspaceResult, "success">>;

/** Owns the unified resume workflow while keeping history selection and generation review compatibility. */
export function ResumeTools({ apiConfig, resumeContent, onResumeChange }: ResumeToolsProps) {
    const [resume, setResume] = useState(resumeContent), [jd, setJd] = useState("");
    const [sessions, setSessions] = useState<string[]>([]), [includeProfile, setIncludeProfile] = useState(false);
    const [pickerOpen, setPickerOpen] = useState(false);
    const [mode, setMode] = useState<ResumeOptimizeMode>("balanced");
    const [workspace, setWorkspace] = useState<ResumeWorkspaceView | null>(null), [runStage, setRunStage] = useState("queued");
    const [running, setRunning] = useState(false), [uploading, setUploading] = useState(false), [progress, setProgress] = useState("");
    const [resultId, setResultId] = useState<number>(), [review, setReview] = useState<ResumeReviewState | null>(null);
    const [decisions, setDecisions] = useState<Record<string, ResumeReviewDecision>>({}), [reviewLoading, setReviewLoading] = useState(false), [reviewSubmitting, setReviewSubmitting] = useState(false);
    const [generate, setGenerate] = useState(false), [preview, setPreview] = useState<{ id: number; title: string; content: string } | null>(null);
    const fileRef = useRef<HTMLInputElement>(null), optimizeRef = useRef<HTMLDivElement>(null), bottomRef = useRef<HTMLDivElement>(null);
    const { currentResumeResult, fetchCompletedSessions, fetchResumeResults, completedSessions, completedSessionsLoading } = useInterviewStore();

    useEffect(() => { void fetchCompletedSessions(); }, [fetchCompletedSessions]);
    // History is an external store selection; mirror it locally so legacy history remains viewable in the new workspace.
    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (currentResumeResult) {
            setResume(currentResumeResult.resume_content); setJd(currentResumeResult.job_description || ""); setSessions(currentResumeResult.session_ids || []);
            setIncludeProfile(currentResumeResult.include_profile || false); setResultId(currentResumeResult.id);
            if (currentResumeResult.result_type === "analyze") setWorkspace({ success: true, competition_analysis: currentResumeResult.result_data as ResumeAnalyzeResult });
            else setWorkspace({ success: true, content_optimization: currentResumeResult.result_data as ResumeOptimizeResult });
        } else { setWorkspace(null); setResultId(undefined); setJd(""); setSessions([]); setIncludeProfile(false); }
    }, [currentResumeResult]);
    // Keep the host-provided draft synchronized only when no historical record is selected.
    useEffect(() => { if (!currentResumeResult) setResume(resumeContent); }, [resumeContent, currentResumeResult]);
    // Review data is fetched after a saved optimization becomes available.
    useEffect(() => {
        let alive = true;
        if (!workspace?.content_optimization?.requires_user_review || !resultId) { setReview(null); setDecisions({}); return; }
        setReviewLoading(true); void getResumeReview(resultId).then(value => { if (alive) { setReview(value); setDecisions(Object.fromEntries(value.items.filter(item => item.status !== "pending").map(item => [item.item_id, item.status as ResumeReviewDecision]))); } }).catch(error => toast.error(error instanceof Error ? error.message : "读取人工确认项失败")).finally(() => { if (alive) setReviewLoading(false); });
        return () => { alive = false; };
    }, [workspace?.content_optimization?.requires_user_review, resultId]);
    /* eslint-enable react-hooks/set-state-in-effect */

    /** Uploads a supported resume through the existing extraction endpoint without exposing file contents in logs. */
    async function upload(event: React.ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0]; if (!file) return; setUploading(true);
        try { const body = new FormData(); body.append("file", file); const response = await fetch(`${API_BASE_URL}/api/upload/resume`, { method: "POST", headers: { "X-User-ID": getUserId() }, body }); if (!response.ok) throw new Error("文件上传失败"); const data = await response.json() as { text_content: string }; setResume(data.text_content); onResumeChange?.(data.text_content); toast.success(`已从 ${file.name} 提取简历内容`); }
        catch (error) { toast.error(error instanceof Error ? error.message : "文件上传失败"); }
        finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
    }
    /** Runs all resume stages as one resumable task and keeps partial server warnings visible. */
    async function startWorkspace() {
        if (!resume.trim()) return toast.error("请输入或导入简历内容"); if (!jd.trim()) return toast.error("请输入目标职位描述"); if (!apiConfig) return toast.error("请先配置 API Key");
        setRunning(true); setWorkspace(null); setReview(null); setResultId(undefined); setRunStage("queued");
        try { const result = await runResumeWorkspace({ resume_content: resume, job_description: jd, session_ids: sessions, include_overall_profile: includeProfile, mode, api_config: apiConfig, onUpdate: run => { setRunStage(run.stage); setProgress(run.plan.find(step => step.status === "running")?.title || run.title); } }); setWorkspace(result); setReview(result.review); setResultId(result.result_id); if (result.warnings.length) toast.warning("分析完成，但部分节点返回了警告"); else toast.success("完整分析已完成"); await fetchResumeResults(); }
        catch (error) { toast.error(error instanceof Error ? error.message : "完整分析失败，请重试"); }
        finally { setRunning(false); setProgress(""); }
    }
    /** Submits the existing review gate before generation, preserving its optimistic local choices. */
    async function submitReview() {
        if (!resultId || !review) return; const pending = review.items.filter(item => item.status === "pending"); if (pending.some(item => !decisions[item.item_id])) return toast.warning("还有待确认项"); setReviewSubmitting(true);
        try { const next = await submitResumeReview(resultId, review.version, pending.map(item => ({ item_id: item.item_id, decision: decisions[item.item_id]! }))); setReview(next); toast.success("人工确认已保存"); } catch (error) { toast.error(error instanceof Error ? error.message : "提交人工确认失败"); } finally { setReviewSubmitting(false); }
    }
    const picker = <ResumeSessionPicker sessions={completedSessions} selectedSessions={sessions} isOpen={pickerOpen} isLoading={completedSessionsLoading} onToggleOpen={() => setPickerOpen(open => !open)} onToggleSession={id => setSessions(current => current.includes(id) ? current.filter(value => value !== id) : current.length >= 3 ? current : [...current, id])} />;
    const optimize = workspace?.content_optimization;
    return <div className="h-full min-h-0 flex flex-col gap-5">
        <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,.txt,.md" onChange={upload} className="hidden" />
        <div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-600">Resume workspace</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">一次输入，完成一份可投递的判断</h1><p className="mt-1 text-sm text-slate-500">竞争力、JD 匹配和内容优化会在同一条可恢复流程中完成。</p></div><Sparkles className="hidden h-8 w-8 text-amber-400 sm:block" aria-hidden="true" /></div>
        <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[minmax(300px,0.8fr)_minmax(0,1.4fr)]">
            <ResumeInputPanel mode="optimize" resume={resume} jobDescription={jd} isUploading={uploading} isSubmitting={running} submitDisabled={running || !resume.trim() || !jd.trim() || !apiConfig} submitLabel="开始完整分析" submittingLabel="工作区处理中..." optimizeProgress={progress} sessionPicker={picker} includeProfile={includeProfile} optimizeMode={mode} fileInputRef={fileRef} onResumeChange={value => { setResume(value); onResumeChange?.(value); }} onJobDescriptionChange={setJd} onSubmit={startWorkspace} onIncludeProfileChange={setIncludeProfile} onOptimizeModeChange={setMode} />
            <div className="min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/60">{running ? <ResumeProcessingView stage={runStage} message={progress} /> : workspace ? <ScrollArea className="h-full px-4"><div className="space-y-5 pb-8"><div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4"><p className="text-sm font-semibold text-emerald-900">完整分析结果</p><p className="mt-1 text-xs text-emerald-700">先看结论，再查看各模块依据。你可以继续人工确认并生成简历。</p></div>{workspace.competition_analysis && <ResumeAnalyzeResultPanel result={workspace.competition_analysis} />}{workspace.jd_matching && <ResumeJDMatchResultPanel result={workspace.jd_matching} onContinueOptimize={optimize ? () => optimizeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }) : undefined} />}{optimize && <div ref={optimizeRef}><ResumeOptimizeResultPanel result={optimize} review={review} reviewDecisions={decisions} reviewLoading={reviewLoading} reviewSubmitting={reviewSubmitting} onReviewDecision={(id, decision) => setDecisions(current => ({ ...current, [id]: decision }))} onSubmitReview={submitReview} onScrollToGenerate={() => bottomRef.current?.scrollIntoView({ behavior: "smooth" })} onGenerate={() => { if (optimize.requires_user_review && review?.status !== "completed") return toast.warning("请先完成所有改写项的人工确认"); setGenerate(true); }} resultsBottomRef={bottomRef} /></div>}</div></ScrollArea> : <ResumeToolEmptyState type="optimize" />}</div>
        </div>
        {generate && apiConfig && optimize && <ResumeGenerationDialog isOpen={generate} onClose={() => setGenerate(false)} resumeContent={resume} jobDescription={jd} optimizationResult={optimize} optimizationResultId={resultId} apiConfig={apiConfig} onSuccess={(id, title, content) => { setGenerate(false); setPreview({ id, title, content }); void refreshGeneratedResumes(); }} />}
        {preview && <ResumePreviewDialog isOpen={true} onClose={() => setPreview(null)} title={preview.title} content={preview.content} onContentChange={async content => { const saved = await updateGeneratedResume(preview.id, content); if (!saved) throw new Error("保存简历失败，请重试"); setPreview(current => current ? { ...current, content } : current); void refreshGeneratedResumes(); }} />}
    </div>;
}

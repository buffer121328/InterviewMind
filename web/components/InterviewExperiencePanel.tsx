"use client";

import { useState } from "react";
import { CheckSquare, Download, Loader2, PlayCircle, Search } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    collectInterviewExperiences,
    importExperienceQuestions,
    type ExperienceCollectResponse,
} from "@/lib/api/interviewExperience";
import { useInterviewStore } from "@/store/useInterviewStore";

interface InterviewExperiencePanelProps {
    onImported: () => void;
    onStartInterview?: () => void;
}

/** Renders supported interview-experience collection while keeping question-bank writes user-confirmed. */
export function InterviewExperiencePanel({ onImported, onStartInterview }: InterviewExperiencePanelProps) {
    const setExperienceQuestions = useInterviewStore((state) => state.setExperienceQuestions);
    const queuedCount = useInterviewStore((state) => state.experienceQuestions.length);
    const [query, setQuery] = useState("");
    const [result, setResult] = useState<ExperienceCollectResponse | null>(null);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [loading, setLoading] = useState(false);
    const [importing, setImporting] = useState(false);

    /** Applies a completed collection preview and preselects candidates for explicit review. */
    const applyResult = (data: ExperienceCollectResponse) => {
        setResult(data);
        setSelected(new Set(data.questions.map((_, index) => index)));
        toast.success(data.message ?? "采集完成");
    };

    /** Collects supported Nowcoder results through the synchronous preview endpoint. */
    const handleCollect = async () => {
        if (!query.trim()) {
            toast.warning("请输入搜索关键词");
            return;
        }
        setLoading(true);
        try {
            applyResult(await collectInterviewExperiences({
                source: "nowcoder",
                queries: [query.trim()],
                max_pages: 1,
                exported_items: [],
            }));
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "面经采集失败");
        } finally {
            setLoading(false);
        }
    };

    /** Imports only explicitly selected candidates into the current user's question bank. */
    const handleImport = async () => {
        if (!result) return;
        const questions = result.questions.filter((_, index) => selected.has(index));
        if (!questions.length) {
            toast.warning("请至少选择一道题");
            return;
        }
        setImporting(true);
        try {
            const data = await importExperienceQuestions(questions);
            toast.success(data.message ?? "已导入题库");
            onImported();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "导入失败");
        } finally {
            setImporting(false);
        }
    };

    /** Queues selected candidates for the next interview without writing question-bank records. */
    const handleUseInInterview = () => {
        if (!result) return;
        const questions = result.questions.filter((_, index) => selected.has(index));
        if (!questions.length) {
            toast.warning("请至少选择一道题");
            return;
        }
        setExperienceQuestions(questions);
        toast.success(`已将 ${questions.length} 道面经题带入面试配置`);
        onStartInterview?.();
    };

    return (
        <div className="h-full overflow-auto p-4">
            <div className="mx-auto max-w-3xl space-y-4">
                <div className="rounded-2xl border border-stone-200 bg-white p-4">
                    <div className="flex flex-wrap gap-2">
                        <span className="inline-flex items-center rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-600">牛客网</span>
                        <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：字节 Python 后端面经" className="min-w-56 flex-1" />
                        <Button onClick={handleCollect} disabled={loading} className="gap-2 bg-teal-500 hover:bg-teal-600">
                            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                            采集并抽题
                        </Button>
                    </div>
                </div>

                {result && (
                    <div className="rounded-2xl border border-stone-200 bg-white p-4">
                        <div className="mb-3 flex items-center justify-between gap-3">
                            <p className="text-sm text-stone-600">{result.experiences.length} 篇面经 · {result.questions.length} 道候选题</p>
                            <div className="flex flex-wrap gap-2">
                                <Button size="sm" variant="outline" onClick={handleUseInInterview} disabled={selected.size === 0} className="gap-2"><PlayCircle className="h-4 w-4" />用于模拟面试 {selected.size} 题</Button>
                                <Button size="sm" onClick={handleImport} disabled={importing || selected.size === 0} className="gap-2">{importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}导入所选 {selected.size} 题</Button>
                            </div>
                        </div>
                        {queuedCount > 0 && <p className="mb-3 text-xs text-teal-600">当前已有 {queuedCount} 道面经题等待用于下次模拟面试。</p>}
                        {result.warnings?.map((warning) => <p key={warning} className="mb-2 text-xs text-amber-600">{warning}</p>)}
                        <div className="space-y-2">
                            {result.questions.map((question, index) => (
                                <label key={`${question.source_id}-${index}`} className="flex cursor-pointer gap-3 rounded-xl border border-stone-100 p-3 hover:bg-stone-50">
                                    <input type="checkbox" checked={selected.has(index)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(index)) next.delete(index); else next.add(index); return next; })} className="mt-1" />
                                    <div className="min-w-0 flex-1"><p className="text-sm leading-relaxed text-stone-800">{question.question_text}</p><p className="mt-1 text-xs text-stone-400">{question.tags.join(" · ")}</p></div>
                                    <CheckSquare className="h-4 w-4 shrink-0 text-teal-400" />
                                </label>
                            ))}
                            {result.questions.length === 0 && <p className="py-8 text-center text-sm text-stone-400">未抽取到问句，可调整关键词后重试。</p>}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

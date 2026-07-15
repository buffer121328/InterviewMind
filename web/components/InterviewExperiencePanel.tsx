"use client";

import { useState } from "react";
import { CheckSquare, Download, Loader2, PlayCircle, Search } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
    collectInterviewExperiences,
    importExperienceQuestions,
    type ExperienceCollectResponse,
    type ExperienceSource,
} from "@/lib/api/interviewExperience";
import { useInterviewStore } from "@/store/useInterviewStore";

interface InterviewExperiencePanelProps {
    onImported: () => void;
    onStartInterview?: () => void;
}

export function InterviewExperiencePanel({ onImported, onStartInterview }: InterviewExperiencePanelProps) {
    const setExperienceQuestions = useInterviewStore((state) => state.setExperienceQuestions);
    const queuedCount = useInterviewStore((state) => state.experienceQuestions.length);
    const [source, setSource] = useState<ExperienceSource>("nowcoder");
    const [query, setQuery] = useState("");
    const [exportJson, setExportJson] = useState("");
    const [result, setResult] = useState<ExperienceCollectResponse | null>(null);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [loading, setLoading] = useState(false);
    const [importing, setImporting] = useState(false);

    const handleCollect = async () => {
        if (!query.trim() && source === "nowcoder") {
            toast.warning("请输入搜索关键词");
            return;
        }
        let exportedItems: Array<Record<string, unknown>> = [];
        if (source === "xiaohongshu") {
            try {
                const parsed: unknown = JSON.parse(exportJson);
                if (!Array.isArray(parsed)) throw new Error("导出内容必须是 JSON 数组");
                exportedItems = parsed as Array<Record<string, unknown>>;
            } catch (error) {
                toast.error(error instanceof Error ? error.message : "导出 JSON 格式错误");
                return;
            }
        }
        setLoading(true);
        try {
            const data = await collectInterviewExperiences({
                source,
                queries: query.trim() ? [query.trim()] : [],
                max_pages: 1,
                exported_items: exportedItems,
            });
            setResult(data);
            setSelected(new Set(data.questions.map((_, index) => index)));
            toast.success(data.message ?? "采集完成");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "面经采集失败");
        } finally {
            setLoading(false);
        }
    };

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
                        <select
                            value={source}
                            onChange={(event) => {
                                setSource(event.target.value as ExperienceSource);
                                setResult(null);
                            }}
                            className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm"
                        >
                            <option value="nowcoder">牛客网</option>
                            <option value="xiaohongshu">小红书授权导出</option>
                        </select>
                        <Input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="例如：字节 Python 后端面经"
                            className="min-w-56 flex-1"
                        />
                        <Button onClick={handleCollect} disabled={loading} className="gap-2 bg-orange-500 hover:bg-orange-600">
                            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                            采集并抽题
                        </Button>
                    </div>
                    {source === "xiaohongshu" && (
                        <div className="mt-3 space-y-2">
                            <Textarea
                                value={exportJson}
                                onChange={(event) => setExportJson(event.target.value)}
                                placeholder={'粘贴本人授权导出的 JSON 数组，例如 [{"note_id":"1","title":"面经","desc":"1. Redis 为什么快？"}]'}
                                className="min-h-32 font-mono text-xs"
                            />
                            <p className="text-xs text-stone-400">不上传 Cookie，不内置签名绕过；请遵守平台规则并仅处理有权使用的内容。</p>
                        </div>
                    )}
                </div>

                {result && (
                    <div className="rounded-2xl border border-stone-200 bg-white p-4">
                        <div className="mb-3 flex items-center justify-between gap-3">
                            <p className="text-sm text-stone-600">{result.experiences.length} 篇面经 · {result.questions.length} 道候选题</p>
                            <div className="flex flex-wrap gap-2">
                                <Button size="sm" variant="outline" onClick={handleUseInInterview} disabled={selected.size === 0} className="gap-2">
                                    <PlayCircle className="h-4 w-4" />
                                    用于模拟面试 {selected.size} 题
                                </Button>
                                <Button size="sm" onClick={handleImport} disabled={importing || selected.size === 0} className="gap-2">
                                    {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                                    导入所选 {selected.size} 题
                                </Button>
                            </div>
                        </div>
                        {queuedCount > 0 && <p className="mb-3 text-xs text-orange-600">当前已有 {queuedCount} 道面经题等待用于下次模拟面试。</p>}
                        <div className="space-y-2">
                            {result.questions.map((question, index) => (
                                <label key={`${question.source_id}-${index}`} className="flex cursor-pointer gap-3 rounded-xl border border-stone-100 p-3 hover:bg-stone-50">
                                    <input
                                        type="checkbox"
                                        checked={selected.has(index)}
                                        onChange={() => setSelected((current) => {
                                            const next = new Set(current);
                                            if (next.has(index)) next.delete(index); else next.add(index);
                                            return next;
                                        })}
                                        className="mt-1"
                                    />
                                    <div className="min-w-0 flex-1">
                                        <p className="text-sm leading-relaxed text-stone-800">{question.question_text}</p>
                                        <p className="mt-1 text-xs text-stone-400">{question.tags.join(" · ")}</p>
                                    </div>
                                    <CheckSquare className="h-4 w-4 shrink-0 text-orange-400" />
                                </label>
                            ))}
                            {result.questions.length === 0 && <p className="py-8 text-center text-sm text-stone-400">未抽取到问句，可调整关键词或导出内容后重试。</p>}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

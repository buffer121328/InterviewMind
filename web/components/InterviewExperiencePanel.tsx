"use client";

import { useState } from "react";
import { CheckCircle2, Loader2, Search } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    collectInterviewExperiences,
    type ExperienceCollectResponse,
} from "@/lib/api/interviewExperience";
import { experienceImportSummary } from "@/lib/interviewExperiencePresentation";
import { useInterviewStore } from "@/store/useInterviewStore";

interface InterviewExperiencePanelProps {
    onImported: () => void;
}

/** Collects interview experiences, runs model governance, and shows direct-import results. */
export function InterviewExperiencePanel({ onImported }: InterviewExperiencePanelProps) {
    const getApiConfigForRequest = useInterviewStore((state) => state.getApiConfigForRequest);
    const [query, setQuery] = useState("");
    const [result, setResult] = useState<ExperienceCollectResponse | null>(null);
    const [loading, setLoading] = useState(false);

    /** Collects, governs, and persists supported Nowcoder questions in one request. */
    const handleCollect = async () => {
        if (!query.trim()) {
            toast.warning("请输入搜索关键词");
            return;
        }
        const apiConfig = getApiConfigForRequest();
        if (!apiConfig) {
            toast.warning("请先在设置中配置可用的文本模型");
            return;
        }
        setLoading(true);
        try {
            const data = await collectInterviewExperiences({
                source: "nowcoder",
                queries: [query.trim()],
                max_pages: 1,
                exported_items: [],
                api_config: apiConfig,
            });
            setResult(data);
            if (data.imported_count > 0) onImported();
            if (data.success) toast.success(data.message ?? "面经题已加入个人题库");
            else toast.warning(data.message ?? "部分面经题入库失败");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "面经采集失败");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="h-full overflow-auto p-4">
            <div className="mx-auto max-w-3xl space-y-4">
                <div className="rounded-2xl border border-stone-200 bg-white p-4">
                    <div className="flex flex-wrap gap-2">
                        <span className="inline-flex items-center rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-600">牛客网</span>
                        <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：字节 Python 后端面经" className="min-w-56 flex-1" />
                        <Button onClick={() => void handleCollect()} disabled={loading} className="gap-2 bg-teal-500 hover:bg-teal-600">
                            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                            {loading ? "模型筛选并入库中" : "采集、筛选并入库"}
                        </Button>
                    </div>
                    <p className="mt-2 text-xs text-stone-400">采集结果会经过大模型质量筛选并生成回答要点，然后直接进入个人题库。</p>
                </div>

                {result && (
                    <div className="rounded-2xl border border-stone-200 bg-white p-4">
                        <div className="mb-3 space-y-2">
                            <p className="text-sm font-medium text-stone-700">{result.message}</p>
                            <p className="text-xs text-stone-500">
                                {experienceImportSummary(result)}
                            </p>
                        </div>
                        {result.warnings?.map((warning) => <p key={warning} className="mb-2 text-xs text-amber-600">{warning}</p>)}
                        <div className="space-y-2">
                            {result.questions.map((question, index) => (
                                <article key={`${question.source_id}-${index}`} className="flex gap-3 rounded-xl border border-stone-100 p-3">
                                    <div className="min-w-0 flex-1">
                                        <p className="text-sm leading-relaxed text-stone-800">{question.question_text}</p>
                                        <p className="mt-1 text-xs text-stone-400">{question.tags.join(" · ")}</p>
                                    </div>
                                    <CheckCircle2 className="h-4 w-4 shrink-0 text-teal-500" />
                                </article>
                            ))}
                            {result.questions.length === 0 && <p className="py-8 text-center text-sm text-stone-400">本次没有新增题目，可调整关键词后重试。</p>}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

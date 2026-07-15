"use client";

import { useState } from "react";
import { FileUp, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
    importQuestions,
    previewQuestionFile,
    type QuestionFileCandidate,
} from "@/lib/api/questionBank";

export function QuestionFileImportPanel({ onImported }: { onImported: () => void }) {
    const [filename, setFilename] = useState("");
    const [questions, setQuestions] = useState<QuestionFileCandidate[]>([]);
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const [loading, setLoading] = useState(false);

    const handleFile = async (file: File) => {
        setLoading(true);
        try {
            const result = await previewQuestionFile(file);
            setFilename(result.filename);
            setQuestions(result.questions);
            setSelected(new Set(result.questions.map((_, index) => index)));
            toast.success(result.message ?? "文件解析完成");
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "文件解析失败");
        } finally {
            setLoading(false);
        }
    };

    const confirmImport = async () => {
        const chosen = questions.filter((_, index) => selected.has(index));
        if (!chosen.length) return toast.warning("请至少选择一道题");
        setLoading(true);
        try {
            const result = await importQuestions({ questions: chosen, import_source: "upload" });
            if (!result.success) throw new Error(result.message ?? "导入失败");
            toast.success(result.message ?? "导入完成");
            setQuestions([]);
            setSelected(new Set());
            onImported();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "导入失败");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="mx-4 mb-3 rounded-2xl border border-stone-200 bg-white p-4">
            <div className="flex items-center gap-3">
                <FileUp className="h-5 w-5 text-orange-500" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-stone-700">从 PDF / Markdown 导入</p>
                    <p className="text-xs text-stone-400">先解析预览，确认后才写入题库；扫描版 PDF 暂不支持。</p>
                </div>
                <label className="cursor-pointer">
                    <input
                        type="file"
                        accept=".pdf,.md"
                        className="hidden"
                        disabled={loading}
                        onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void handleFile(file);
                            event.target.value = "";
                        }}
                    />
                    <span className="inline-flex h-9 items-center gap-2 rounded-xl bg-orange-500 px-3 text-sm text-white hover:bg-orange-600">
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                        选择文件
                    </span>
                </label>
            </div>

            {questions.length > 0 && (
                <div className="mt-4 space-y-2 border-t border-stone-100 pt-4">
                    <div className="flex items-center justify-between gap-3">
                        <p className="text-xs text-stone-500">{filename} · {questions.length} 道候选题</p>
                        <Button size="sm" disabled={loading || selected.size === 0} onClick={confirmImport}>
                            导入所选 {selected.size} 题
                        </Button>
                    </div>
                    <div className="max-h-72 space-y-2 overflow-auto">
                        {questions.map((question, index) => (
                            <label key={`${question.source_id}-${index}`} className="flex cursor-pointer gap-3 rounded-xl bg-stone-50 p-3">
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
                                <div className="min-w-0">
                                    <p className="text-sm text-stone-800">{question.question_text}</p>
                                    {question.reference_answer && <p className="mt-1 line-clamp-2 text-xs text-stone-500">{question.reference_answer}</p>}
                                </div>
                            </label>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

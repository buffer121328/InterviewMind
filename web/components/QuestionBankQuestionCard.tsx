"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Pencil, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { QuestionBankItem } from "@/lib/api/questionBank";
import {
    questionAnswerPoints,
    questionSourceLabel,
} from "@/lib/questionBankPresentation";
import { cn } from "@/lib/utils";

const difficultyBadge: Record<string, { bg: string; text: string; label: string }> = {
    easy: { bg: "bg-emerald-100", text: "text-emerald-700", label: "简单" },
    medium: { bg: "bg-amber-100", text: "text-amber-700", label: "中等" },
    hard: { bg: "bg-red-100", text: "text-red-700", label: "困难" },
};

const typeBadge: Record<string, { bg: string; text: string; label: string }> = {
    tech: { bg: "bg-blue-100", text: "text-blue-700", label: "技术" },
    intro: { bg: "bg-purple-100", text: "text-purple-700", label: "介绍" },
    behavior: { bg: "bg-teal-100", text: "text-teal-700", label: "行为" },
    system_design: { bg: "bg-indigo-100", text: "text-indigo-700", label: "设计" },
};

/** Displays zero or more answer points with a stable empty-state fallback. */
function AnswerPointList({ points }: { points: string[] }) {
    if (points.length === 0) {
        return <p className="text-sm text-stone-500">暂无</p>;
    }

    return (
        <ul className="space-y-1.5 text-sm text-stone-700">
            {points.map((point, index) => (
                <li key={`${index}-${point}`} className="flex gap-2 leading-relaxed">
                    <span aria-hidden="true" className="text-teal-600">•</span>
                    <span>{point}</span>
                </li>
            ))}
        </ul>
    );
}

/** Renders one editable question with main-answer review points and question-only nested follow-ups. */
export function QuestionBankQuestionCard({
    item,
    onDelete,
    onEdit,
}: {
    item: QuestionBankItem;
    onDelete: (id: number) => void;
    onEdit: (item: QuestionBankItem) => void;
}) {
    const [expanded, setExpanded] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(false);

    const diff = difficultyBadge[item.difficulty] ?? difficultyBadge.medium;
    const tp = typeBadge[item.question_type] ?? typeBadge.tech;
    const sourceLabel = questionSourceLabel(item);
    const answerPoints = questionAnswerPoints(item);

    return (
        <div className="group rounded-2xl border border-stone-200 bg-white p-4 transition-shadow hover:shadow-md">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-sm font-medium leading-relaxed text-stone-800">
                        {item.question_text}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className={cn("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", diff.bg, diff.text)}>
                            {diff.label}
                        </span>
                        <span className={cn("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", tp.bg, tp.text)}>
                            {tp.label}
                        </span>
                        <span className="text-xs text-stone-400">已使用 {item.usage_count} 次</span>
                        <span className="text-xs text-stone-400">来源：{sourceLabel}</span>
                    </div>
                </div>

                <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-stone-400 hover:text-teal-600"
                        aria-label="编辑题目"
                        onClick={() => onEdit(item)}
                    >
                        <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-stone-400 hover:text-red-500"
                        aria-label={confirmDelete ? "确认删除题目" : "删除题目"}
                        onClick={() => {
                            if (confirmDelete) {
                                onDelete(item.id);
                                setConfirmDelete(false);
                            } else {
                                setConfirmDelete(true);
                                window.setTimeout(() => setConfirmDelete(false), 3000);
                            }
                        }}
                    >
                        <Trash2 className="h-4 w-4" />
                    </Button>
                </div>
            </div>

            {confirmDelete && <p className="mt-1 text-xs text-red-500">再点一次确认删除</p>}

            <button
                className="mt-3 flex items-center gap-1 text-xs text-teal-600 transition-colors hover:text-teal-700"
                onClick={() => setExpanded(!expanded)}
                type="button"
            >
                {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                {expanded ? "收起" : "展开题目详情"}
            </button>

            <div
                className={cn(
                    "overflow-hidden transition-all duration-300 ease-in-out",
                    expanded ? "mt-3 max-h-[80rem] opacity-100" : "max-h-0 opacity-0",
                )}
            >
                <div className="rounded-xl bg-teal-50/60 p-3">
                    <p className="mb-2 text-xs font-medium text-teal-700">回答要点</p>
                    <AnswerPointList points={answerPoints} />
                </div>
                {item.followups.length > 0 && (
                    <div className="mt-2 space-y-2">
                        {item.followups.map((followup) => (
                            <article key={followup.id} className="rounded-xl border border-blue-100 bg-blue-50/50 p-3">
                                <p className="text-sm font-medium leading-relaxed text-stone-800">
                                    <span className="text-blue-700">追问：</span>{followup.question_text}
                                </p>
                            </article>
                        ))}
                    </div>
                )}
                {item.tags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {item.tags.map((tag) => (
                            <span key={tag} className="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500">
                                #{tag}
                            </span>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

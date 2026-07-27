"use client";

import { useState, useEffect, useCallback } from "react";
import {
    Loader2, Plus, Search, Trash2, BookOpen,
    ChevronDown, ChevronUp, MessageCircle, ArrowLeft,
    AlertTriangle, Calendar, Filter, Pencil, RefreshCw
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
    listQuestionBank, createQuestionItem, deleteQuestionItem, searchQuestionBank, updateQuestionItem,
    type QuestionBankItem, type QuestionBankCreateRequest
} from "@/lib/api/questionBank";
import { fetchSessionList, getSessionDetail, type SessionListItem, type SessionDetail } from "@/lib/api/sessions";
import { ChatMessage } from "@/components/ChatMessage";
import { InterviewExperiencePanel } from "@/components/InterviewExperiencePanel";
import { QuestionFileImportPanel } from "@/components/QuestionFileImportPanel";

// =====================================================================
// Types
// =====================================================================

interface QuestionBankPageProps {
    onBack?: () => void;
    onStartInterview: () => void;
    embedded?: boolean;
}

type TabKey = "bank" | "experience" | "history";

type DifficultyOption = { label: string; value: string };
type TypeOption = { label: string; value: string };

const DIFFICULTIES: DifficultyOption[] = [
    { label: "全部难度", value: "" },
    { label: "简单", value: "easy" },
    { label: "中等", value: "medium" },
    { label: "困难", value: "hard" },
];

const QUESTION_TYPES: TypeOption[] = [
    { label: "全部类型", value: "" },
    { label: "自我介绍", value: "intro" },
    { label: "技术题", value: "tech" },
    { label: "行为题", value: "behavior" },
    { label: "系统设计", value: "system_design" },
];

// =====================================================================
// Helpers
// =====================================================================

const difficultyBadge: Record<string, { bg: string; text: string; label: string }> = {
    easy:    { bg: "bg-emerald-100",  text: "text-emerald-700",  label: "简单" },
    medium:  { bg: "bg-amber-100",    text: "text-amber-700",    label: "中等" },
    hard:    { bg: "bg-red-100",      text: "text-red-700",      label: "困难" },
};

const typeBadge: Record<string, { bg: string; text: string; label: string }> = {
    tech:           { bg: "bg-blue-100",   text: "text-blue-700",   label: "技术" },
    intro:          { bg: "bg-purple-100",  text: "text-purple-700", label: "介绍" },
    behavior:       { bg: "bg-teal-100", text: "text-teal-700", label: "行为" },
    system_design:  { bg: "bg-indigo-100", text: "text-indigo-700", label: "设计" },
};

/** Formats date into the stable display representation used by this view; invalid or empty values use the local fallback. */
function formatDate(iso: string) {
    try {
        const d = new Date(iso);
        return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
    } catch {
        return iso;
    }
}

// =====================================================================
// Sub‑components
// =====================================================================

/** Question card inside the bank tab */
function QuestionCard({
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

    return (
        <div className="group rounded-2xl border border-stone-200 bg-white p-4 transition-shadow hover:shadow-md">
            {/* Header row */}
            <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-stone-800 leading-relaxed line-clamp-2">
                        {item.question_text}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className={cn("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", diff.bg, diff.text)}>
                            {diff.label}
                        </span>
                        <span className={cn("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", tp.bg, tp.text)}>
                            {tp.label}
                        </span>
                        <span className="text-xs text-stone-400">
                            已使用 {item.usage_count} 次
                        </span>
                    </div>
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
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
                                setTimeout(() => setConfirmDelete(false), 3000);
                            }
                        }}
                    >
                        <Trash2 className="h-4 w-4" />
                    </Button>
                </div>
            </div>

            {/* Confirm delete hint */}
            {confirmDelete && (
                <p className="mt-1 text-xs text-red-500">再点一次确认删除</p>
            )}

            {/* Expand toggle */}
            {(item.reference_answer || item.tags.length > 0 || item.followups.length > 0) && (
                <button
                    className="mt-3 flex items-center gap-1 text-xs text-teal-600 hover:text-teal-700 transition-colors"
                    onClick={() => setExpanded(!expanded)}
                >
                    {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    {expanded ? "收起" : "展开参考答案/追问"}
                </button>
            )}

            {/* Expanded content */}
            <div
                className={cn(
                    "overflow-hidden transition-all duration-300 ease-in-out",
                    expanded ? "max-h-96 opacity-100 mt-3" : "max-h-0 opacity-0"
                )}
            >
                {item.reference_answer && (
                    <div className="rounded-xl bg-teal-50/60 p-3 text-sm text-stone-700 leading-relaxed whitespace-pre-wrap">
                        {item.reference_answer}
                    </div>
                )}
                {item.followups.length > 0 && (
                    <div className="mt-2 rounded-xl border border-blue-100 bg-blue-50/50 p-3">
                        <p className="mb-2 text-xs font-medium text-blue-700">历史追问沉淀</p>
                        <ul className="space-y-1.5 text-sm text-stone-700">
                            {item.followups.map((followup) => (
                                <li key={followup.id} className="leading-relaxed">• {followup.question_text}</li>
                            ))}
                        </ul>
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

/** Session card inside the history tab */
function SessionCard({ session }: { session: SessionListItem }) {
    const [expanded, setExpanded] = useState(false);
    const [detail, setDetail] = useState<SessionDetail | null>(null);
    const [loading, setLoading] = useState(false);

    /** Encapsulates toggle; returns typed data or state and keeps side effects within the owning module boundary. */
    const toggle = async () => {
        if (!expanded && !detail) {
            setLoading(true);
            const d = await getSessionDetail(session.session_id);
            setDetail(d);
            setLoading(false);
        }
        setExpanded(!expanded);
    };

    return (
        <div className="rounded-2xl border border-stone-200 bg-white overflow-hidden transition-shadow hover:shadow-md">
            {/* Header */}
            <button className="w-full p-4 text-left" onClick={toggle}>
                <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-stone-800 line-clamp-1">{session.title}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-stone-400">
                            <span className="flex items-center gap-1">
                                <Calendar className="h-3.5 w-3.5" />
                                {formatDate(session.created_at)}
                            </span>
                            <span className="flex items-center gap-1">
                                <MessageCircle className="h-3.5 w-3.5" />
                                {session.message_count} 条消息
                            </span>
                            <span className={cn(
                                "rounded-full px-2 py-0.5 text-xs font-medium",
                                session.status === "completed"
                                    ? "bg-emerald-100 text-emerald-700"
                                    : session.status === "active"
                                        ? "bg-teal-100 text-teal-700"
                                        : "bg-stone-100 text-stone-500"
                            )}>
                                {session.status === "completed" ? "已完成" : session.status === "active" ? "进行中" : "已归档"}
                            </span>
                        </div>
                    </div>
                    {expanded ? <ChevronUp className="h-4 w-4 text-stone-400 shrink-0" /> : <ChevronDown className="h-4 w-4 text-stone-400 shrink-0" />}
                </div>
            </button>

            {/* Expanded conversation */}
            <div
                className={cn(
                    "overflow-hidden transition-all duration-300 ease-in-out",
                    expanded ? "max-h-[600px] opacity-100" : "max-h-0 opacity-0"
                )}
            >
                <div className="border-t border-stone-100 bg-stone-50/50">
                    {loading ? (
                        <div className="flex items-center justify-center py-8">
                            <Loader2 className="h-5 w-5 animate-spin text-teal-500" />
                            <span className="ml-2 text-sm text-stone-400">加载中…</span>
                        </div>
                    ) : detail && detail.messages.length > 0 ? (
                        <ScrollArea className="max-h-[500px]">
                            <div className="p-4 space-y-3">
                                {detail.messages.map((msg, idx) => (
                                    <ChatMessage
                                        key={idx}
                                        role={msg.role}
                                        content={msg.content}
                                        timestamp={msg.timestamp}
                                    />
                                ))}
                            </div>
                        </ScrollArea>
                    ) : (
                        <p className="py-8 text-center text-sm text-stone-400">暂无对话记录</p>
                    )}
                </div>
            </div>
        </div>
    );
}

// =====================================================================
// Main Component
// =====================================================================

/** Renders the question bank page UI and coordinates its typed props, local state, and approved backend interactions. */
export default function QuestionBankPage({ onBack, onStartInterview, embedded = false }: QuestionBankPageProps) {
    // ---- state ----
    const [tab, setTab] = useState<TabKey>("bank");
    const [questions, setQuestions] = useState<QuestionBankItem[]>([]);
    const [sessions, setSessions] = useState<SessionListItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);

    // filters
    const [searchQ, setSearchQ] = useState("");
    const [filterType, setFilterType] = useState("");
    const [filterDifficulty, setFilterDifficulty] = useState("");

    // history search
    const [historySearch, setHistorySearch] = useState("");

    // add‑form toggle
    const [showForm, setShowForm] = useState(false);
    const [editingItemId, setEditingItemId] = useState<number | null>(null);
    const [form, setForm] = useState<QuestionBankCreateRequest>({
        question_text: "",
        reference_answer: "",
        difficulty: "medium",
        question_type: "tech",
    });
    const [submitting, setSubmitting] = useState(false);

    // ---- data fetching ----

    const loadQuestions = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            let res;
            if (searchQ.trim()) {
                res = await searchQuestionBank(searchQ.trim(), 200);
            } else {
                res = await listQuestionBank({
                    question_type: filterType || undefined,
                    difficulty: filterDifficulty || undefined,
                    limit: 200,
                });
            }
            if (!res.success) {
                setQuestions([]);
                setLoadError("暂时无法连接题库服务。请确认 FastAPI 后端已启动后重试。");
                return;
            }
            setQuestions(res.items ?? []);
        } catch {
            setLoadError("暂时无法连接题库服务。请确认 FastAPI 后端已启动后重试。");
            toast.error("加载题库失败");
        } finally {
            setLoading(false);
        }
    }, [searchQ, filterType, filterDifficulty]);

    const loadSessions = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const list = await fetchSessionList("completed", undefined, 100);
            setSessions(list);
        } catch {
            setLoadError("暂时无法连接面试历史服务。请确认 FastAPI 后端已启动后重试。");
            toast.error("加载历史失败");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void Promise.resolve().then(() => {
            if (tab === "bank") {
                return loadQuestions();
            }
            if (tab === "history") {
                return loadSessions();
            }
            return undefined;
        });
    }, [tab, loadQuestions, loadSessions]);

    // ---- handlers ----

    /** Handles delete; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleDelete = async (id: number) => {
        const res = await deleteQuestionItem(id);
        if (res.success) {
            toast.success("已删除");
            setQuestions((prev) => prev.filter((q) => q.id !== id));
        } else {
            toast.error(res.message ?? "删除失败");
        }
    };

    /** Encapsulates reset form; returns typed data or state and keeps side effects within the owning module boundary. */
    const resetForm = () => {
        setForm({ question_text: "", reference_answer: "", difficulty: "medium", question_type: "tech" });
        setEditingItemId(null);
    };

    /** Encapsulates open create form; returns typed data or state and keeps side effects within the owning module boundary. */
    const openCreateForm = () => {
        resetForm();
        setShowForm(true);
    };

    /** Encapsulates open edit form; returns typed data or state and keeps side effects within the owning module boundary. */
    const openEditForm = (item: QuestionBankItem) => {
        setEditingItemId(item.id);
        setForm({
            question_text: item.question_text,
            reference_answer: item.reference_answer ?? "",
            tags: item.tags,
            difficulty: item.difficulty,
            target_skill: item.target_skill,
            question_type: item.question_type,
            source_type: item.source_type,
        });
        setShowForm(true);
    };

    /** Handles submit; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSubmit = async () => {
        if (!form.question_text.trim()) {
            toast.warning("请输入题目内容");
            return;
        }
        setSubmitting(true);
        try {
            const res = editingItemId === null
                ? await createQuestionItem(form)
                : await updateQuestionItem(editingItemId, form);
            if (res.success) {
                toast.success(editingItemId === null ? "添加成功" : "更新成功");
                setShowForm(false);
                resetForm();
                await loadQuestions();
            } else {
                toast.error(res.message ?? (editingItemId === null ? "添加失败" : "更新失败"));
            }
        } catch {
            toast.error("网络错误");
        } finally {
            setSubmitting(false);
        }
    };

    // ---- filtering for history ----
    const filteredSessions = historySearch.trim()
        ? sessions.filter((s) => s.title.toLowerCase().includes(historySearch.trim().toLowerCase()))
        : sessions;

    // ---- render ----

    return (
        <div className="flex h-full flex-col bg-[#f7faf9]">
            {/* =================== Header =================== */}
            {!embedded && (
                <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-stone-200 bg-white/80 backdrop-blur px-4 py-3">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 rounded-full"
                        onClick={onBack}
                        aria-label="返回"
                    >
                        <ArrowLeft className="h-5 w-5 text-stone-600" />
                    </Button>
                    <BookOpen className="h-5 w-5 text-teal-700" />
                    <h1 className="text-lg font-semibold text-stone-800">题库与面经</h1>
                </header>
            )}

            {/* =================== Tabs =================== */}
            <div className="flex items-center gap-1 border-b border-stone-200 bg-white px-4">
                {([["bank", "我的题库"], ["experience", "面经采集"], ["history", "面试历史"]] as const).map(([key, label]) => (
                    <button
                        key={key}
                        className={cn(
                            "relative px-4 py-2.5 text-sm font-medium transition-colors",
                            tab === key ? "text-teal-600" : "text-stone-400 hover:text-stone-600"
                        )}
                        onClick={() => setTab(key)}
                    >
                        {label}
                        {tab === key && (
                            <span className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-teal-500" />
                        )}
                    </button>
                ))}
            </div>

            {/* =================== Content =================== */}
            <div className="flex-1 overflow-hidden">
                {/* ---------- Question Bank Tab ---------- */}
                {tab === "bank" && (
                    <div className="flex flex-col h-full">
                        {/* Search + Filters bar */}
                        <div className="shrink-0 space-y-3 px-4 pt-4 pb-2">
                            {/* Search */}
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
                                <Input
                                    value={searchQ}
                                    onChange={(e) => setSearchQ(e.target.value)}
                                    placeholder="搜索题目…"
                                    className="pl-9 rounded-xl border-stone-200 bg-white focus-visible:ring-teal-500"
                                />
                            </div>

                            {/* Filters row */}
                            <div className="flex items-center gap-2 flex-wrap">
                                <Filter className="h-4 w-4 text-stone-400" />
                                <select
                                    value={filterDifficulty}
                                    onChange={(e) => setFilterDifficulty(e.target.value)}
                                    aria-label="按难度筛选"
                                    className="rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                >
                                    {DIFFICULTIES.map((d) => (
                                        <option key={d.value} value={d.value}>{d.label}</option>
                                    ))}
                                </select>
                                <select
                                    value={filterType}
                                    onChange={(e) => setFilterType(e.target.value)}
                                    aria-label="按题型筛选"
                                    className="rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                >
                                    {QUESTION_TYPES.map((t) => (
                                        <option key={t.value} value={t.value}>{t.label}</option>
                                    ))}
                                </select>

                                <div className="flex-1" />

                                <Button
                                    size="sm"
                                    className="rounded-xl bg-teal-500 hover:bg-teal-600 text-white gap-1"
                                    onClick={openCreateForm}
                                >
                                    <Plus className="h-4 w-4" />
                                    添加题目
                                </Button>
                            </div>
                        </div>

                        <QuestionFileImportPanel onImported={() => void loadQuestions()} />

                        {/* Add‑question form */}
                        {showForm && (
                            <div className="mx-4 mb-3 animate-in space-y-3 rounded-2xl border border-teal-200 bg-teal-50/50 p-4 fade-in slide-in-from-top-2">
                                <div className="text-xs font-semibold text-teal-900">
                                    {editingItemId === null ? "添加题目" : "编辑题目"}
                                </div>
                                <Textarea
                                    placeholder="题目内容 *"
                                    value={form.question_text}
                                    onChange={(e) => setForm({ ...form, question_text: e.target.value })}
                                    className="min-h-[72px] rounded-xl border-teal-200 bg-white focus-visible:ring-teal-500"
                                />
                                <Textarea
                                    placeholder="参考答案（可选）"
                                    value={form.reference_answer ?? ""}
                                    onChange={(e) => setForm({ ...form, reference_answer: e.target.value })}
                                    className="min-h-[72px] rounded-xl border-teal-200 bg-white focus-visible:ring-teal-500"
                                />
                                <div className="flex items-center gap-3 flex-wrap">
                                    <select
                                        value={form.difficulty}
                                        onChange={(e) => setForm({ ...form, difficulty: e.target.value })}
                                        aria-label="题目难度"
                                        className="rounded-lg border border-teal-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                    >
                                        {DIFFICULTIES.filter((d) => d.value).map((d) => (
                                            <option key={d.value} value={d.value}>{d.label}</option>
                                        ))}
                                    </select>
                                    <select
                                        value={form.question_type}
                                        onChange={(e) => setForm({ ...form, question_type: e.target.value })}
                                        aria-label="题目类型"
                                        className="rounded-lg border border-teal-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                    >
                                        {QUESTION_TYPES.filter((t) => t.value).map((t) => (
                                            <option key={t.value} value={t.value}>{t.label}</option>
                                        ))}
                                    </select>
                                    <div className="flex-1" />
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="rounded-xl text-stone-500"
                                        onClick={() => {
                                            setShowForm(false);
                                            resetForm();
                                        }}
                                    >
                                        取消
                                    </Button>
                                    <Button
                                        size="sm"
                                        className="rounded-xl bg-teal-500 hover:bg-teal-600 text-white gap-1"
                                        onClick={handleSubmit}
                                        disabled={submitting}
                                    >
                                        {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                                        {editingItemId === null ? "保存" : "保存修改"}
                                    </Button>
                                </div>
                            </div>
                        )}

                        {/* Question list */}
                        <ScrollArea className="flex-1 px-4 pb-4">
                            {loading ? (
                                <div className="flex items-center justify-center py-20">
                                    <Loader2 className="h-6 w-6 animate-spin text-teal-500" />
                                </div>
                            ) : loadError ? (
                                <div className="mx-auto mt-14 flex max-w-md flex-col items-center rounded-2xl border border-amber-200 bg-amber-50 px-6 py-8 text-center">
                                    <AlertTriangle className="h-8 w-8 text-amber-600" />
                                    <p className="mt-3 text-sm font-medium text-amber-950">题库服务暂不可用</p>
                                    <p className="mt-2 text-xs leading-5 text-amber-800">{loadError}</p>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="mt-4 gap-2 border-amber-300 bg-white"
                                        onClick={() => void loadQuestions()}
                                    >
                                        <RefreshCw className="h-3.5 w-3.5" />
                                        重新连接
                                    </Button>
                                </div>
                            ) : questions.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-20 text-stone-400">
                                    <BookOpen className="h-12 w-12 mb-3 opacity-30" />
                                    <p className="text-sm">题库为空</p>
                                    <p className="text-xs mt-1">点击「添加题目」开始创建吧</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {questions.map((q) => (
                                        <QuestionCard key={q.id} item={q} onDelete={handleDelete} onEdit={openEditForm} />
                                    ))}
                                </div>
                            )}
                        </ScrollArea>
                    </div>
                )}

                {tab === "experience" && (
                    <InterviewExperiencePanel
                        onImported={() => void loadQuestions()}
                        onStartInterview={onStartInterview}
                    />
                )}

                {/* ---------- Interview History Tab ---------- */}
                {tab === "history" && (
                    <div className="flex flex-col h-full">
                        {/* History search */}
                        <div className="shrink-0 px-4 pt-4 pb-2">
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
                                <Input
                                    value={historySearch}
                                    onChange={(e) => setHistorySearch(e.target.value)}
                                    placeholder="搜索面试标题…"
                                    className="pl-9 rounded-xl border-stone-200 bg-white focus-visible:ring-teal-500"
                                />
                            </div>
                        </div>

                        {/* Session list */}
                        <ScrollArea className="flex-1 px-4 pb-4">
                            {loading ? (
                                <div className="flex items-center justify-center py-20">
                                    <Loader2 className="h-6 w-6 animate-spin text-teal-500" />
                                </div>
                            ) : loadError ? (
                                <div className="mx-auto mt-14 flex max-w-md flex-col items-center rounded-2xl border border-amber-200 bg-amber-50 px-6 py-8 text-center">
                                    <AlertTriangle className="h-8 w-8 text-amber-600" />
                                    <p className="mt-3 text-sm font-medium text-amber-950">历史服务暂不可用</p>
                                    <p className="mt-2 text-xs leading-5 text-amber-800">{loadError}</p>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="mt-4 gap-2 border-amber-300 bg-white"
                                        onClick={() => void loadSessions()}
                                    >
                                        <RefreshCw className="h-3.5 w-3.5" />
                                        重新连接
                                    </Button>
                                </div>
                            ) : filteredSessions.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-20 text-stone-400">
                                    <MessageCircle className="h-12 w-12 mb-3 opacity-30" />
                                    <p className="text-sm">暂无面试记录</p>
                                    <p className="text-xs mt-1">完成一场面试后会出现在这里</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {filteredSessions.map((s) => (
                                        <SessionCard key={s.session_id} session={s} />
                                    ))}
                                </div>
                            )}
                        </ScrollArea>
                    </div>
                )}
            </div>
        </div>
    );
}

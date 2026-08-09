"use client";

// 已知超限：职责单一（题库管理单页），暂不拆分。

import { useState, useEffect, useCallback } from "react";
import {
    Loader2, Plus, Search, BookOpen, MessageCircle, ArrowLeft,
    AlertTriangle, ArrowRight, Calendar, Filter, RefreshCw
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
import { defaultQuestionBankForm, toQuestionBankForm } from "@/lib/questionBankPriority";
import { fetchSessionPage, type SessionListItem } from "@/lib/api/sessions";
import { InterviewExperiencePanel } from "@/components/InterviewExperiencePanel";
import { QuestionFileImportPanel } from "@/components/QuestionFileImportPanel";
import { QuestionBankQuestionCard } from "@/components/QuestionBankQuestionCard";
import { PaginationControls } from "@/components/PaginationControls";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

// =====================================================================
// Types
// =====================================================================

interface QuestionBankPageProps {
    onBack?: () => void;
    onOpenSession: (sessionId: string) => void;
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

/** Session history is a direct navigation affordance instead of a nested conversation disclosure. */
function SessionCard({ session, onOpen }: { session: SessionListItem; onOpen: (sessionId: string) => void }) {
    return (
        <div className="rounded-2xl border border-stone-200 bg-white overflow-hidden transition-shadow hover:shadow-md">
            <button className="w-full p-4 text-left" onClick={() => onOpen(session.session_id)}>
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
                    <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-teal-600">
                        进入会话
                        <ArrowRight className="h-4 w-4" />
                    </span>
                </div>
            </button>
        </div>
    );
}

// =====================================================================
// Main Component
// =====================================================================

/** Renders the question bank page UI and coordinates its typed props, local state, and approved backend interactions. */
export default function QuestionBankPage({ onBack, onOpenSession, embedded = false }: QuestionBankPageProps) {
    // ---- state ----
    const [tab, setTab] = useState<TabKey>("bank");
    const [questions, setQuestions] = useState<QuestionBankItem[]>([]);
    const [questionTotal, setQuestionTotal] = useState(0);
    const [questionPage, setQuestionPage] = useState(1);
    const [sessions, setSessions] = useState<SessionListItem[]>([]);
    const [sessionTotal, setSessionTotal] = useState(0);
    const [sessionPage, setSessionPage] = useState(1);
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
    const [form, setForm] = useState<QuestionBankCreateRequest>(defaultQuestionBankForm);
    const [submitting, setSubmitting] = useState(false);

    // ---- data fetching ----

    const loadQuestions = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            let res;
            if (searchQ.trim()) {
                res = await searchQuestionBank(
                    searchQ.trim(),
                    DEFAULT_PAGE_SIZE,
                    (questionPage - 1) * DEFAULT_PAGE_SIZE,
                );
            } else {
                res = await listQuestionBank({
                    question_type: filterType || undefined,
                    difficulty: filterDifficulty || undefined,
                    limit: DEFAULT_PAGE_SIZE,
                    offset: (questionPage - 1) * DEFAULT_PAGE_SIZE,
                });
            }
            if (!res.success) {
                setQuestions([]);
                setLoadError("暂时无法连接题库服务。请确认 FastAPI 后端已启动后重试。");
                return;
            }
            setQuestions(res.items ?? []);
            setQuestionTotal(res.total);
        } catch {
            setLoadError("暂时无法连接题库服务。请确认 FastAPI 后端已启动后重试。");
            toast.error("加载题库失败");
        } finally {
            setLoading(false);
        }
    }, [filterDifficulty, filterType, questionPage, searchQ]);

    const loadSessions = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const searchingHistory = Boolean(historySearch.trim());
            const response = await fetchSessionPage(
                "completed",
                undefined,
                searchingHistory ? 200 : DEFAULT_PAGE_SIZE,
                searchingHistory ? 0 : (sessionPage - 1) * DEFAULT_PAGE_SIZE,
            );
            setSessions(response.sessions);
            setSessionTotal(response.total);
        } catch {
            setLoadError("暂时无法连接面试历史服务。请确认 FastAPI 后端已启动后重试。");
            toast.error("加载历史失败");
        } finally {
            setLoading(false);
        }
    }, [historySearch, sessionPage]);

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
            if (questions.length === 1 && questionPage > 1) {
                setQuestionPage((current) => current - 1);
            } else {
                await loadQuestions();
            }
        } else {
            toast.error(res.message ?? "删除失败");
        }
    };

    /** Encapsulates reset form; returns typed data or state and keeps side effects within the owning module boundary. */
    const resetForm = () => {
        setForm(defaultQuestionBankForm());
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
        setForm(toQuestionBankForm(item));
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
    const displayedSessions = historySearch.trim()
        ? filteredSessions.slice((sessionPage - 1) * DEFAULT_PAGE_SIZE, sessionPage * DEFAULT_PAGE_SIZE)
        : filteredSessions;

    // ---- render ----

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#f7faf9]">
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
            <div className="flex shrink-0 items-center gap-1 border-b border-stone-200 bg-white px-4">
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
            <div className="min-h-0 flex-1 overflow-hidden">
                {/* ---------- Question Bank Tab ---------- */}
                {tab === "bank" && (
                    <div className="flex h-full min-h-0 flex-col overflow-hidden">
                        {/* Search + Filters bar */}
                        <div className="shrink-0 space-y-3 px-4 pt-4 pb-2">
                            {/* Search */}
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
                                <Input
                                    value={searchQ}
                                    onChange={(e) => {
                                        setSearchQ(e.target.value);
                                        setQuestionPage(1);
                                    }}
                                    placeholder="搜索题目…"
                                    className="pl-9 rounded-xl border-stone-200 bg-white focus-visible:ring-teal-500"
                                />
                            </div>

                            {/* Filters row */}
                            <div className="flex items-center gap-2 flex-wrap">
                                <Filter className="h-4 w-4 text-stone-400" />
                                <select
                                    value={filterDifficulty}
                                    onChange={(e) => {
                                        setFilterDifficulty(e.target.value);
                                        setQuestionPage(1);
                                    }}
                                    aria-label="按难度筛选"
                                    className="rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                >
                                    {DIFFICULTIES.map((d) => (
                                        <option key={d.value} value={d.value}>{d.label}</option>
                                    ))}
                                </select>
                                <select
                                    value={filterType}
                                    onChange={(e) => {
                                        setFilterType(e.target.value);
                                        setQuestionPage(1);
                                    }}
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

                        <div className="shrink-0">
                            <QuestionFileImportPanel onImported={() => void loadQuestions()} />
                        </div>

                        {/* Add‑question form */}
                        {showForm && (
                            <div className="mx-4 mb-3 shrink-0 animate-in space-y-3 rounded-2xl border border-teal-200 bg-teal-50/50 p-4 fade-in slide-in-from-top-2">
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
                                    placeholder="回答要点（可选，建议一行一个要点）"
                                    value={form.reference_answer ?? ""}
                                    onChange={(e) => setForm({ ...form, reference_answer: e.target.value })}
                                    className="min-h-[72px] rounded-xl border-teal-200 bg-white focus-visible:ring-teal-500"
                                />
                                <div className="grid gap-3 sm:grid-cols-2">
                                    <Input
                                        placeholder="考察技能（可选）"
                                        value={form.target_skill ?? ""}
                                        onChange={(e) => setForm({ ...form, target_skill: e.target.value })}
                                        className="rounded-xl border-teal-200 bg-white focus-visible:ring-teal-500"
                                    />
                                    <Input
                                        placeholder="标签（使用逗号分隔）"
                                        value={(form.tags ?? []).join(", ")}
                                        onChange={(e) => setForm({
                                            ...form,
                                            tags: e.target.value
                                                .split(/[,，]/)
                                                .map((tag) => tag.trim())
                                                .filter(Boolean)
                                                .slice(0, 10),
                                        })}
                                        className="rounded-xl border-teal-200 bg-white focus-visible:ring-teal-500"
                                    />
                                </div>
                                <div className="flex items-center gap-3 flex-wrap">
                                    <select
                                        value={form.difficulty}
                                        onChange={(e) => setForm({ ...form, difficulty: e.target.value as NonNullable<QuestionBankCreateRequest["difficulty"]> })}
                                        aria-label="题目难度"
                                        className="rounded-lg border border-teal-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                    >
                                        {DIFFICULTIES.filter((d) => d.value).map((d) => (
                                            <option key={d.value} value={d.value}>{d.label}</option>
                                        ))}
                                    </select>
                                    <select
                                        value={form.question_type}
                                        onChange={(e) => setForm({ ...form, question_type: e.target.value as NonNullable<QuestionBankCreateRequest["question_type"]> })}
                                        aria-label="题目类型"
                                        className="rounded-lg border border-teal-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                    >
                                        {QUESTION_TYPES.filter((t) => t.value).map((t) => (
                                            <option key={t.value} value={t.value}>{t.label}</option>
                                        ))}
                                    </select>
                                    <select
                                        value={form.priority}
                                        onChange={(e) => setForm({ ...form, priority: e.target.value as NonNullable<QuestionBankCreateRequest["priority"]> })}
                                        aria-label="题目优先级"
                                        className="rounded-lg border border-teal-200 bg-white px-2.5 py-1.5 text-xs text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500"
                                    >
                                        <option value="required">必选</option>
                                        <option value="high">高</option>
                                        <option value="low">低</option>
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
                        <ScrollArea aria-label="题目列表" className="min-h-0 flex-1 overflow-hidden px-4 pb-4">
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
                                        <QuestionBankQuestionCard key={q.id} item={q} onDelete={handleDelete} onEdit={openEditForm} />
                                    ))}
                                </div>
                            )}
                        </ScrollArea>
                        <PaginationControls
                            className="shrink-0 border-t border-stone-200 bg-white px-4 py-3"
                            page={questionPage}
                            total={questionTotal}
                            loading={loading}
                            onPageChange={setQuestionPage}
                        />
                    </div>
                )}

                {tab === "experience" && (
                    <InterviewExperiencePanel onImported={() => void loadQuestions()} />
                )}

                {/* ---------- Interview History Tab ---------- */}
                {tab === "history" && (
                    <div className="flex h-full min-h-0 flex-col overflow-hidden">
                        {/* History search */}
                        <div className="shrink-0 px-4 pt-4 pb-2">
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
                                <Input
                                    value={historySearch}
                                    onChange={(e) => {
                                        setHistorySearch(e.target.value);
                                        setSessionPage(1);
                                    }}
                                    placeholder="搜索面试标题…"
                                    className="pl-9 rounded-xl border-stone-200 bg-white focus-visible:ring-teal-500"
                                />
                            </div>
                        </div>

                        {/* Session list */}
                        <ScrollArea aria-label="面试历史列表" className="min-h-0 flex-1 overflow-hidden px-4 pb-4">
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
                                    {displayedSessions.map((s) => (
                                        <SessionCard key={s.session_id} session={s} onOpen={onOpenSession} />
                                    ))}
                                </div>
                            )}
                        </ScrollArea>
                        <PaginationControls
                            className="shrink-0 border-t border-stone-200 bg-white px-4 py-3"
                            page={sessionPage}
                            total={historySearch.trim() ? filteredSessions.length : sessionTotal}
                            loading={loading}
                            onPageChange={setSessionPage}
                        />
                    </div>
                )}
            </div>
        </div>
    );
}

'use client';

import { useCallback, useEffect, useState } from 'react';
import {
    Clock3,
    Database,
    History,
    Loader2,
    Pencil,
    Plus,
    RefreshCw,
    Search,
    ShieldAlert,
    Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
    deleteAllMemories,
    deleteMemory,
    addMemory,
    getAllMemories,
    getMemoryHistory,
    searchMemories,
    updateMemory,
    type MemoryHistoryItem,
    type MemoryItem,
} from '@/lib/api/memory';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { useInterviewStore } from '@/store/useInterviewStore';
import { toast } from 'sonner';

/** Formats date into the stable display representation used by this view; invalid or empty values use the local fallback. */
function formatDate(value?: string) {
    if (!value) return '时间未知';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/** Encapsulates metadata labels; returns typed data or state and keeps side effects within the owning module boundary. */
function metadataLabels(metadata?: Record<string, unknown>) {
    if (!metadata) return [];
    return Object.entries(metadata)
        .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value))
        .slice(0, 4)
        .map(([key, value]) => `${key}: ${String(value)}`);
}

/** Renders the memory center UI and coordinates its typed props, local state, and approved backend interactions. */
export function MemoryCenter() {
    const getApiConfigForRequest = useInterviewStore(state => state.getApiConfigForRequest);
    const [memories, setMemories] = useState<MemoryItem[]>([]);
    const [total, setTotal] = useState(0);
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(true);
    const [actingId, setActingId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [historyMemory, setHistoryMemory] = useState<MemoryItem | null>(null);
    const [history, setHistory] = useState<MemoryHistoryItem[]>([]);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [clearOpen, setClearOpen] = useState(false);
    const [editorOpen, setEditorOpen] = useState(false);
    const [editingMemory, setEditingMemory] = useState<MemoryItem | null>(null);
    const [editorContent, setEditorContent] = useState('');

    /** Resolves the in-memory model settings used by mem0 without logging or persisting credentials. */
    const memoryApiConfig = useCallback(() => {
        const config = getApiConfigForRequest();
        const missingChannels: string[] = [];
        if (!config?.mem0_llm) missingChannels.push('mem0 提取 LLM');
        if (!config?.mem0_embedder && !config?.rag_embedding) missingChannels.push('mem0 Embedding');
        if (missingChannels.length > 0) {
            setError(`尚缺模型分配：${missingChannels.join('、')}。请前往“模型设置 → RAG 与长期记忆”完成分配。`);
            return null;
        }
        return config;
    }, [getApiConfigForRequest]);

    const load = useCallback(async () => {
        const apiConfig = memoryApiConfig();
        if (!apiConfig) {
            setLoading(false);
            return;
        }
        setLoading(true);
        try {
            const response = await getAllMemories(apiConfig, 200);
            setMemories(response.memories || []);
            setTotal(response.total || 0);
            setError(response.message || null);
        } catch (loadError) {
            const message = loadError instanceof Error ? loadError.message : '';
            setError(/failed to fetch/i.test(message) ? '无法连接后端，请确认 FastAPI 与 mem0 服务已启动。' : message || '长期记忆暂时不可用');
        } finally {
            setLoading(false);
        }
    }, [memoryApiConfig]);

    useEffect(() => {
        const timer = window.setTimeout(() => void load(), 0);
        return () => window.clearTimeout(timer);
    }, [load]);

    /** Handles search; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSearch = async () => {
        if (!query.trim()) {
            await load();
            return;
        }
        const apiConfig = memoryApiConfig();
        if (!apiConfig) return;
        setLoading(true);
        try {
            const response = await searchMemories({ q: query.trim(), limit: 20, api_config: apiConfig });
            setMemories(response.memories || []);
            setTotal(response.total || 0);
            setError(response.message || null);
        } catch (searchError) {
            toast.error(searchError instanceof Error ? searchError.message : '搜索长期记忆失败');
        } finally {
            setLoading(false);
        }
    };

    /** Handles delete; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleDelete = async (item: MemoryItem) => {
        if (!window.confirm('确认删除这条长期记忆？后续个性化检索将不再使用它。')) return;
        const apiConfig = memoryApiConfig();
        if (!apiConfig) return;
        setActingId(item.id);
        try {
            const response = await deleteMemory(item.id, apiConfig);
            if (!response.success) throw new Error(response.message);
            setMemories(current => current.filter(memory => memory.id !== item.id));
            setTotal(current => Math.max(0, current - 1));
            if (historyMemory?.id === item.id) setHistoryMemory(null);
            toast.success('长期记忆已删除');
        } catch (deleteError) {
            toast.error(deleteError instanceof Error ? deleteError.message : '删除失败');
        } finally {
            setActingId(null);
        }
    };

    /** Opens the owner-controlled editor for either a new or an existing memory. */
    const openEditor = (item?: MemoryItem) => {
        setEditingMemory(item || null);
        setEditorContent(item?.memory || '');
        setEditorOpen(true);
    };

    /** Persists a user-authored memory and refreshes the list so mem0 metadata stays authoritative. */
    const handleSaveMemory = async () => {
        const content = editorContent.trim();
        if (!content) {
            toast.error('请输入记忆内容');
            return;
        }
        const apiConfig = memoryApiConfig();
        if (!apiConfig) return;
        setActingId(editingMemory?.id || '__new__');
        try {
            const response = editingMemory
                ? await updateMemory(editingMemory.id, content, apiConfig)
                : await addMemory(content, apiConfig);
            if (!response.success) throw new Error(response.message);
            setEditorOpen(false);
            setEditingMemory(null);
            setEditorContent('');
            await load();
            toast.success(editingMemory ? '长期记忆已更新' : '长期记忆已添加');
        } catch (saveError) {
            toast.error(saveError instanceof Error ? saveError.message : '保存记忆失败');
        } finally {
            setActingId(null);
        }
    };

    /** Encapsulates open history; returns typed data or state and keeps side effects within the owning module boundary. */
    const openHistory = async (item: MemoryItem) => {
        const apiConfig = memoryApiConfig();
        if (!apiConfig) return;
        setHistoryMemory(item);
        setHistory([]);
        setHistoryLoading(true);
        try {
            const response = await getMemoryHistory(item.id, apiConfig);
            setHistory(response.history || []);
        } catch (historyError) {
            toast.error(historyError instanceof Error ? historyError.message : '读取记忆历史失败');
        } finally {
            setHistoryLoading(false);
        }
    };

    /** Handles clear all; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleClearAll = async () => {
        const apiConfig = memoryApiConfig();
        if (!apiConfig) return;
        setActingId('__all__');
        try {
            const response = await deleteAllMemories(apiConfig, true);
            if (!response.success) throw new Error(response.message);
            setMemories([]);
            setTotal(0);
            setHistoryMemory(null);
            setClearOpen(false);
            toast.success('全部长期记忆已清空');
        } catch (clearError) {
            toast.error(clearError instanceof Error ? clearError.message : '清空失败');
        } finally {
            setActingId(null);
        }
    };

    return (
        <div className="mx-auto flex h-full w-full max-w-7xl flex-col gap-5 p-5 sm:p-6">
            <section className="surface-panel p-5">
                <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
                    <div>
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                            <Database className="h-4 w-4 text-teal-700" />
                            长期记忆治理
                        </div>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                            面试报告生成成功后，自动沉淀短板、练习目标和优势事实；回答中的稳定偏好也会即时尝试写入。
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm" onClick={() => openEditor()} disabled={actingId !== null}>
                            <Plus />添加记忆
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
                            <RefreshCw className={loading ? 'animate-spin' : ''} />刷新
                        </Button>
                        <Button variant="outline" size="sm" className="text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => setClearOpen(true)} disabled={total === 0}>
                            <Trash2 />清空全部
                        </Button>
                    </div>
                </div>

                <div className="mt-5 flex gap-2">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                        <Input
                            value={query}
                            onChange={event => setQuery(event.target.value)}
                            onKeyDown={event => {
                                if (event.key === 'Enter') void handleSearch();
                            }}
                            className="pl-9"
                            placeholder="按经历、技能、偏好或岗位语义搜索"
                        />
                    </div>
                    <Button className="bg-teal-700 hover:bg-teal-800" onClick={() => void handleSearch()} disabled={loading}>搜索</Button>
                </div>
            </section>

            {error && (
                <div className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                        <div className="font-medium">长期记忆服务未就绪</div>
                        <p className="mt-1 text-xs leading-5 text-amber-800">{error}</p>
                    </div>
                </div>
            )}

            <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
                <section className="min-h-0 overflow-y-auto pr-1">
                    {loading ? (
                        <div className="flex min-h-64 items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">
                            <Loader2 className="mr-2 h-4 w-4 animate-spin text-teal-700" />读取长期记忆...
                        </div>
                    ) : memories.length === 0 ? (
                        <div className="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white text-center">
                            <Database className="h-9 w-9 text-slate-300" />
                            <div className="mt-3 text-sm font-medium text-slate-900">{query.trim() ? '没有匹配的记忆' : '尚未形成长期记忆'}</div>
                            <p className="mt-1 max-w-md text-xs leading-5 text-slate-500">
                                请先分配 mem0 提取 LLM 与 Embedding；完成模拟面试并等待面试报告生成成功后，这里会自动出现记忆。
                            </p>
                        </div>
                    ) : (
                        <div className="grid gap-3 md:grid-cols-2">
                            {memories.map(item => (
                                <article key={item.id} className="surface-panel p-4">
                                    <div className="flex items-start justify-between gap-3">
                                        <p className="text-sm leading-6 text-slate-800">{item.memory}</p>
                                        {typeof item.score === 'number' && (
                                            <span className="shrink-0 rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-medium text-teal-700">
                                                {(item.score * 100).toFixed(0)}%
                                            </span>
                                        )}
                                    </div>
                                    {metadataLabels(item.metadata).length > 0 && (
                                        <div className="mt-3 flex flex-wrap gap-1.5">
                                            {metadataLabels(item.metadata).map(label => (
                                                <span key={label} className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{label}</span>
                                            ))}
                                        </div>
                                    )}
                                    <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                                        <span className="flex items-center gap-1 text-[10px] text-slate-400"><Clock3 className="h-3 w-3" />{formatDate(item.updated_at || item.created_at)}</span>
                                        <div className="flex items-center gap-1">
                                            <Button variant="ghost" size="sm" onClick={() => void openHistory(item)}><History className="h-3.5 w-3.5" />历史</Button>
                                            <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-500 hover:bg-slate-100 hover:text-slate-800" onClick={() => openEditor(item)} disabled={actingId !== null}>
                                                <Pencil className="h-3.5 w-3.5" />
                                            </Button>
                                            <Button variant="ghost" size="icon" className="h-8 w-8 text-red-500 hover:bg-red-50 hover:text-red-700" onClick={() => void handleDelete(item)} disabled={actingId === item.id}>
                                                {actingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                                            </Button>
                                        </div>
                                    </div>
                                </article>
                            ))}
                        </div>
                    )}
                </section>

                <aside className="surface-panel min-h-0 overflow-y-auto p-5">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><History className="h-4 w-4 text-teal-700" />变更历史</div>
                    {!historyMemory ? (
                        <p className="mt-4 text-xs leading-6 text-slate-500">选择任意记忆的“历史”，查看该条内容的新增、更新和删除记录。</p>
                    ) : (
                        <>
                            <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-700">{historyMemory.memory}</div>
                            <div className="mt-4 space-y-3">
                                {historyLoading ? (
                                    <div className="py-8 text-center text-xs text-slate-500"><Loader2 className="mx-auto mb-2 h-4 w-4 animate-spin" />加载中</div>
                                ) : history.length === 0 ? (
                                    <div className="py-8 text-center text-xs text-slate-400">暂无变更记录</div>
                                ) : history.map(event => (
                                    <div key={event.id} className="border-l-2 border-teal-200 pl-3">
                                        <div className="flex items-center justify-between gap-3">
                                            <span className="text-xs font-semibold text-teal-700">{event.event}</span>
                                            <span className="text-[10px] text-slate-400">{formatDate(event.created_at)}</span>
                                        </div>
                                        {event.new_memory && <p className="mt-1 text-xs leading-5 text-slate-600">{event.new_memory}</p>}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </aside>
            </div>

            <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>{editingMemory ? '编辑长期记忆' : '添加长期记忆'}</DialogTitle>
                        <DialogDescription>
                            {editingMemory ? '修改后会记录在该记忆的变更历史中。' : '这段内容会原样保存，不会被 mem0 自动改写或抽取。'}
                        </DialogDescription>
                    </DialogHeader>
                    <Textarea
                        value={editorContent}
                        onChange={event => setEditorContent(event.target.value)}
                        maxLength={2000}
                        placeholder="例如：我希望回答优先使用 Python 和 FastAPI 的真实项目经验。"
                        className="min-h-32"
                    />
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button>
                        <Button onClick={() => void handleSaveMemory()} disabled={actingId !== null}>
                            {actingId === (editingMemory?.id || '__new__') && <Loader2 className="h-4 w-4 animate-spin" />}
                            保存
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <AlertDialog open={clearOpen} onOpenChange={setClearOpen}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>清空全部长期记忆？</AlertDialogTitle>
                        <AlertDialogDescription>这会删除当前用户的全部 mem0 记忆，后续个性化建议将失去这些上下文。此操作不可撤销。</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction className="bg-red-600 hover:bg-red-700" onClick={() => void handleClearAll()} disabled={actingId === '__all__'}>
                            {actingId === '__all__' && <Loader2 className="h-4 w-4 animate-spin" />}确认清空
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}

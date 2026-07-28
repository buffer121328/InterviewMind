'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, BookOpen, Check, ChevronLeft, ChevronRight, Code2, Eye, FilePlus2, FolderOpen, Loader2, Pencil, Rocket, Search, ShieldCheck, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/atom-one-dark.css';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { createPromptVersion, getPrompt, listPrompts, previewPrompt, promotePromptToProduction, PromptManagementError, type PromptBody, type PromptChatMessage, type PromptMetadata, type PromptPreviewResponse, type PromptVersion } from '@/lib/api/prompts';
import { getPromptDisplayName, getPromptFunctionalGroup, getPromptLabelDisplayName } from '@/lib/promptCatalog';

const pageSize = 50;
const badge = 'rounded-full border px-2 py-0.5 text-[11px] font-medium';
const roleNames: Record<PromptChatMessage['role'], string> = {
    system: '系统',
    developer: '开发者',
    user: '用户',
    assistant: '助手',
    tool: '工具',
};

type EditorMode = 'write' | 'preview';

/** Renders a prompt body as safe Markdown without executing HTML or model code. */
function PromptBodyMarkdown({ value }: { value: PromptBody }) {
    if (Array.isArray(value)) {
        return (
            <div className="space-y-3">
                {value.map((message, index) => (
                    <article className="overflow-hidden rounded-xl border border-slate-200 bg-white" key={`${message.role}-${index}`}>
                        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-3 py-2">
                            <span className="text-xs font-semibold text-slate-600">{roleNames[message.role]}</span>
                            <span className="font-mono text-[10px] uppercase tracking-wide text-slate-400">{message.role}</span>
                        </div>
                        <div className="prose prose-sm max-w-none px-4 py-3 text-slate-700 prose-headings:text-slate-900 prose-a:text-teal-700 prose-code:rounded prose-code:bg-slate-100 prose-code:px-1 prose-code:py-0.5 prose-pre:overflow-x-auto prose-pre:bg-slate-950 [&_p]:whitespace-pre-wrap">
                            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{message.content}</ReactMarkdown>
                        </div>
                    </article>
                ))}
            </div>
        );
    }

    return (
        <div className="prose prose-sm max-w-none text-slate-700 prose-headings:text-slate-900 prose-a:text-teal-700 prose-code:rounded prose-code:bg-slate-100 prose-code:px-1 prose-code:py-0.5 prose-pre:overflow-x-auto prose-pre:bg-slate-950 [&_p]:whitespace-pre-wrap">
            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{value}</ReactMarkdown>
        </div>
    );
}

/** Provides a compact write/preview switch so Markdown remains readable before it is saved. */
function MarkdownEditor({ value, type, mode, onChange, onModeChange }: { value: string; type: 'text' | 'chat'; mode: EditorMode; onChange: (value: string) => void; onModeChange: (mode: EditorMode) => void }) {
    const previewBody = parsePromptBodyForPreview(value, type);

    return (
        <div className="mt-2 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-2 py-2">
                <div className="flex gap-1" role="tablist" aria-label="Prompt 内容模式">
                    <button className={cn('rounded-md px-3 py-1.5 text-xs font-medium transition-colors', mode === 'write' ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500 hover:bg-white/70')} onClick={() => onModeChange('write')} role="tab" aria-selected={mode === 'write'} type="button"><Code2 className="mr-1.5 inline h-3.5 w-3.5" />编辑</button>
                    <button className={cn('rounded-md px-3 py-1.5 text-xs font-medium transition-colors', mode === 'preview' ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500 hover:bg-white/70')} onClick={() => onModeChange('preview')} role="tab" aria-selected={mode === 'preview'} type="button"><Eye className="mr-1.5 inline h-3.5 w-3.5" />Markdown 预览</button>
                </div>
                <span className="hidden text-[11px] text-slate-400 sm:inline">支持标题、列表、引用、代码块</span>
            </div>
            {mode === 'write' ? <Textarea className="min-h-56 resize-y rounded-none border-0 font-mono text-sm shadow-none focus-visible:ring-0" value={value} onChange={event => onChange(event.target.value)} placeholder={type === 'text' ? '你是一个面试官…\n\n## 任务\n请分析 {{candidate_name}}' : '[{"role":"system","content":"你是一个…"}]'} /> : previewBody ? <div className="max-h-[32rem] min-h-56 overflow-auto p-4"><PromptBodyMarkdown value={previewBody} /></div> : <div className="min-h-56 p-4 text-sm text-slate-500">{type === 'text' ? '填写内容后即可查看 Markdown 预览。' : 'Chat Prompt 需要先填写有效的 JSON 数组，才能预览。'}</div>}
        </div>
    );
}

/** Parses editor content only for preview; save-time parsing still shows a validation toast. */
function parsePromptBodyForPreview(value: string, promptType: 'text' | 'chat'): PromptBody | null {
    if (promptType === 'text') return value;
    try {
        const parsed: unknown = JSON.parse(value);
        return Array.isArray(parsed) ? parsed as PromptBody : null;
    } catch {
        return null;
    }
}

/** Formats text and chat prompt bodies for the JSON editor and compiled preview fallback. */
function renderBody(value: PromptBody): string {
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

/** Returns labels that can be copied to a new version while excluding the computed production pointer. */
function getCopyableLabels(labels: string[]): string[] {
    return labels.filter(label => label !== 'production' && label !== 'builtin');
}

/** Displays lifecycle labels without exposing the backend's technical prompt key. */
function PromptLabel({ label }: { label: string }) {
    const color = label === 'production' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-600';
    return <span className={cn(badge, color)}>{getPromptLabelDisplayName(label)}</span>;
}

/** Displays the read-only functional group derived from the backend prompt namespace. */
function PromptGroupBadge({ name }: { name: string }) {
    return <span className={cn(badge, 'border-violet-200 bg-violet-50 text-violet-700')}><FolderOpen className="mr-1 inline h-3 w-3" />{getPromptFunctionalGroup(name)}</span>;
}

/** Renders the prompt registry with group filtering, Markdown preview, and immutable version actions. */
export function PromptManagementPage() {
    const [items, setItems] = useState<PromptMetadata[]>([]);
    const [page, setPage] = useState(1);
    const [selected, setSelected] = useState<PromptVersion | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<PromptManagementError | null>(null);
    const [creating, setCreating] = useState(false);
    const [name, setName] = useState('');
    const [type, setType] = useState<'text' | 'chat'>('text');
    const [body, setBody] = useState('');
    const [commit, setCommit] = useState('');
    const [createMode, setCreateMode] = useState<EditorMode>('write');
    const [editing, setEditing] = useState(false);
    const [editBody, setEditBody] = useState('');
    const [editCommit, setEditCommit] = useState('');
    const [editMode, setEditMode] = useState<EditorMode>('write');
    const [preview, setPreview] = useState<PromptPreviewResponse | null>(null);
    const [variables, setVariables] = useState<Record<string, string>>({});
    const [search, setSearch] = useState('');
    const [groupFilter, setGroupFilter] = useState('all');
    const [acting, setActing] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setItems((await listPrompts(page, pageSize)).items);
        } catch (cause) {
            setError(cause instanceof PromptManagementError ? cause : new PromptManagementError('暂时无法加载 Prompt'));
        } finally {
            setLoading(false);
        }
    }, [page]);

    useEffect(() => {
        // Defer the initial fetch so the effect subscribes to the network boundary rather than synchronously cascading render state.
        const timer = window.setTimeout(() => void load(), 0);
        return () => window.clearTimeout(timer);
    }, [load]);

    const groupOptions = useMemo(() => {
        const groups = new Set(items.map(item => getPromptFunctionalGroup(item.name)));
        return [...groups].sort((left, right) => left.localeCompare(right, 'zh-CN'));
    }, [items]);

    const filteredItems = useMemo(() => {
        const query = search.trim().toLowerCase();
        return items.filter(item => {
            const matchesGroup = groupFilter === 'all' || getPromptFunctionalGroup(item.name) === groupFilter;
            const displayName = getPromptDisplayName(item.name).toLowerCase();
            const matchesSearch = !query || item.name.toLowerCase().includes(query) || displayName.includes(query) || item.labels.some(label => getPromptLabelDisplayName(label).toLowerCase().includes(query));
            return matchesGroup && matchesSearch;
        });
    }, [groupFilter, items, search]);

    /** Selects a prompt and initializes its local editor copy without mutating the immutable server record. */
    const selectPrompt = (prompt: PromptVersion) => {
        setSelected(prompt);
        setEditBody(renderBody(prompt.prompt));
        setEditCommit('');
        setEditMode('write');
        setEditing(false);
        setVariables({});
    };

    /** Loads the requested immutable version and resets its local-only editor state. */
    const openPrompt = async (item: PromptMetadata, selector: { version: number } | { label: string }) => {
        setActing(true);
        try {
            selectPrompt(await getPrompt(item.name, selector));
            setPreview(null);
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : '读取版本失败');
        } finally {
            setActing(false);
        }
    };

    /** Parses a text field into the prompt body required by the selected prompt type. */
    const parsePromptBody = (value: string, promptType: 'text' | 'chat'): PromptBody | null => {
        const parsed = parsePromptBodyForPreview(value, promptType);
        if (parsed === null || (promptType === 'text' && !value.trim())) {
            toast.error(promptType === 'chat' ? 'Chat Prompt 必须是有效 JSON 数组' : 'Prompt 内容不能为空');
            return null;
        }
        return parsed;
    };

    /** Creates a new immutable prompt record; its functional group is derived from the backend namespace. */
    const handleCreate = async () => {
        if (!name.trim() || !body.trim()) {
            toast.error('请填写名称和 Prompt 内容');
            return;
        }
        const prompt = parsePromptBody(body, type);
        if (prompt === null) return;
        setActing(true);
        try {
            const result = await createPromptVersion({ name: name.trim(), type, prompt, commit_message: commit.trim() || undefined });
            selectPrompt(result);
            setCreating(false);
            setPage(1);
            setName('');
            setBody('');
            setCommit('');
            toast.success(`已创建 v${result.version}，默认标记为草稿`);
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : '创建失败');
        } finally {
            setActing(false);
        }
    };

    /** Saves the local detail copy as a new immutable version, leaving the opened version—including v0—untouched. */
    const saveNewVersion = async () => {
        if (!selected || !editBody.trim()) {
            toast.error('请填写 Prompt 内容');
            return;
        }
        const prompt = parsePromptBody(editBody, selected.type);
        if (prompt === null) return;
        setActing(true);
        try {
            const result = await createPromptVersion({ name: selected.name, type: selected.type, prompt, labels: getCopyableLabels(selected.labels), commit_message: editCommit.trim() || undefined });
            selectPrompt(result);
            setPreview(null);
            toast.success(`已保存为新的不可变版本 v${result.version}`);
            await load();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : '保存新版本失败');
        } finally {
            setActing(false);
        }
    };

    /** Discards the local draft and restores the immutable content currently displayed. */
    const cancelEditing = () => {
        if (!selected) return;
        setEditBody(renderBody(selected.prompt));
        setEditCommit('');
        setEditMode('write');
        setEditing(false);
    };

    /** Promotes a version only after a native confirmation that explains the immutable-label behavior. */
    const promote = async () => {
        if (!selected || !window.confirm(`确认将「${getPromptDisplayName(selected.name)}」v${selected.version} 标记为生产版本？这会替换该版本的标签，版本内容仍不可变。`)) return;
        setActing(true);
        try {
            setSelected(await promotePromptToProduction(selected.name, selected.version));
            toast.success('已完成生产版本发布');
            await load();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : '更新标签失败');
        } finally {
            setActing(false);
        }
    };

    const detectedVariables = useMemo(() => {
        const source = typeof selected?.prompt === 'string' ? selected.prompt : JSON.stringify(selected?.prompt || '');
        return [...new Set([...source.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)].map(match => match[1]))];
    }, [selected]);

    /** Requests a no-model local substitution preview, with values constrained to visible variables. */
    const runPreview = async () => {
        if (!selected) return;
        setActing(true);
        try {
            setPreview(await previewPrompt({ name: selected.name, version: selected.version, values: variables }));
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : '预览失败');
        } finally {
            setActing(false);
        }
    };

    if (error?.status === 503) {
        return <div className="flex h-full items-center justify-center p-6"><div className="surface-panel max-w-lg p-8 text-center"><ShieldCheck className="mx-auto mb-4 h-10 w-10 text-amber-600" /><h2 className="text-xl font-semibold">Prompt 管理暂不可用</h2><p className="mt-3 text-sm leading-6 text-slate-600">服务器暂时无法访问 Prompt 数据库。请确认后端服务和数据库迁移已完成；模板内容不会保存在浏览器中。</p><Button className="mt-6" onClick={() => void load()}>重新检查</Button></div></div>;
    }

    if (selected) {
        return (
            <div className="min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top_right,_rgba(20,184,166,.12),transparent_32rem)] p-4 sm:p-8">
                <div className="mx-auto max-w-6xl">
                    <Button variant="ghost" onClick={() => setSelected(null)}><ArrowLeft />返回 Prompt 列表</Button>
                    <div className="mt-5 grid gap-5 lg:grid-cols-[1.1fr_.9fr]">
                        <section className="surface-panel overflow-hidden">
                            <div className="border-b border-slate-100 p-6">
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                    <div>
                                        <p className="font-mono text-xs text-teal-700">{selected.type.toUpperCase()} · VERSION {selected.version}</p>
                                        <h2 className="mt-2 text-2xl font-semibold tracking-tight">{getPromptDisplayName(selected.name)}</h2>
                                        <div className="mt-3 flex flex-wrap gap-2"><PromptGroupBadge name={selected.name} />{selected.labels.map(label => <PromptLabel key={label} label={label} />)}</div>
                                    </div>
                                    <Button disabled={acting || selected.version === 0 || selected.labels.includes('production')} onClick={() => void promote()}><Rocket />{selected.labels.includes('production') ? '已是生产版本' : selected.version === 0 ? '内置版本' : '发布为生产版本'}</Button>
                                </div>
                            </div>
                            <div className="border-b border-slate-100 p-6">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div><h3 className="font-semibold">版本内容</h3><p className="mt-1 text-sm text-slate-500">支持 Markdown。编辑会创建新版本，当前 v{selected.version} 的内容不会被修改。</p></div>
                                    {editing ? <div className="flex gap-2"><Button variant="outline" disabled={acting} onClick={cancelEditing}>取消</Button><Button disabled={acting} onClick={() => void saveNewVersion()}>{acting ? <Loader2 className="animate-spin" /> : <Check />}保存新版本</Button></div> : <Button variant="outline" disabled={acting} onClick={() => setEditing(true)}><Pencil />编辑</Button>}
                                </div>
                                {editing ? <><MarkdownEditor value={editBody} type={selected.type} mode={editMode} onChange={setEditBody} onModeChange={setEditMode} /><label className="mt-4 block text-sm font-medium">提交说明（可选）<Input className="mt-1.5" value={editCommit} onChange={event => setEditCommit(event.target.value)} placeholder="说明这次版本的变化" /></label></> : <div className="mt-5 max-h-[52vh] overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4"><PromptBodyMarkdown value={selected.prompt} /></div>}
                            </div>
                        </section>
                        <section className="space-y-5">
                            <div className="surface-panel p-6">
                                <div className="flex items-center gap-2"><FolderOpen className="h-5 w-5 text-violet-700" /><h3 className="font-semibold">功能分组</h3></div>
                                <p className="mt-2 text-sm leading-6 text-slate-500">分组来自后端 Prompt 命名空间，按功能自动归类，无需手动维护。</p>
                                <div className="mt-4"><PromptGroupBadge name={selected.name} /></div>
                            </div>
                            <div className="surface-panel p-6">
                                <div className="flex items-center gap-2"><Eye className="h-5 w-5 text-teal-700" /><h3 className="font-semibold">安全变量预览</h3></div>
                                <p className="mt-2 text-sm leading-6 text-slate-500">仅替换模板变量，不调用模型。未识别变量会保留并提示。</p>
                                {detectedVariables.length === 0 ? <p className="mt-6 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">这个版本没有检测到 {'{{variable}}'}。</p> : <div className="mt-5 space-y-3">{detectedVariables.map(variable => <label className="block text-sm font-medium text-slate-700" key={variable}>{variable}<Input className="mt-1.5" value={variables[variable] || ''} onChange={event => setVariables(current => ({ ...current, [variable]: event.target.value }))} /></label>)}<Button className="w-full" disabled={acting} onClick={() => void runPreview()}>{acting ? <Loader2 className="animate-spin" /> : <Sparkles />}生成预览</Button></div>}
                                {preview && <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">编译后内容</p><div className="mt-3 max-h-80 overflow-auto"><PromptBodyMarkdown value={preview.compiled_prompt} /></div>{preview.unresolved_variables.length > 0 && <p className="mt-3 text-xs text-amber-700">未解析：{preview.unresolved_variables.join(', ')}</p>}</div>}
                            </div>
                        </section>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-8">
            <div className="mx-auto max-w-6xl">
                <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
                    <div><p className="text-xs font-semibold uppercase tracking-[.22em] text-teal-700">提示词注册表</p><h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Prompt 管理</h2><p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">按后端功能分组并使用中文名称展示提示词。内容不可变，发布操作仍需要明确确认。</p></div>
                    <Button onClick={() => setCreating(true)}><FilePlus2 />新建版本</Button>
                </div>
                {creating && <div className="surface-panel mb-6 p-6">
                    <div className="mb-5 flex items-center justify-between gap-3"><div><h3 className="text-lg font-semibold">创建不可变版本</h3><p className="mt-1 text-xs text-slate-500">默认标签：草稿 · 内容支持 Markdown</p></div><button className="text-sm text-slate-500 hover:text-slate-900" onClick={() => setCreating(false)} type="button">关闭</button></div>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <label className="text-sm font-medium">名称<Input className="mt-1.5" value={name} onChange={event => setName(event.target.value)} placeholder="例如 interview.system" /></label>
                        <label className="text-sm font-medium">类型<select className="mt-1.5 h-9 w-full rounded-md border border-input bg-white px-3 text-sm" value={type} onChange={event => setType(event.target.value as 'text' | 'chat')}><option value="text">文本 Prompt</option><option value="chat">Chat（JSON 数组）</option></select></label>
                    </div>
                    <label className="mt-4 block text-sm font-medium">Prompt 内容<MarkdownEditor value={body} type={type} mode={createMode} onChange={setBody} onModeChange={setCreateMode} /></label>
                    <label className="mt-4 block text-sm font-medium">提交说明（可选）<Input className="mt-1.5" value={commit} onChange={event => setCommit(event.target.value)} placeholder="说明这次版本的变化" /></label>
                    <div className="mt-5 flex justify-end gap-2"><Button variant="outline" disabled={acting} onClick={() => setCreating(false)}>取消</Button><Button disabled={acting} onClick={() => void handleCreate()}>{acting ? <Loader2 className="animate-spin" /> : <Check />}创建版本</Button></div>
                </div>}
                <div className="surface-panel overflow-hidden">
                    <div className="flex flex-col gap-3 border-b border-slate-100 bg-slate-50 p-4 sm:flex-row sm:items-center">
                        <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input className="pl-9" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索提示词名称或标签" aria-label="搜索提示词" /></div>
                        <div className="flex items-center gap-2"><FolderOpen className="h-4 w-4 text-violet-600" /><select className="h-9 min-w-44 rounded-md border border-input bg-white px-3 text-sm" value={groupFilter} onChange={event => setGroupFilter(event.target.value)} aria-label="按功能分组筛选"><option value="all">全部功能</option>{groupOptions.map(group => <option key={group} value={group}>{group}</option>)}</select></div>
                    </div>
                    {error && <div className="border-b border-amber-100 bg-amber-50 px-5 py-3 text-sm text-amber-800">{error.message}<button className="ml-3 font-medium underline" onClick={() => void load()} type="button">重试</button></div>}
                    <div className="hidden grid-cols-[minmax(0,1fr)_auto_auto] gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3 text-xs font-semibold tracking-wide text-slate-500 sm:grid"><span>提示词</span><span>版本</span><span>功能 / 状态</span></div>
                    {loading ? <div className="flex justify-center p-12"><Loader2 className="animate-spin text-teal-700" /></div> : filteredItems.length === 0 ? <div className="p-10 text-center"><BookOpen className="mx-auto h-8 w-8 text-slate-300" /><p className="mt-3 text-sm text-slate-500">{items.length === 0 ? '尚无 Prompt 版本。' : '当前筛选条件下没有匹配的 Prompt。'}</p></div> : filteredItems.map(item => <button className="grid w-full grid-cols-1 gap-3 border-b border-slate-100 px-5 py-4 text-left transition-colors hover:bg-teal-50/40 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center" key={item.name} onClick={() => void openPrompt(item, { version: Math.max(...item.versions) })}><span><span className="block font-medium text-slate-900">{getPromptDisplayName(item.name)}</span><span className="mt-1 block text-xs text-slate-500">{item.type === 'chat' ? 'Chat 对话提示词' : 'Markdown 文本提示词'} · {getPromptFunctionalGroup(item.name)}</span></span><span className="font-mono text-sm text-slate-600">v{Math.max(...item.versions)}</span><span className="flex flex-wrap justify-start gap-1 sm:justify-end"><PromptGroupBadge name={item.name} />{item.labels.map(label => <PromptLabel key={label} label={label} />)}</span></button>)}
                </div>
                <div className="mt-5 flex items-center justify-end gap-2"><Button variant="outline" size="icon" disabled={loading || page === 1} onClick={() => setPage(current => current - 1)} aria-label="上一页"><ChevronLeft /></Button><span className="text-sm text-slate-500">第 {page} 页</span><Button variant="outline" size="icon" disabled={loading || items.length < pageSize} onClick={() => setPage(current => current + 1)} aria-label="下一页"><ChevronRight /></Button></div>
            </div>
        </div>
    );
}

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, BookOpen, Check, CloudUpload, Code2, Eye, FilePlus2, FolderOpen, Loader2, Pencil, Rocket, Search, ShieldCheck, Sparkles, Tag } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/atom-one-dark.css';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { createPromptVersion, getPrompt, listPrompts, previewPrompt, promotePromptToProduction, PromptManagementError, syncBuiltinPrompts, type PromptBody, type PromptChatMessage, type PromptMetadata, type PromptPreviewResponse, type PromptVersion } from '@/lib/api/prompts';
import { getPromptDisplayName, getPromptFunctionalGroup, getPromptLabelDisplayName } from '@/lib/promptCatalog';
import { getPromptManagementTagsForCategory, getVisiblePromptManagementTags, type PromptManagementTag } from '@/lib/promptManagementTags';
import { PaginationControls } from '@/components/PaginationControls';
import { DEFAULT_PAGE_SIZE } from '@/lib/pagination';

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
                            <span className="text-[10px] tracking-wide text-slate-400">第 {index + 1} 条消息</span>
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
                <div className="flex gap-1" role="tablist" aria-label="提示词内容模式">
                    <button className={cn('rounded-md px-3 py-1.5 text-xs font-medium transition-colors', mode === 'write' ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500 hover:bg-white/70')} onClick={() => onModeChange('write')} role="tab" aria-selected={mode === 'write'} type="button"><Code2 className="mr-1.5 inline h-3.5 w-3.5" />编辑</button>
                    <button className={cn('rounded-md px-3 py-1.5 text-xs font-medium transition-colors', mode === 'preview' ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500 hover:bg-white/70')} onClick={() => onModeChange('preview')} role="tab" aria-selected={mode === 'preview'} type="button"><Eye className="mr-1.5 inline h-3.5 w-3.5" />Markdown 预览</button>
                </div>
                <span className="hidden text-[11px] text-slate-400 sm:inline">支持标题、列表、引用、代码块</span>
            </div>
            {mode === 'write' ? <Textarea className="min-h-56 resize-y rounded-none border-0 font-mono text-sm shadow-none focus-visible:ring-0" value={value} onChange={event => onChange(event.target.value)} placeholder={type === 'text' ? '你是一个面试官…\n\n## 任务\n请分析 {{candidate_name}}' : '[{"role":"system","content":"你是一个…"}]'} /> : previewBody ? <div className="max-h-[32rem] min-h-56 overflow-auto p-4"><PromptBodyMarkdown value={previewBody} /></div> : <div className="min-h-56 p-4 text-sm text-slate-500">{type === 'text' ? '填写内容后即可查看 Markdown 预览。' : '对话提示词需要先填写有效的 JSON 数组，才能预览。'}</div>}
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
function PromptGroupBadge({ name, functionalGroup }: { name: string; functionalGroup?: string }) {
    return <span className={cn(badge, 'border-violet-200 bg-violet-50 text-violet-700')}><FolderOpen className="mr-1 inline h-3 w-3" />{getPromptFunctionalGroup(name, functionalGroup)}</span>;
}

/** Displays backend-owned specialist roles without repeating the functional-group badge. */
function PromptManagementTags({ name, functionalGroup, tags }: { name: string; functionalGroup?: string; tags?: PromptManagementTag[] }) {
    const group = getPromptFunctionalGroup(name, functionalGroup);
    return <>{getVisiblePromptManagementTags(tags, group).map(tag => <span className={cn(badge, tag.category === '处理阶段' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : tag.category === '工作职责' ? 'border-cyan-200 bg-cyan-50 text-cyan-800' : 'border-sky-200 bg-sky-50 text-sky-800')} key={tag.key}><Tag className="mr-1 inline h-3 w-3" />{tag.label}</span>)}</>;
}

/** Renders the prompt registry with backend-driven functional-tag filtering and immutable version actions. */
export function PromptManagementPage() {
    const [items, setItems] = useState<PromptMetadata[]>([]);
    const [total, setTotal] = useState(0);
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
    const [domainFilter, setDomainFilter] = useState('');
    const [responsibilityFilter, setResponsibilityFilter] = useState('');
    const [stageFilter, setStageFilter] = useState('');
    const [availableManagementTags, setAvailableManagementTags] = useState<PromptManagementTag[]>([]);
    const [acting, setActing] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [evaluationRunId, setEvaluationRunId] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await listPrompts(page, DEFAULT_PAGE_SIZE, {
                domain: domainFilter,
                responsibility: responsibilityFilter,
                stage: stageFilter,
            });
            setItems(response.items);
            setTotal(response.total);
            setAvailableManagementTags(response.available_management_tags ?? []);
        } catch (cause) {
            setError(cause instanceof PromptManagementError ? cause : new PromptManagementError('暂时无法加载提示词'));
        } finally {
            setLoading(false);
        }
    }, [domainFilter, page, responsibilityFilter, stageFilter]);

    useEffect(() => {
        // Defer the initial fetch so the effect subscribes to the network boundary rather than synchronously cascading render state.
        const timer = window.setTimeout(() => void load(), 0);
        return () => window.clearTimeout(timer);
    }, [load]);

    const filteredItems = useMemo(() => {
        const query = search.trim().toLowerCase();
        return items.filter(item => {
            const displayName = getPromptDisplayName(item.name, item.display_name).toLowerCase();
            const matchesSearch = !query
                || item.name.toLowerCase().includes(query)
                || displayName.includes(query)
                || item.labels.some(label => getPromptLabelDisplayName(label).toLowerCase().includes(query))
                || (item.management_tags ?? []).some(tag => tag.label.toLowerCase().includes(query));
            return matchesSearch;
        });
    }, [items, search]);

    const domainOptions = useMemo(
        () => getPromptManagementTagsForCategory(availableManagementTags, '业务领域'),
        [availableManagementTags],
    );
    const responsibilityOptions = useMemo(
        () => getPromptManagementTagsForCategory(availableManagementTags, '工作职责'),
        [availableManagementTags],
    );
    const stageOptions = useMemo(
        () => getPromptManagementTagsForCategory(availableManagementTags, '处理阶段'),
        [availableManagementTags],
    );
    const hasManagementFilters = Boolean(domainFilter || responsibilityFilter || stageFilter);

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
            toast.error(promptType === 'chat' ? '对话提示词必须是有效 JSON 数组' : '提示词内容不能为空');
            return null;
        }
        return parsed;
    };

    /** Creates a new immutable prompt record; its functional group is derived from the backend namespace. */
    const handleCreate = async () => {
        if (!name.trim() || !body.trim()) {
            toast.error('请填写名称和提示词内容');
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
            toast.error('请填写提示词内容');
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
        if (!selected || !window.confirm(`确认将「${getPromptDisplayName(selected.name, selected.display_name)}」版本 ${selected.version} 标记为生产版本？这会替换该版本的标签，版本内容仍不可变。`)) return;
        setActing(true);
        try {
            setSelected(await promotePromptToProduction(selected.name, selected.version, evaluationRunId.trim() || undefined));
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

    /** Publishes only missing built-in production prompts, preserving cloud-owned versions. */
    const syncBuiltins = async () => {
        setSyncing(true);
        try {
            const result = await syncBuiltinPrompts();
            toast.success(
                result.created > 0
                    ? `已同步 ${result.created} 个生产提示词，跳过 ${result.skipped} 个已有版本`
                    : `云端 ${result.discovered} 个内置提示词已全部就绪`,
            );
            setPage(1);
            await load();
        } catch (cause) {
            toast.error(cause instanceof Error ? cause.message : '同步 Langfuse 提示词失败');
        } finally {
            setSyncing(false);
        }
    };

    if (error?.status === 503) {
        return <div className="flex h-full items-center justify-center p-6"><div className="surface-panel max-w-lg p-8 text-center"><ShieldCheck className="mx-auto mb-4 h-10 w-10 text-amber-600" /><h2 className="text-xl font-semibold">Langfuse 提示词管理暂不可用</h2><p className="mt-3 text-sm leading-6 text-slate-600">请确认已启用 Langfuse 提示词管理，并配置当前项目的 Public Key、Secret Key 和 Base URL。</p><Button className="mt-6" onClick={() => void load()}>重新检查</Button></div></div>;
    }

    if (selected) {
        return (
            <div className="min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top_right,_rgba(20,184,166,.12),transparent_32rem)] p-4 sm:p-8">
                <div className="mx-auto max-w-6xl">
                    <Button variant="ghost" onClick={() => setSelected(null)}><ArrowLeft />返回提示词列表</Button>
                    <div className="mt-5 grid gap-5 lg:grid-cols-[1.1fr_.9fr]">
                        <section className="surface-panel overflow-hidden">
                            <div className="border-b border-slate-100 p-6">
                                <div className="flex flex-wrap items-start justify-between gap-4">
                                    <div>
                                        <p className="text-xs font-medium text-teal-700">{selected.type === 'chat' ? '对话提示词' : '文本提示词'} · 版本 {selected.version}</p>
                                        <h2 className="mt-2 text-2xl font-semibold tracking-tight">{getPromptDisplayName(selected.name, selected.display_name)}</h2>
                                        <div className="mt-3 flex flex-wrap gap-2"><PromptGroupBadge name={selected.name} functionalGroup={selected.functional_group} /><PromptManagementTags name={selected.name} functionalGroup={selected.functional_group} tags={selected.management_tags} />{selected.is_builtin && !selected.labels.includes('builtin') && <PromptLabel label="builtin" />}{selected.labels.map(label => <PromptLabel key={label} label={label} />)}</div>
                                    </div>
                                    <Button disabled={acting || selected.version === 0 || selected.labels.includes('production')} onClick={() => void promote()}><Rocket />{selected.labels.includes('production') ? '已是生产版本' : selected.version === 0 ? '内置版本' : '发布为生产版本'}</Button>
                                </div>
                            </div>
                            <div className="border-b border-slate-100 p-6">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div><h3 className="font-semibold">版本内容</h3><p className="mt-1 text-sm text-slate-500">支持 Markdown。编辑会创建新版本，当前版本 {selected.version} 的内容不会被修改。</p></div>
                                    {editing ? <div className="flex gap-2"><Button variant="outline" disabled={acting} onClick={cancelEditing}>取消</Button><Button disabled={acting} onClick={() => void saveNewVersion()}>{acting ? <Loader2 className="animate-spin" /> : <Check />}保存新版本</Button></div> : <Button variant="outline" disabled={acting} onClick={() => setEditing(true)}><Pencil />编辑</Button>}
                                </div>
                                {editing ? <><MarkdownEditor value={editBody} type={selected.type} mode={editMode} onChange={setEditBody} onModeChange={setEditMode} /><label className="mt-4 block text-sm font-medium">提交说明（可选）<Input className="mt-1.5" value={editCommit} onChange={event => setEditCommit(event.target.value)} placeholder="说明这次版本的变化" /></label></> : <div className="mt-5 max-h-[52vh] overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4"><PromptBodyMarkdown value={selected.prompt} /></div>}
                            </div>
                        </section>
                        <section className="space-y-5">
                            <div className="surface-panel p-6">
                                <div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-emerald-700" /><h3 className="font-semibold">评测与发布门禁</h3></div>
                                <p className="mt-2 text-sm leading-6 text-slate-500">先在 Agent 评测中心运行当前版本并与生产版本基线比较。门禁为强制时，后端只接受通过门禁结果的版本。</p>
                                <Input className="mt-4" value={evaluationRunId} onChange={event => setEvaluationRunId(event.target.value)} placeholder="评测运行 ID（发布时可选/强制模式必填）" />
                                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                                    <Button variant="outline" onClick={() => { localStorage.setItem('evaluationPromptCandidate', JSON.stringify({ name: selected.name, version: selected.version, compareProduction: false })); localStorage.setItem('activeMainTab', 'evaluations'); window.location.reload(); }}>运行评测</Button>
                                    <Button variant="outline" onClick={() => { localStorage.setItem('evaluationPromptCandidate', JSON.stringify({ name: selected.name, version: selected.version, compareProduction: true })); localStorage.setItem('activeMainTab', 'evaluations'); window.location.reload(); }}>与生产版本对比</Button>
                                </div>
                            </div>
                            <div className="surface-panel p-6">
                                <div className="flex items-center gap-2"><Tag className="h-5 w-5 text-cyan-700" /><h3 className="font-semibold">功能标签</h3></div>
                                <p className="mt-2 text-sm leading-6 text-slate-500">标签由后端提示词注册表按功能与专家职责自动归类，无需手动维护。</p>
                                <div className="mt-4 flex flex-wrap gap-2"><PromptGroupBadge name={selected.name} functionalGroup={selected.functional_group} /><PromptManagementTags name={selected.name} functionalGroup={selected.functional_group} tags={selected.management_tags} /></div>
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
                    <div><p className="text-xs font-semibold uppercase tracking-[.22em] text-teal-700">Langfuse Cloud</p><h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">提示词管理</h2><p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">直接读取和管理当前 Langfuse 项目的提示词；运行时使用标记为“生产”的云端版本。</p></div>
                    <div className="flex flex-wrap gap-2">
                        <Button variant="outline" disabled={syncing || acting} onClick={() => void syncBuiltins()}>{syncing ? <Loader2 className="animate-spin" /> : <CloudUpload />}同步内置提示词</Button>
                        <Button onClick={() => setCreating(true)}><FilePlus2 />新建版本</Button>
                    </div>
                </div>
                {creating && <div className="surface-panel mb-6 p-6">
                    <div className="mb-5 flex items-center justify-between gap-3"><div><h3 className="text-lg font-semibold">创建不可变版本</h3><p className="mt-1 text-xs text-slate-500">默认标签：草稿 · 内容支持 Markdown</p></div><button className="text-sm text-slate-500 hover:text-slate-900" onClick={() => setCreating(false)} type="button">关闭</button></div>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <label className="text-sm font-medium">名称<Input className="mt-1.5" value={name} onChange={event => setName(event.target.value)} placeholder="例如 interview.system" /></label>
                        <label className="text-sm font-medium">类型<select className="mt-1.5 h-9 w-full rounded-md border border-input bg-white px-3 text-sm" value={type} onChange={event => setType(event.target.value as 'text' | 'chat')}><option value="text">文本提示词</option><option value="chat">对话提示词（JSON 数组）</option></select></label>
                    </div>
                    <label className="mt-4 block text-sm font-medium">提示词内容<MarkdownEditor value={body} type={type} mode={createMode} onChange={setBody} onModeChange={setCreateMode} /></label>
                    <label className="mt-4 block text-sm font-medium">提交说明（可选）<Input className="mt-1.5" value={commit} onChange={event => setCommit(event.target.value)} placeholder="说明这次版本的变化" /></label>
                    <div className="mt-5 flex justify-end gap-2"><Button variant="outline" disabled={acting} onClick={() => setCreating(false)}>取消</Button><Button disabled={acting} onClick={() => void handleCreate()}>{acting ? <Loader2 className="animate-spin" /> : <Check />}创建版本</Button></div>
                </div>}
                <div className="surface-panel overflow-hidden">
                    <div className="flex flex-col gap-3 border-b border-slate-100 bg-slate-50 p-4 sm:flex-row sm:items-center">
                        <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><Input className="pl-9" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="搜索提示词、职责或生命周期标签" aria-label="搜索提示词" /></div>
                        <div className="grid gap-2 sm:grid-cols-3">
                            <label className="flex min-w-0 items-center gap-2 text-sm text-slate-600"><Tag className="h-4 w-4 shrink-0 text-cyan-700" /><span className="sr-only">业务领域</span><select className="h-9 min-w-0 flex-1 rounded-md border border-input bg-white px-3 text-sm" value={domainFilter} onChange={event => { setDomainFilter(event.target.value); setPage(1); }} aria-label="按业务领域筛选"><option value="">全部业务领域</option>{domainOptions.map(tag => <option key={tag.key} value={tag.key}>{tag.label}</option>)}</select></label>
                            <label className="flex min-w-0 items-center gap-2 text-sm text-slate-600"><Tag className="h-4 w-4 shrink-0 text-cyan-700" /><span className="sr-only">工作职责</span><select className="h-9 min-w-0 flex-1 rounded-md border border-input bg-white px-3 text-sm" value={responsibilityFilter} onChange={event => { setResponsibilityFilter(event.target.value); setPage(1); }} aria-label="按工作职责筛选"><option value="">全部工作职责</option>{responsibilityOptions.map(tag => <option key={tag.key} value={tag.key}>{tag.label}</option>)}</select></label>
                            <label className="flex min-w-0 items-center gap-2 text-sm text-slate-600"><Tag className="h-4 w-4 shrink-0 text-cyan-700" /><span className="sr-only">处理阶段</span><select className="h-9 min-w-0 flex-1 rounded-md border border-input bg-white px-3 text-sm" value={stageFilter} onChange={event => { setStageFilter(event.target.value); setPage(1); }} aria-label="按处理阶段筛选"><option value="">全部处理阶段</option>{stageOptions.map(tag => <option key={tag.key} value={tag.key}>{tag.label}</option>)}</select></label>
                        </div>
                    </div>
                    {error && <div className="border-b border-amber-100 bg-amber-50 px-5 py-3 text-sm text-amber-800">{error.message}<button className="ml-3 font-medium underline" onClick={() => void load()} type="button">重试</button></div>}
                    <div className="hidden grid-cols-[minmax(0,1fr)_auto_auto] gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3 text-xs font-semibold tracking-wide text-slate-500 sm:grid"><span>提示词</span><span>版本</span><span>功能 / 标签</span></div>
                    {loading ? <div className="flex justify-center p-12"><Loader2 className="animate-spin text-teal-700" /></div> : filteredItems.length === 0 ? <div className="p-10 text-center"><BookOpen className="mx-auto h-8 w-8 text-slate-300" /><p className="mt-3 text-sm text-slate-500">{items.length === 0 ? hasManagementFilters ? '当前组合筛选条件下没有可管理的提示词。' : '当前 Langfuse 项目尚无提示词。可同步后端内置模板并自动标记为生产版本。' : '当前搜索条件下没有匹配的提示词。'}</p>{items.length === 0 && !hasManagementFilters && <Button className="mt-5" disabled={syncing} onClick={() => void syncBuiltins()}>{syncing ? <Loader2 className="animate-spin" /> : <CloudUpload />}同步内置提示词</Button>}</div> : filteredItems.map(item => <button className="grid w-full grid-cols-1 gap-3 border-b border-slate-100 px-5 py-4 text-left transition-colors hover:bg-teal-50/40 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center" key={item.name} onClick={() => void openPrompt(item, { version: Math.max(...item.versions) })}><span><span className="block font-medium text-slate-900">{getPromptDisplayName(item.name, item.display_name)}</span><span className="mt-1 block text-xs text-slate-500">{item.type === 'chat' ? '对话提示词' : '文本提示词'} · {getPromptFunctionalGroup(item.name, item.functional_group)}</span></span><span className="text-sm text-slate-600">版本 {Math.max(...item.versions)}</span><span className="flex flex-wrap justify-start gap-1 sm:justify-end"><PromptGroupBadge name={item.name} functionalGroup={item.functional_group} /><PromptManagementTags name={item.name} functionalGroup={item.functional_group} tags={item.management_tags} />{item.is_builtin && !item.labels.includes('builtin') && <PromptLabel label="builtin" />}{item.labels.map(label => <PromptLabel key={label} label={label} />)}</span></button>)}
                </div>
                <PaginationControls
                    className="mt-5"
                    page={page}
                    total={total}
                    loading={loading}
                    onPageChange={setPage}
                />
            </div>
        </div>
    );
}

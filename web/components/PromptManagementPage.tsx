'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, ChevronLeft, ChevronRight, Eye, FilePlus2, Loader2, Rocket, ShieldCheck, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { createPromptVersion, getPrompt, listPrompts, previewPrompt, promotePromptToProduction, PromptManagementError, type PromptBody, type PromptMetadata, type PromptPreviewResponse, type PromptVersion } from '@/lib/api/prompts';

const pageSize = 12;
const badge = 'rounded-full border px-2 py-0.5 text-[11px] font-medium';

/** Renders the bounded Prompt Management workspace, keeping mutations explicit and prompt configuration server-side. */
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
    const [preview, setPreview] = useState<PromptPreviewResponse | null>(null);
    const [variables, setVariables] = useState<Record<string, string>>({});
    const [acting, setActing] = useState(false);

    const load = useCallback(async () => {
        setLoading(true); setError(null);
        try { setItems((await listPrompts(page, pageSize)).items); }
        catch (cause) { setError(cause instanceof PromptManagementError ? cause : new PromptManagementError('暂时无法加载 Prompt')); }
        finally { setLoading(false); }
    }, [page]);
    useEffect(() => {
        // Defer the initial fetch so the effect subscribes to the network boundary rather than synchronously cascading render state.
        const timer = window.setTimeout(() => void load(), 0);
        return () => window.clearTimeout(timer);
    }, [load]);

    /** Loads a selected immutable version while preserving the list context. */
    const openPrompt = async (item: PromptMetadata, selector: { version: number } | { label: string }) => {
        setActing(true); try { setSelected(await getPrompt(item.name, selector)); setPreview(null); } catch (cause) { toast.error(cause instanceof Error ? cause.message : '读取版本失败'); } finally { setActing(false); }
    };
    /** Creates a new immutable draft version after validating the local form only. */
    const handleCreate = async () => {
        if (!name.trim() || !body.trim()) { toast.error('请填写名称和 Prompt 内容'); return; }
        let prompt: PromptBody = body;
        if (type === 'chat') { try { prompt = JSON.parse(body) as PromptBody; } catch { toast.error('Chat Prompt 必须是有效 JSON 数组'); return; } }
        setActing(true); try { const result = await createPromptVersion({ name: name.trim(), type, prompt, commit_message: commit.trim() || undefined }); setSelected(result); setCreating(false); setPage(1); toast.success(`已创建 v${result.version}，默认标记为 draft`); } catch (cause) { toast.error(cause instanceof Error ? cause.message : '创建失败'); } finally { setActing(false); }
    };
    /** Promotes a version only after a native confirmation that explains the immutable-label behavior. */
    const promote = async () => {
        if (!selected || !window.confirm(`确认将 ${selected.name} v${selected.version} 标记为 production？这会替换该版本的标签，版本内容仍不可变。`)) return;
        setActing(true); try { setSelected(await promotePromptToProduction(selected.name, selected.version)); toast.success('已完成 production promotion'); await load(); } catch (cause) { toast.error(cause instanceof Error ? cause.message : '更新标签失败'); } finally { setActing(false); }
    };
    const detectedVariables = useMemo(() => {
        const source = typeof selected?.prompt === 'string' ? selected.prompt : JSON.stringify(selected?.prompt || '');
        return [...new Set([...source.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)].map(match => match[1]))];
    }, [selected]);
    /** Requests a no-model local substitution preview, with values constrained to visible variables. */
    const runPreview = async () => {
        if (!selected) return;
        setActing(true); try { setPreview(await previewPrompt({ name: selected.name, version: selected.version, values: variables })); } catch (cause) { toast.error(cause instanceof Error ? cause.message : '预览失败'); } finally { setActing(false); }
    };
    const renderBody = (value: PromptBody) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);

    if (error?.status === 503) return <div className="flex h-full items-center justify-center p-6"><div className="surface-panel max-w-lg p-8 text-center"><ShieldCheck className="mx-auto mb-4 h-10 w-10 text-amber-600" /><h2 className="text-xl font-semibold">Prompt Management 尚未启用</h2><p className="mt-3 text-sm leading-6 text-slate-600">服务器返回 503。请在服务端启用并配置 Langfuse Prompt Management；密钥和配置不会在浏览器中展示。</p><Button className="mt-6" onClick={() => void load()}>重新检查</Button></div></div>;
    if (selected) return <div className="min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top_right,_rgba(20,184,166,.12),transparent_32rem)] p-4 sm:p-8"><div className="mx-auto max-w-6xl"><Button variant="ghost" onClick={() => setSelected(null)}><ArrowLeft />返回 Prompt 列表</Button><div className="mt-5 grid gap-5 lg:grid-cols-[1.1fr_.9fr]"><section className="surface-panel overflow-hidden"><div className="border-b border-slate-100 p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="font-mono text-xs text-teal-700">{selected.type.toUpperCase()} · VERSION {selected.version}</p><h2 className="mt-2 text-2xl font-semibold tracking-tight">{selected.name}</h2><div className="mt-3 flex flex-wrap gap-2">{selected.labels.map(label => <span className={cn(badge, label === 'production' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-600')} key={label}>{label}</span>)}</div></div><Button disabled={acting || selected.labels.includes('production')} onClick={() => void promote()}><Rocket />{selected.labels.includes('production') ? '已是 production' : 'Promote'}</Button></div></div><pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap p-6 font-mono text-sm leading-7 text-slate-700">{renderBody(selected.prompt)}</pre></section><section className="surface-panel p-6"><div className="flex items-center gap-2"><Eye className="h-5 w-5 text-teal-700" /><h3 className="font-semibold">安全变量预览</h3></div><p className="mt-2 text-sm leading-6 text-slate-500">仅替换模板变量，不调用模型。未识别变量会保留并提示。</p>{detectedVariables.length === 0 ? <p className="mt-6 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">这个版本没有检测到 {'{{variable}}'}。</p> : <div className="mt-5 space-y-3">{detectedVariables.map(variable => <label className="block text-sm font-medium text-slate-700" key={variable}>{variable}<Input className="mt-1.5" value={variables[variable] || ''} onChange={event => setVariables(current => ({ ...current, [variable]: event.target.value }))} placeholder="可选替换值" /></label>)}<Button variant="secondary" disabled={acting} onClick={() => void runPreview()}>{acting ? <Loader2 className="animate-spin" /> : <Sparkles />}生成预览</Button></div>}{preview && <div className="mt-6 border-t border-slate-100 pt-5"><div className="flex items-center gap-2 text-sm font-semibold text-teal-800"><Check className="h-4 w-4" />编译结果</div><pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 font-mono text-xs leading-6 text-teal-50">{renderBody(preview.compiled_prompt)}</pre>{preview.unresolved_variables.length > 0 && <p className="mt-2 text-xs text-amber-700">未解决：{preview.unresolved_variables.join('、')}</p>}</div>}</section></div></div></div>;

    return <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-8"><div className="mx-auto max-w-6xl"><div className="mb-7 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[.22em] text-teal-700">Prompt registry</p><h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Prompt 管理</h2><p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">把提示词当作可审计的版本资产。内容不可变，标签 promotion 需要明确确认。</p></div><Button onClick={() => setCreating(true)}><FilePlus2 />新建版本</Button></div><div className="mb-6 rounded-2xl border border-teal-100 bg-teal-50/70 p-4 text-sm text-teal-900"><ShieldCheck className="mr-2 inline h-4 w-4" />浏览器只访问受限 API，不保存或展示 Langfuse 密钥、连接配置。</div>{creating && <div className="surface-panel mb-6 p-6"><div className="mb-5 flex items-center justify-between"><h3 className="text-lg font-semibold">创建不可变版本</h3><span className="text-xs text-slate-500">默认标签：draft</span></div><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium">名称<Input className="mt-1.5" value={name} onChange={event => setName(event.target.value)} placeholder="例如 interview.system" /></label><label className="text-sm font-medium">类型<select className="mt-1.5 h-9 w-full rounded-md border border-input bg-white px-3 text-sm" value={type} onChange={event => setType(event.target.value as 'text' | 'chat')}><option value="text">Text</option><option value="chat">Chat（JSON 数组）</option></select></label></div><label className="mt-4 block text-sm font-medium">Prompt 内容<Textarea className="mt-1.5 min-h-48 font-mono text-sm" value={body} onChange={event => setBody(event.target.value)} placeholder={type === 'text' ? '你是一个… {{candidate_name}}' : '[{"role":"system","content":"你是…"}]'} /></label><label className="mt-4 block text-sm font-medium">提交说明（可选）<Input className="mt-1.5" value={commit} onChange={event => setCommit(event.target.value)} placeholder="说明这次版本的变化" /></label><div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={() => setCreating(false)}>取消</Button><Button disabled={acting} onClick={() => void handleCreate()}>{acting && <Loader2 className="animate-spin" />}创建 draft 版本</Button></div></div>}<div className="surface-panel overflow-hidden">{error && <div className="border-b border-red-100 bg-red-50 p-4 text-sm text-red-800">{error.message}<button className="ml-3 underline" onClick={() => void load()}>重试</button></div>}{loading ? <div className="flex justify-center p-16"><Loader2 className="animate-spin text-teal-700" /></div> : items.length === 0 ? <div className="p-16 text-center text-sm text-slate-500">这一页还没有 Prompt。</div> : <div className="divide-y divide-slate-100">{items.map(item => <button className="group flex w-full items-center justify-between gap-4 p-5 text-left transition hover:bg-teal-50/40 sm:p-6" key={item.name} onClick={() => void openPrompt(item, item.labels[0] ? { label: item.labels[0] } : { version: Math.max(...item.versions) })}><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="truncate font-mono text-sm font-semibold text-slate-900">{item.name}</span><span className={cn(badge, 'border-slate-200 text-slate-500')}>{item.type}</span>{item.labels.map(label => <span className={cn(badge, label === 'production' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500')} key={label}>{label}</span>)}</div><p className="mt-2 text-xs text-slate-500">{item.versions.length} 个版本 · 最新 v{Math.max(...item.versions)}</p></div><ChevronRight className="h-5 w-5 shrink-0 text-slate-300 transition group-hover:translate-x-1 group-hover:text-teal-700" /></button>)}</div>}<div className="flex items-center justify-between border-t border-slate-100 p-4"><span className="text-xs text-slate-500">第 {page} 页 · 每页 {pageSize} 条</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page === 1 || loading} onClick={() => setPage(value => value - 1)}><ChevronLeft />上一页</Button><Button variant="outline" size="sm" disabled={loading || items.length < pageSize} onClick={() => setPage(value => value + 1)}>下一页<ChevronRight /></Button></div></div></div></div></div>;
}

'use client';

import { useEffect, useMemo, useState } from 'react';
import {
    CheckCircle2,
    Copy,
    KeyRound,
    Pencil,
    Plus,
    ServerCog,
    ShieldAlert,
    Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { type ModelConfig, useInterviewStore } from '@/store/useInterviewStore';
import {
    deleteModelCredential,
    fetchModelCredentialStatuses,
    saveModelCredential,
} from '@/lib/api/modelCredentials';
import { toast } from 'sonner';
import { ModelFormDialog } from './settings/ModelFormDialog';
import { ModelAssignments } from './settings/ModelAssignments';

interface SettingsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

const KIND_LABEL: Record<string, string> = {
    chat: '文本 / 推理',
    embedding: 'Embedding',
    voice: 'MiMo 语音拆分',
};

/** Encapsulates safe endpoint label; returns typed data or state and keeps side effects within the owning module boundary. */
function safeEndpointLabel(baseUrl: string) {
    try {
        return new URL(baseUrl).host;
    } catch {
        return baseUrl;
    }
}

/** Formats the Redis credential expiry as a compact user-facing status. */
function credentialLabel(model: ModelConfig): string {
    if (!model.credentialStored) return '未保存或已过期';
    if (!model.credentialExpiresAt) return '已保存';
    const remainingMs = new Date(model.credentialExpiresAt).getTime() - Date.now();
    if (!Number.isFinite(remainingMs) || remainingMs <= 0) return '已过期';
    const remainingDays = Math.max(1, Math.ceil(remainingMs / 86_400_000));
    return `已保存（约 ${remainingDays} 天，使用时自动续期）`;
}

/** Renders the settings dialog UI and coordinates its typed props, local state, and approved backend interactions. */
export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
    const store = useInterviewStore();
    const config = store.apiConfig;
    const [showModelForm, setShowModelForm] = useState(false);
    const [editingModel, setEditingModel] = useState<ModelConfig | undefined>();
    const [sourceModel, setSourceModel] = useState<ModelConfig | undefined>();
    const modelKeys = useMemo(() => config.models.map(model => ({ modelName: model.model, legacyId: model.id })), [config.models]);
    const modelKeysToken = useMemo(() => modelKeys.map(item => `${item.modelName}\u0000${item.legacyId}`).sort().join(','), [modelKeys]);

    useEffect(() => {
        if (!modelKeysToken) return;
        let cancelled = false;
        void fetchModelCredentialStatuses(modelKeys).then(statuses => {
            if (cancelled) return;
            const byModelName = new Map(statuses.map(status => [status.model_name, status]));
            config.models.forEach(model => {
                const status = byModelName.get(model.model);
                store.updateModel(model.id, {
                    apiKey: '',
                    credentialStored: status?.stored === true,
                    credentialExpiresAt: status?.expires_at || undefined,
                });
            });
        }).catch(() => {
            if (!cancelled) toast.error('无法读取模型 Key 状态，请检查 Redis 与后端配置');
        });
        return () => { cancelled = true; };
        // Only technical model-name changes require another Redis status request.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [modelKeysToken]);

    /** Handles add; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleAdd = () => {
        setEditingModel(undefined);
        setSourceModel(undefined);
        setShowModelForm(true);
    };

    /** Handles edit; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleEdit = (model: ModelConfig) => {
        setEditingModel(model);
        setSourceModel(undefined);
        setShowModelForm(true);
    };

    /** Handles duplicate; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleDuplicate = (model: ModelConfig) => {
        setEditingModel(undefined);
        setSourceModel(model);
        setShowModelForm(true);
    };

    /** Handles save; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSave = async (modelData: Omit<ModelConfig, 'id' | 'createdAt'>) => {
        const apiKey = modelData.apiKey.trim();
        const safeModelData = { ...modelData, apiKey: '' };
        if (editingModel) {
            if (apiKey) {
                const status = await saveModelCredential(modelData.model, {
                    apiKey,
                    sourceModel: editingModel.model,
                    legacyId: editingModel.id,
                });
                safeModelData.credentialStored = status.stored;
                safeModelData.credentialExpiresAt = status.expires_at || undefined;
            } else if (modelData.model !== editingModel.model && editingModel.credentialStored) {
                const status = await saveModelCredential(modelData.model, {
                    sourceModel: editingModel.model,
                    legacyId: editingModel.id,
                });
                safeModelData.credentialStored = status.stored;
                safeModelData.credentialExpiresAt = status.expires_at || undefined;
            } else {
                safeModelData.credentialStored = editingModel.credentialStored;
                safeModelData.credentialExpiresAt = editingModel.credentialExpiresAt;
            }
            store.updateModel(editingModel.id, safeModelData);
        } else {
            const created = store.addModel({ ...safeModelData, credentialStored: false });
            if (!created) throw new Error('无法创建模型连接');
            try {
                const status = await saveModelCredential(created.model, { apiKey, legacyId: created.id });
                store.updateModel(created.id, {
                    apiKey: '',
                    credentialStored: status.stored,
                    credentialExpiresAt: status.expires_at || undefined,
                });
            } catch (error) {
                store.deleteModel(created.id);
                throw error;
            }
        }
        setShowModelForm(false);
        setEditingModel(undefined);
        setSourceModel(undefined);
        toast.success('模型连接和 Key 已保存');
    };

    /** Handles delete; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleDelete = async (model: ModelConfig) => {
        if (window.confirm(`确认删除模型连接「${model.name}」？相关通道分配会同时清空。`)) {
            try {
                await deleteModelCredential(model.model, model.id);
                store.deleteModel(model.id);
            } catch (error) {
                toast.error('删除模型 Key 失败', { description: error instanceof Error ? error.message : undefined });
            }
        }
    };

    /** Handles clear all; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleClearAll = async () => {
        if (!window.confirm('确认清除全部模型连接和 Redis 中的 API Key？此操作无法撤销。')) return;
        const results = await Promise.allSettled(config.models.map(model => deleteModelCredential(model.model, model.id)));
        const failedIds = new Set(results.flatMap((result, index) => result.status === 'rejected' ? [config.models[index].id] : []));
        config.models.filter(model => !failedIds.has(model.id)).forEach(model => store.deleteModel(model.id));
        if (failedIds.size) toast.error(`${failedIds.size} 个模型 Key 删除失败，连接已保留`);
    };

    const smartReady = Boolean(config.models.find(model => model.id === config.smartModelId)?.credentialStored);
    const fastReady = Boolean(config.models.find(model => model.id === config.fastModelId)?.credentialStored);
    const coreReady = smartReady && fastReady;

    return (
        <>
            <Dialog open={open && !showModelForm} onOpenChange={onOpenChange}>
                <DialogContent className="flex max-h-[92vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[900px]">
                    <DialogHeader className="border-b border-slate-200 px-6 py-5 pr-12">
                        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                            <div>
                                <DialogTitle className="flex items-center gap-2 text-slate-950">
                                    <ServerCog className="h-5 w-5 text-teal-700" />
                                    模型连接与通道路由
                                </DialogTitle>
                                <DialogDescription className="mt-1.5">连接模型端点，并按后端 Smart、Fast、专家、RAG、mem0 与 MiMo 语音通道分配。</DialogDescription>
                            </div>
                            <div className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${coreReady ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>
                                {coreReady ? <CheckCircle2 className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
                                {coreReady ? '核心通道已就绪' : '需要配置 Smart 与 Fast'}
                            </div>
                        </div>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto px-6 py-5">
                        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-950">
                            <div className="flex items-start gap-2">
                                <KeyRound className="mt-0.5 h-4 w-4 shrink-0" />
                                <div>
                                    <div className="font-semibold">本地 Key 映射</div>
                                    <p className="mt-1 text-amber-900/80">模型名、端点和通道分配保存在当前浏览器；Redis 只按技术模型名保存对应的明文 API Key；默认 30 天滑动 TTL，保存、状态检查或业务使用时自动续期。前端不会重新读取或持久化 Key。</p>
                                </div>
                            </div>
                        </div>

                        <section className="mt-6">
                            <div className="flex items-center justify-between gap-4">
                                <div>
                                    <h2 className="text-sm font-semibold text-slate-950">模型连接</h2>
                                    <p className="mt-1 text-xs text-slate-500">一个连接可被多个后端通道复用。</p>
                                </div>
                                <Button size="sm" className="bg-teal-700 hover:bg-teal-800" onClick={handleAdd}>
                                    <Plus className="h-4 w-4" /> 添加连接
                                </Button>
                            </div>

                            {config.models.length === 0 ? (
                                <button type="button" onClick={handleAdd} className="mt-4 flex min-h-40 w-full flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 text-center transition hover:border-teal-400 hover:bg-teal-50/40">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-teal-700 shadow-sm"><Plus className="h-5 w-5" /></div>
                                    <div className="mt-3 text-sm font-medium text-slate-900">添加第一个模型连接</div>
                                    <div className="mt-1 text-xs text-slate-500">至少准备 Smart 与 Fast 两个通道，也可以先复用同一个连接。</div>
                                </button>
                            ) : (
                                <div className="mt-4 grid gap-3 md:grid-cols-2">
                                    {config.models.map(model => (
                                        <div key={model.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <div className="truncate text-sm font-semibold text-slate-950">{model.name}</div>
                                                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                                                        <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-medium text-teal-700">{KIND_LABEL[model.kind || 'chat']}</span>
                                                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{model.provider}</span>
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-1">
                                                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => handleDuplicate(model)} aria-label="复制连接"><Copy className="h-3.5 w-3.5" /></Button>
                                                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => handleEdit(model)} aria-label="编辑连接"><Pencil className="h-3.5 w-3.5" /></Button>
                                                    <Button variant="ghost" size="icon" className="h-8 w-8 text-red-500 hover:bg-red-50 hover:text-red-700" onClick={() => void handleDelete(model)} aria-label="删除连接"><Trash2 className="h-3.5 w-3.5" /></Button>
                                                </div>
                                            </div>
                                            <dl className="mt-4 grid gap-2 text-xs">
                                                <div className="flex justify-between gap-3"><dt className="text-slate-400">模型</dt><dd className="truncate font-mono text-slate-700">{model.model}</dd></div>
                                                <div className="flex justify-between gap-3"><dt className="text-slate-400">端点</dt><dd className="truncate text-slate-700">{safeEndpointLabel(model.baseUrl)}</dd></div>
                                                <div className="flex justify-between gap-3"><dt className="text-slate-400">Key</dt><dd className="text-slate-700">{credentialLabel(model)}</dd></div>
                                            </dl>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </section>

                        {config.models.length > 0 && (
                            <section className="mt-8">
                                <div className="mb-4">
                                    <h2 className="text-sm font-semibold text-slate-950">后端通道路由</h2>
                                    <p className="mt-1 text-xs text-slate-500">选择每类 Agent 任务实际使用的模型连接。</p>
                                </div>
                                <ModelAssignments
                                    config={config}
                                    onSetSmartModel={store.setSmartModel}
                                    onSetFastModel={store.setFastModel}
                                    onToggleReasoningPoolModel={store.toggleReasoningPoolModel}
                                    onToggleFastPoolModel={store.toggleFastPoolModel}
                                    onSetTechnicalDepthModel={store.setTechnicalDepthModel}
                                    onSetCommunicationModel={store.setCommunicationModel}
                                    onSetGeneralModel={store.setGeneralModel}
                                    onSetMatchAnalystModel={store.setMatchAnalystModel}
                                    onSetContentWriterModel={store.setContentWriterModel}
                                    onSetHrReviewerModel={store.setHrReviewerModel}
                                    onSetReflectorModel={store.setReflectorModel}
                                    onSetMimoModel={store.setMimoModel}
                                    onSetRagEmbeddingModel={store.setRagEmbeddingModel}
                                    onSetMem0LlmModel={store.setMem0LlmModel}
                                    onSetMem0EmbedderModel={store.setMem0EmbedderModel}
                                />
                            </section>
                        )}
                    </div>

                    <DialogFooter className="flex-col gap-3 border-t border-slate-200 bg-slate-50 px-6 py-4 sm:flex-row sm:justify-between">
                        <div className="text-xs leading-5 text-slate-500">Redis 仅保存“技术模型名 → API Key”，无 Hash 和 UUID；默认 30 天滑动 TTL，业务请求不发送明文 Key。</div>
                        <div className="flex gap-2">
                            {config.models.length > 0 && <Button variant="ghost" className="text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => void handleClearAll()}>清除全部连接</Button>}
                            <Button variant="outline" onClick={() => onOpenChange(false)}>完成</Button>
                        </div>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {showModelForm && (
                <ModelFormDialog
                    key={editingModel?.id || sourceModel?.id || 'new'}
                    open={showModelForm}
                    onClose={() => {
                        setShowModelForm(false);
                        setEditingModel(undefined);
                        setSourceModel(undefined);
                    }}
                    onSave={handleSave}
                    editingModel={editingModel}
                    initialValues={sourceModel ? { ...sourceModel, name: undefined } : undefined}
                />
            )}
        </>
    );
}

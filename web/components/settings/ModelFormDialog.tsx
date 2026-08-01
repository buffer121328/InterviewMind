'use client';

import { useMemo, useState } from 'react';
import {
    AlertCircle,
    CheckCircle2,
    ChevronLeft,
    ExternalLink,
    Eye,
    EyeOff,
    KeyRound,
    Loader2,
    Network,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { API_PROVIDERS, type ModelConfig } from '@/store/useInterviewStore';
import { getUserId } from '@/hooks/useUserIdentity';
import { API_BASE_URL } from '@/lib/api/config';
import { toast } from 'sonner';

interface ModelFormDialogProps {
    open: boolean;
    onClose: () => void;
    onSave: (model: Omit<ModelConfig, 'id' | 'createdAt'>) => void;
    editingModel?: ModelConfig;
    initialValues?: Partial<ModelConfig>;
}

type ModelKind = NonNullable<ModelConfig['kind']>;

/** Infers the form category from an explicit model kind or stable model-name markers, defaulting to chat when no marker is present. */
function inferKind(model?: Partial<ModelConfig>): ModelKind {
    if (model?.kind) return model.kind;
    const modelName = model?.model?.toLowerCase() || '';
    if (modelName.includes('embedding')) return 'embedding';
    if (modelName.includes('omni') || modelName.includes('audio')) return 'voice';
    return 'chat';
}

/** Merges an existing model or caller-provided draft with safe defaults used to initialize the form; it does not persist or validate credentials. */
function getInitialValues(editingModel?: ModelConfig, initialValues?: Partial<ModelConfig>) {
    const source = editingModel || initialValues;
    if (source) {
        return {
            provider: source.provider || 'openai',
            apiKey: source.apiKey || '',
            baseUrl: source.baseUrl || '',
            model: source.model || '',
            name: editingModel?.name || '',
            kind: inferKind(source),
        };
    }
    const provider = API_PROVIDERS.find(item => item.id === 'openai');
    return {
        provider: 'openai',
        apiKey: '',
        baseUrl: provider?.baseUrl || '',
        model: '',
        name: '',
        kind: 'chat' as ModelKind,
    };
}

/** Renders the model form dialog UI and coordinates its typed props, local state, and approved backend interactions. */
export function ModelFormDialog({ open, onClose, onSave, editingModel, initialValues }: ModelFormDialogProps) {
    const [initial] = useState(() => getInitialValues(editingModel, initialValues));
    const [provider, setProvider] = useState(initial.provider);
    const [kind, setKind] = useState<ModelKind>(initial.kind);
    const [apiKey, setApiKey] = useState(initial.apiKey);
    const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
    const [model, setModel] = useState(initial.model);
    const [name, setName] = useState(initial.name);
    const [showApiKey, setShowApiKey] = useState(false);
    const [isTesting, setIsTesting] = useState(false);
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
    const [testedFingerprint, setTestedFingerprint] = useState<string | null>(null);

    const providerConfig = API_PROVIDERS.find(item => item.id === provider);
    const fingerprint = [provider, kind, apiKey, baseUrl, model].join('\u0000');
    const currentTestResult = testedFingerprint === fingerprint ? testResult : null;
    const canSave = Boolean(apiKey.trim() && baseUrl.trim() && model.trim());
    const suggestedModels = useMemo(() => providerConfig?.models || [], [providerConfig]);

    /** Handles provider change; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleProviderChange = (providerId: string) => {
        const next = API_PROVIDERS.find(item => item.id === providerId);
        setProvider(providerId);
        setBaseUrl(next?.baseUrl || '');
        setModel('');
    };

    /** Handles test connection; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleTestConnection = async () => {
        if (!canSave) {
            setTestResult({ success: false, message: '请先填写 API Key、Base URL 和模型名称。' });
            setTestedFingerprint(fingerprint);
            return;
        }

        setIsTesting(true);
        setTestResult(null);
        setTestedFingerprint(null);
        try {
            const response = await fetch(`${API_BASE_URL}/api/config/validate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-ID': getUserId(),
                },
                body: JSON.stringify({
                    api_key: apiKey.trim(),
                    base_url: baseUrl.trim(),
                    model: model.trim(),
                    kind: kind === 'embedding' ? 'embedding' : 'chat',
                }),
            });
            const data = await response.json().catch(() => ({}));
            const result = {
                success: Boolean(response.ok && data.success),
                message: data.message || (response.ok ? '连接验证通过。' : `验证失败（HTTP ${response.status}）。`),
            };
            setTestResult(result);
            setTestedFingerprint(fingerprint);
            if (result.success) toast.success('模型连接验证通过');
            else toast.error('模型连接验证失败', { description: result.message });
        } catch {
            const result = { success: false, message: '无法连接后端验证接口，请检查服务状态与网络。' };
            setTestResult(result);
            setTestedFingerprint(fingerprint);
            toast.error('连接验证失败', { description: result.message });
        } finally {
            setIsTesting(false);
        }
    };

    /** Handles save; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSave = () => {
        if (!canSave) return;
        const displayName = name.trim() || `${providerConfig?.name || '自定义'} · ${model.trim()}`;
        onSave({
            name: displayName,
            provider,
            kind,
            apiKey: apiKey.trim(),
            baseUrl: baseUrl.trim().replace(/\/+$/, ''),
            model: model.trim(),
        });
        onClose();
    };

    return (
        <Dialog open={open} onOpenChange={nextOpen => !nextOpen && onClose()}>
            <DialogContent className="flex max-h-[92vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[620px]">
                <DialogHeader className="border-b border-slate-200 px-6 py-5 pr-12">
                    <DialogTitle className="flex items-center gap-2 text-slate-950">
                        <button type="button" onClick={onClose} className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900" aria-label="返回">
                            <ChevronLeft className="h-5 w-5" />
                        </button>
                        {editingModel ? '编辑模型连接' : '添加模型连接'}
                    </DialogTitle>
                    <DialogDescription className="pl-8">填写一个 OpenAI-compatible 模型端点，并在保存前验证连接。</DialogDescription>
                </DialogHeader>

                <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
                        <div className="flex items-start gap-2">
                            <KeyRound className="mt-0.5 h-4 w-4 shrink-0" />
                            <p>Key 只保留在当前页面内存中，刷新或关闭页面后需重新输入；执行任务时会随请求发送给后端。公网部署必须使用 HTTPS。</p>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <label className="text-sm font-medium text-slate-800">提供商预设</label>
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                            {API_PROVIDERS.map(item => (
                                <button
                                    type="button"
                                    key={item.id}
                                    onClick={() => handleProviderChange(item.id)}
                                    className={cn(
                                        'rounded-lg border px-3 py-2 text-xs transition',
                                        provider === item.id
                                            ? 'border-teal-600 bg-teal-50 font-medium text-teal-800'
                                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
                                    )}
                                >
                                    {item.name}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="space-y-3">
                        <label className="text-sm font-medium text-slate-800">模型类型</label>
                        <div className="grid grid-cols-3 gap-2">
                            {([
                                ['chat', '文本 / 推理'],
                                ['embedding', 'Embedding'],
                                ['voice', '语音 Omni'],
                            ] as const).map(([value, label]) => (
                                <button
                                    type="button"
                                    key={value}
                                    onClick={() => setKind(value)}
                                    className={cn(
                                        'rounded-lg border px-3 py-2 text-xs transition',
                                        kind === value
                                            ? 'border-teal-600 bg-teal-50 font-medium text-teal-800'
                                            : 'border-slate-200 text-slate-600 hover:border-slate-300',
                                    )}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="grid gap-5 sm:grid-cols-2">
                        <label className="space-y-2 sm:col-span-2">
                            <span className="text-sm font-medium text-slate-800">API Key</span>
                            <span className="relative block">
                                <input
                                    type={showApiKey ? 'text' : 'password'}
                                    value={apiKey}
                                    onChange={event => setApiKey(event.target.value)}
                                    autoComplete="new-password"
                                    name="model-api-key"
                                    placeholder="输入当前提供商的 API Key"
                                    className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 pr-11 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                                />
                                <button type="button" onClick={() => setShowApiKey(value => !value)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700" aria-label={showApiKey ? '隐藏 Key' : '显示 Key'}>
                                    {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                            </span>
                            {providerConfig?.apiKeyUrl && (
                                <a href={providerConfig.apiKeyUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-teal-700 hover:underline">
                                    打开 {providerConfig.name} 官方密钥页 <ExternalLink className="h-3 w-3" />
                                </a>
                            )}
                        </label>

                        <label className="space-y-2 sm:col-span-2">
                            <span className="text-sm font-medium text-slate-800">Base URL</span>
                            <input
                                value={baseUrl}
                                onChange={event => setBaseUrl(event.target.value)}
                                placeholder="https://provider.example/v1"
                                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 font-mono text-xs outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                            />
                        </label>

                        <label className="space-y-2">
                            <span className="text-sm font-medium text-slate-800">模型名称</span>
                            <input
                                value={model}
                                onChange={event => setModel(event.target.value)}
                                list="provider-model-suggestions"
                                placeholder={kind === 'embedding' ? '例如 text-embedding-v4' : kind === 'voice' ? '例如 qwen3-omni-flash-2025-12-01' : '填写提供商模型 ID'}
                                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                            />
                            <datalist id="provider-model-suggestions">
                                {suggestedModels.map(item => <option key={item} value={item} />)}
                            </datalist>
                        </label>

                        <label className="space-y-2">
                            <span className="text-sm font-medium text-slate-800">连接名称（可选）</span>
                            <input
                                value={name}
                                onChange={event => setName(event.target.value)}
                                placeholder="例如 主推理模型"
                                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                            />
                        </label>
                    </div>

                    {currentTestResult && (
                        <div className={cn(
                            'flex items-start gap-2 rounded-xl border p-3 text-sm',
                            currentTestResult.success
                                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                                : 'border-red-200 bg-red-50 text-red-800',
                        )}>
                            {currentTestResult.success ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                            {currentTestResult.message}
                        </div>
                    )}
                </div>

                <DialogFooter className="border-t border-slate-200 bg-slate-50 px-6 py-4">
                    <Button variant="outline" onClick={handleTestConnection} disabled={!canSave || isTesting}>
                        {isTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
                        验证连接
                    </Button>
                    <Button className="bg-teal-700 hover:bg-teal-800" onClick={handleSave} disabled={!canSave}>
                        保存连接
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

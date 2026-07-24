'use client';

import { useState } from 'react';
import { AlertCircle, Award, Check, ChevronLeft, Eye, EyeOff, HelpCircle, Loader2 } from 'lucide-react';
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

// 添加/编辑模型的二级弹窗
interface ModelFormDialogProps {
    open: boolean;
    onClose: () => void;
    onSave: (model: Omit<ModelConfig, 'id' | 'createdAt'>) => void;
    editingModel?: ModelConfig;
    initialValues?: Partial<ModelConfig>;
}

function getInitialModelFormValues(
    editingModel?: ModelConfig,
    initialValues?: Partial<ModelConfig>
) {
    if (editingModel) {
        return {
            provider: editingModel.provider,
            apiKey: editingModel.apiKey,
            baseUrl: editingModel.baseUrl,
            model: editingModel.model,
            name: editingModel.name,
        };
    }

    if (initialValues) {
        return {
            provider: initialValues.provider || '',
            apiKey: initialValues.apiKey || '',
            baseUrl: initialValues.baseUrl || '',
            model: initialValues.model || '',
            name: '',
        };
    }

    const defaultProvider = 'aiping';
    const providerConfig = API_PROVIDERS.find((item) => item.id === defaultProvider);
    return {
        provider: defaultProvider,
        apiKey: '',
        baseUrl: providerConfig?.baseUrl || '',
        model: providerConfig?.models[0] || '',
        name: '',
    };
}

export function ModelFormDialog({ open, onClose, onSave, editingModel, initialValues }: ModelFormDialogProps) {
    const [initialFormValues] = useState(() => getInitialModelFormValues(editingModel, initialValues));
    const [provider, setProvider] = useState(initialFormValues.provider);
    const [apiKey, setApiKey] = useState(initialFormValues.apiKey);
    const [baseUrl, setBaseUrl] = useState(initialFormValues.baseUrl);
    const [model, setModel] = useState(initialFormValues.model);
    const [name, setName] = useState(initialFormValues.name);
    const [showApiKey, setShowApiKey] = useState(false);
    const [isTesting, setIsTesting] = useState(false);
    const [showTutorial, setShowTutorial] = useState(false);
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
    const [testedConfiguration, setTestedConfiguration] = useState<string | null>(null);
    const modelKind = model.toLowerCase().includes('embedding') ? 'embedding' : 'chat';
    const configuration = [provider, apiKey, baseUrl, model, modelKind].join('\u0000');
    const currentTestResult = testedConfiguration === configuration ? testResult : null;

    // 选择提供商
    const handleProviderChange = (providerId: string) => {
        setProvider(providerId);
        const providerConfig = API_PROVIDERS.find(p => p.id === providerId);
        if (providerConfig) {
            setBaseUrl(providerConfig.baseUrl);
            if (providerConfig.models.length > 0) {
                setModel(providerConfig.models[0]);
            } else {
                setModel('');
            }
        }
    };

    // 测试连接
    const handleTestConnection = async () => {
        if (!apiKey || !baseUrl || !model) {
            setTestResult({ success: false, message: '请先填写完整的配置信息' });
            setTestedConfiguration(configuration);
            return;
        }

        setIsTesting(true);
        setTestResult(null);
        setTestedConfiguration(null);

        try {
            const response = await fetch(`${API_BASE_URL}/api/config/validate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-ID': getUserId()
                },
                body: JSON.stringify({
                    api_key: apiKey,
                    base_url: baseUrl,
                    model: model,
                    kind: modelKind
                })
            });

            const data = await response.json();
            const result = {
                success: data.success,
                message: data.message || (data.success ? '连接成功！' : '连接失败')
            };
            setTestResult(result);
            setTestedConfiguration(configuration);

            if (data.success) {
                toast.success('连接成功！', {
                    description: '您的 API 配置已验证通过'
                });
            } else {
                toast.error('连接失败', {
                    description: result.message
                });
            }
        } catch {
            const message = '无法连接到服务器，请检查网络';
            setTestResult({
                success: false,
                message
            });
            setTestedConfiguration(configuration);
            toast.error('连接错误', {
                description: message
            });
        } finally {
            setIsTesting(false);
        }
    };

    // 保存
    const handleSave = () => {
        const providerConfig = API_PROVIDERS.find(p => p.id === provider);
        const configName = name || `${providerConfig?.name || '自定义'} - ${model}`;

        onSave({
            name: configName,
            provider,
            apiKey,
            baseUrl,
            model
        });
        onClose();
    };

    const currentProvider = API_PROVIDERS.find(p => p.id === provider);
    const canSave = apiKey && baseUrl && model;

    return (
        <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
            <DialogContent className="sm:max-w-[500px] max-h-[90vh] p-0 flex flex-col gap-0 overflow-hidden">
                <DialogHeader className="p-6 pb-4 border-b">
                    <div className="flex items-center justify-between">
                        <DialogTitle className="flex items-center gap-2">
                            <ChevronLeft className="w-5 h-5 cursor-pointer hover:text-orange-600" onClick={onClose} />
                            {editingModel ? '编辑模型配置' : '添加模型配置'}
                        </DialogTitle>
                        <button
                            onClick={() => setShowTutorial(!showTutorial)}
                            className="flex items-center gap-1 text-xs text-orange-600 hover:text-orange-700 font-medium bg-orange-50 px-2 py-1 rounded-md transition-colors"
                        >
                            <HelpCircle className="w-3.5 h-3.5" />
                            教程
                        </button>
                    </div>
                    <DialogDescription>
                        配置大模型 API，数据仅保存在本地浏览器中
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto p-6">
                    <div className="space-y-5">
                        {/* 配置教程面板 */}
                        {showTutorial && (
                            <div className="mb-5 p-4 rounded-xl border border-orange-100 bg-orange-50/40 space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
                                <div className="flex items-center gap-2 text-sm font-bold text-orange-800">
                                    <Award className="w-4 h-4 text-orange-500" /> 快速配置建议
                                </div>
                                <div className="space-y-2 text-[11px] text-orange-700 leading-relaxed">
                                    <p>1. <strong>获取福利：</strong> 推荐使用 <a href="https://www.aiping.cn/#?invitation_code=SJY0NW" target="_blank" className="underline font-bold text-orange-600 font-bold underline">AI Ping</a> 注册，输入邀请码 <b>SJY0NW</b> 可领 <b>20元</b> 奖励。</p>
                                    <p>2. <strong>填写说明：</strong> 选择提供商后会自动填入 Base URL。你只需要粘贴你的 <b>API Key</b> ，并选择模型配置即可。</p>
                                    <p>3. <strong>测试连接：</strong> 保存前请务必点击底部的“测试连接”，确保配置有效。</p>
                                </div>
                            </div>
                        )}
                        {/* API 提供商 */}
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">
                                API 提供商
                            </label>
                            <div className="grid grid-cols-3 gap-2">
                                {API_PROVIDERS.map((p) => (
                                    <button
                                        key={p.id}
                                        onClick={() => handleProviderChange(p.id)}
                                        className={cn(
                                            "px-3 py-2 text-sm rounded-lg border transition-all",
                                            provider === p.id
                                                ? "border-orange-500 bg-orange-50 text-orange-700 font-medium"
                                                : "border-gray-200 hover:border-gray-300 text-gray-600"
                                        )}
                                    >
                                        {p.name}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* API Key */}
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">
                                API Key <span className="text-red-500">*</span>
                            </label>
                            <div className="relative">
                                <input
                                    type={showApiKey ? 'text' : 'password'}
                                    value={apiKey}
                                    onChange={(e) => setApiKey(e.target.value)}
                                    autoComplete="new-password"
                                    name="api-key-field"
                                    className="w-full rounded-lg border border-gray-200 px-4 py-2.5 pr-12 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none"
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowApiKey(!showApiKey)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                                >
                                    {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                </button>
                            </div>
                            {currentProvider?.apiKeyUrl ? (
                                <p className="text-xs text-orange-600">
                                    <a
                                        href={currentProvider.apiKeyUrl}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="hover:underline inline-flex items-center gap-1"
                                    >
                                        → 点击获取 {currentProvider.name} API Key
                                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                        </svg>
                                    </a>
                                </p>
                            ) : (
                                <p className="text-xs text-gray-400">
                                    您的 API Key 仅保存在浏览器本地，不会上传到服务器
                                </p>
                            )}
                        </div>

                        {/* Base URL */}
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">
                                Base URL <span className="text-red-500">*</span>
                            </label>
                            <input
                                type="text"
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                className="w-full rounded-lg border border-gray-200 px-4 py-2.5 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none"
                                placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                            />
                        </div>

                        {/* 模型配置 */}
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">
                                模型配置 <span className="text-red-500">*</span>
                            </label>
                            {currentProvider && currentProvider.models.length > 0 ? (
                                <select
                                    value={model}
                                    onChange={(e) => setModel(e.target.value)}
                                    className="w-full rounded-lg border border-gray-200 px-4 py-2.5 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                                >
                                    <option value="">选择模型</option>
                                    {currentProvider.models.map((m) => (
                                        <option key={m} value={m}>{m}</option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    type="text"
                                    value={model}
                                    onChange={(e) => setModel(e.target.value)}
                                    className="w-full rounded-lg border border-gray-200 px-4 py-2.5 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none"
                                    placeholder="输入模型名称，如 deepseek-v4-flash 或 text-embedding-v4"
                                />
                            )}
                        </div>

                        {/* 配置名称（可选） */}
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">
                                配置名称 <span className="text-gray-400 text-xs">（可选）</span>
                            </label>
                            <input
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                autoComplete="off"
                                name="config-name-field"
                                className="w-full rounded-lg border border-gray-200 px-4 py-2.5 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none"
                            />
                        </div>

                        {/* 测试连接结果 - 只在失败时显示 Banner，成功则直接体现在按钮上 */}
                        {currentTestResult && !currentTestResult.success && (
                            <div className={cn(
                                "flex items-center gap-2 p-3 rounded-lg text-sm bg-red-50 text-red-700 border border-red-200 animate-in fade-in slide-in-from-top-1"
                            )}>
                                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                                {currentTestResult.message}
                            </div>
                        )}
                    </div>
                </div>

                <DialogFooter className="p-6 pt-4 border-t bg-gray-50/50 flex-col sm:flex-row gap-2">
                    {!currentTestResult && (
                        <div className="flex items-center gap-2 px-1 pb-2">
                            <span className="relative flex h-2 w-2">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75"></span>
                                <span className="relative inline-flex rounded-full h-2 w-2 bg-orange-500"></span>
                            </span>
                            <p className="text-xs text-orange-600 font-medium">请先测试连接，确保配置可用</p>
                        </div>
                    )}
                    <Button
                        variant="outline"
                        onClick={handleTestConnection}
                        disabled={isTesting || !canSave}
                        className={cn(
                            "flex-1 sm:flex-none transition-all duration-300",
                            currentTestResult?.success
                                ? "border-green-200 text-green-700 bg-green-50 hover:bg-green-100 hover:text-green-800 hover:border-green-300"
                                : "border-orange-200 text-orange-700 bg-orange-50 hover:bg-orange-100 hover:text-orange-800 hover:border-orange-300"
                        )}
                    >
                        {isTesting ? (
                            <>
                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                测试中...
                            </>
                        ) : currentTestResult?.success ? (
                            <>
                                <Check className="w-4 h-4 mr-2" />
                                连接成功
                            </>
                        ) : (
                            '测试连接'
                        )}
                    </Button>
                    <div className="flex gap-2 flex-1 sm:flex-none">
                        <Button variant="outline" onClick={onClose} className="flex-1">
                            取消
                        </Button>
                        <Button
                            onClick={handleSave}
                            disabled={!canSave}
                            className="flex-1 bg-orange-600 hover:bg-orange-700"
                        >
                            保存
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

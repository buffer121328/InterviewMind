import { AlertCircle, Brain, Check, CheckCircle, ChevronDown, FileText, PenTool, UserCheck, Users, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ApiConfig } from '@/store/types';

interface ModelAssignmentsProps {
    config: ApiConfig;
    onSetSmartModel: (id: string) => boolean;
    onSetFastModel: (id: string) => boolean;
    onToggleReasoningPoolModel: (id: string) => boolean;
    onToggleFastPoolModel: (id: string) => boolean;
    onSetGeneralModel: (id: string) => boolean;
    onSetMatchAnalystModel: (id: string) => boolean;
    onSetContentWriterModel: (id: string) => boolean;
    onSetHrReviewerModel: (id: string) => boolean;
    onSetReflectorModel: (id: string) => boolean;
    onSetVoiceModel: (id: string) => boolean;
}

export function ModelAssignments({
    config,
    onSetSmartModel,
    onSetFastModel,
    onToggleReasoningPoolModel,
    onToggleFastPoolModel,
    onSetGeneralModel,
    onSetMatchAnalystModel,
    onSetContentWriterModel,
    onSetHrReviewerModel,
    onSetReflectorModel,
    onSetVoiceModel,
}: ModelAssignmentsProps) {
    return (
        <>
{/* 模型配置区域 - 下拉选择 */}
{config.models.length > 0 && (
    <>
        <div className="p-4 rounded-xl border border-gray-200 bg-gray-50/50 space-y-4">
            <label className="text-sm font-medium text-gray-700">面试功能模型配置</label>

            {/* Smart 通道选择 */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <Brain className="w-4 h-4 text-purple-500" />
                    Smart
                    <span className="text-xs text-gray-400">（复杂任务：规划、总结，推荐 Qwen3-Max ）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.smartModelId}
                        onChange={(e) => onSetSmartModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
                <div className="space-y-2 pt-1">
                    <div className="text-xs font-medium text-gray-500">Reasoning Pool（空时使用 Smart）</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {config.models.map((model) => {
                            const selected = (config.reasoningPoolModelIds || []).includes(model.id);
                            return (
                                <button
                                    type="button"
                                    key={model.id}
                                    onClick={() => onToggleReasoningPoolModel(model.id)}
                                    className={cn(
                                        "flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                                        selected
                                            ? "border-purple-300 bg-purple-50 text-purple-700"
                                            : "border-gray-200 bg-white text-gray-600 hover:border-purple-200"
                                    )}
                                >
                                    <span className={cn(
                                        "flex h-4 w-4 items-center justify-center rounded border",
                                        selected ? "border-purple-500 bg-purple-500 text-white" : "border-gray-300"
                                    )}>
                                        {selected && <Check className="h-3 w-3" />}
                                    </span>
                                    <span className="truncate">{model.name}</span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Fast 通道选择 */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <Zap className="w-4 h-4 text-amber-500" />
                    Fast
                    <span className="text-xs text-gray-400">（快速响应：问答、点评，推荐 MiMo-V2-Flash/ DeepSeek-V3.2）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.fastModelId}
                        onChange={(e) => onSetFastModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
                <div className="space-y-2 pt-1">
                    <div className="text-xs font-medium text-gray-500">Fast Pool（空时使用 Fast）</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {config.models.map((model) => {
                            const selected = (config.fastPoolModelIds || []).includes(model.id);
                            return (
                                <button
                                    type="button"
                                    key={model.id}
                                    onClick={() => onToggleFastPoolModel(model.id)}
                                    className={cn(
                                        "flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                                        selected
                                            ? "border-amber-300 bg-amber-50 text-amber-700"
                                            : "border-gray-200 bg-white text-gray-600 hover:border-amber-200"
                                    )}
                                >
                                    <span className={cn(
                                        "flex h-4 w-4 items-center justify-center rounded border",
                                        selected ? "border-amber-500 bg-amber-500 text-white" : "border-gray-300"
                                    )}>
                                        {selected && <Check className="h-3 w-3" />}
                                    </span>
                                    <span className="truncate">{model.name}</span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>

        {/* 简历工具专家模型配置 */}
        <div className="p-4 rounded-xl border border-gray-200 bg-gray-50/50 space-y-4">
            <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                <FileText className="w-4 h-4 text-orange-600" />
                简历工具模型配置
            </label>

            <div className="flex items-start gap-2 p-3 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <p>注意：魔搭免费模型存在并发限制，匹配分析师、内容优化师、HR审核官只允许一个配置免费模型。deepseekv3.2与deepseekchat是同一模型</p>
            </div>

            {/* 通用任务（简历分析 + 主持人） */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <Brain className="w-4 h-4 text-indigo-500" />
                    通用任务
                    <span className="text-xs text-gray-400">（简历分析、主持人，推荐Qwen3-Max）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.generalModelId || ''}
                        onChange={(e) => onSetGeneralModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
            </div>

            {/* 匹配分析师 */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <Users className="w-4 h-4 text-blue-500" />
                    匹配分析师
                    <span className="text-xs text-gray-400">（JD关键词匹配，推荐Qwen3-Max/DeepSeek-V3.2）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.matchAnalystModelId || ''}
                        onChange={(e) => onSetMatchAnalystModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
            </div>

            {/* 内容优化师 */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <PenTool className="w-4 h-4 text-green-500" />
                    内容优化师
                    <span className="text-xs text-gray-400">（内容重写建议，推荐 DeepSeek-V3.2 / GLM-4.7）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.contentWriterModelId || ''}
                        onChange={(e) => onSetContentWriterModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
            </div>

            {/* HR审核官 */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <UserCheck className="w-4 h-4 text-orange-500" />
                    HR审核官
                    <span className="text-xs text-gray-400">（模拟HR筛选，推荐 GLM-4.7 / DeepSeek-V3.2）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.hrReviewerModelId || ''}
                        onChange={(e) => onSetHrReviewerModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
            </div>

            {/* 质量审核 */}
            <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-gray-600">
                    <CheckCircle className="w-4 h-4 text-purple-500" />
                    质量审核
                    <span className="text-xs text-gray-400">（质量检查，推荐kimi-k2/MiMo-V2-Flash）</span>
                </label>
                <div className="relative">
                    <select
                        value={config.reflectorModelId || ''}
                        onChange={(e) => onSetReflectorModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name}
                            </option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
            </div>
        </div>

        {/* 语音面试 */}
        <div className="p-3 bg-purple-50 rounded-lg border border-purple-100">
            <h4 className="text-sm font-medium text-purple-800 mb-2">🎤 语音面试</h4>
            <div className="space-y-2">
                <label className="text-xs text-gray-600">语音模型 (必须选择 Qwen3-Omni)</label>
                <div className="relative">
                    <select
                        value={config.voiceModelId || ''}
                        onChange={(e) => onSetVoiceModel(e.target.value)}
                        className="w-full appearance-none rounded-lg border border-gray-200 px-4 py-2.5 pr-10 text-sm focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none bg-white"
                    >
                        <option value="">选择模型</option>
                        {config.models
                            .filter(m => m.model === 'qwen3-omni-flash-2025-12-01')
                            .map((model) => (
                                <option key={model.id} value={model.id}>
                                    {model.name}
                                </option>
                            ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
                <p className="text-xs text-purple-600 font-medium mt-1.5 flex items-center gap-1.5">
                    <AlertCircle className="w-3 h-3" />
                    语音功能仅支持：qwen3-omni-flash-2025-12-01
                </p>
            </div>
        </div>
    </>
)}
        </>
    );
}

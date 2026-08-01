'use client';

import {
    AudioLines,
    BrainCircuit,
    Check,
    Database,
    FileText,
    Gauge,
    Network,
    ShieldCheck,
    Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ApiConfig, ModelConfig } from '@/store/useInterviewStore';

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
    onSetMimoModel: (id: string) => boolean;
    onSetRagEmbeddingModel: (id: string) => boolean;
    onSetMem0LlmModel: (id: string) => boolean;
    onSetMem0EmbedderModel: (id: string) => boolean;
}

/** Encapsulates model select; returns typed data or state and keeps side effects within the owning module boundary. */
function ModelSelect({
    label,
    description,
    value,
    models,
    onChange,
    required = false,
}: {
    label: string;
    description: string;
    value: string;
    models: ModelConfig[];
    onChange: (id: string) => boolean;
    required?: boolean;
}) {
    return (
        <label className="grid gap-2">
            <span className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-slate-800">{label}</span>
                {required && <span className="rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-medium text-teal-700">必需</span>}
            </span>
            <span className="text-xs leading-5 text-slate-500">{description}</span>
            <select
                value={value || ''}
                onChange={event => onChange(event.target.value)}
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            >
                <option value="">{required ? '请选择模型连接' : '未单独配置（使用默认回退）'}</option>
                {models.map(model => (
                    <option key={model.id} value={model.id}>{model.name}</option>
                ))}
            </select>
        </label>
    );
}

/** Encapsulates pool picker; returns typed data or state and keeps side effects within the owning module boundary. */
function PoolPicker({
    title,
    description,
    models,
    selectedIds,
    onToggle,
}: {
    title: string;
    description: string;
    models: ModelConfig[];
    selectedIds: string[];
    onToggle: (id: string) => boolean;
}) {
    return (
        <div className="space-y-2">
            <div className="text-sm font-medium text-slate-800">{title}</div>
            <p className="text-xs leading-5 text-slate-500">{description}</p>
            <div className="grid gap-2 sm:grid-cols-2">
                {models.map(model => {
                    const selected = selectedIds.includes(model.id);
                    return (
                        <button
                            type="button"
                            key={model.id}
                            onClick={() => onToggle(model.id)}
                            className={cn(
                                'flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition',
                                selected
                                    ? 'border-teal-300 bg-teal-50 text-teal-800'
                                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
                            )}
                        >
                            <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border', selected ? 'border-teal-600 bg-teal-600 text-white' : 'border-slate-300')}>
                                {selected && <Check className="h-3 w-3" />}
                            </span>
                            <span className="truncate">{model.name}</span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}

/** Encapsulates section; returns typed data or state and keeps side effects within the owning module boundary. */
function Section({
    icon: Icon,
    title,
    description,
    children,
}: {
    icon: typeof BrainCircuit;
    title: string;
    description: string;
    children: React.ReactNode;
}) {
    return (
        <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5">
            <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-950 text-teal-100">
                    <Icon className="h-4 w-4" />
                </div>
                <div>
                    <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
                </div>
            </div>
            <div className="mt-5 grid gap-5">{children}</div>
        </section>
    );
}

/** Encapsulates model assignments; returns typed data or state and keeps side effects within the owning module boundary. */
export function ModelAssignments(props: ModelAssignmentsProps) {
    const { config } = props;
    if (config.models.length === 0) return null;

    const chatModels = config.models.filter(model => (model.kind || 'chat') === 'chat');
    const embeddingModels = config.models.filter(model => model.kind === 'embedding' || model.model.toLowerCase().includes('embedding'));
    const mimoModels = config.models.filter(model => model.provider === 'mimo');
    const primaryModels = chatModels.length > 0 ? chatModels : config.models;
    const embeddingOptions = embeddingModels.length > 0 ? embeddingModels : config.models;

    return (
        <div className="space-y-4">
            <Section
                icon={Gauge}
                title="核心执行与模型池"
                description="Smart 负责规划、总结等复杂任务；Fast 负责高频问答。模型池为空时，后端回退到对应单模型。"
            >
                <div className="grid gap-5 md:grid-cols-2">
                    <ModelSelect label="Smart 通道" description="复杂推理、面试规划与报告生成。" value={config.smartModelId} models={primaryModels} onChange={props.onSetSmartModel} required />
                    <ModelSelect label="Fast 通道" description="实时问答、短反馈与低延迟任务。" value={config.fastModelId} models={primaryModels} onChange={props.onSetFastModel} required />
                </div>
                <div className="grid gap-5 md:grid-cols-2">
                    <PoolPicker title="Reasoning Pool" description="用于推理任务的加权成员；后端负责调度、冷却和回退。" models={primaryModels} selectedIds={config.reasoningPoolModelIds || []} onToggle={props.onToggleReasoningPoolModel} />
                    <PoolPicker title="Fast Pool" description="用于快速任务的加权成员；未选择时使用 Fast 通道。" models={primaryModels} selectedIds={config.fastPoolModelIds || []} onToggle={props.onToggleFastPoolModel} />
                </div>
            </Section>

            <Section
                icon={Users}
                title="简历专家通道"
                description="为多 Agent 简历工作流分配独立模型。任何未配置通道都会由后端回退到 Smart。"
            >
                <div className="grid gap-5 md:grid-cols-2">
                    <ModelSelect label="通用 / 主持人" description="简历分析、流程主持与结果汇总。" value={config.generalModelId} models={primaryModels} onChange={props.onSetGeneralModel} />
                    <ModelSelect label="JD 匹配分析师" description="岗位要求拆解、关键词和差距分析。" value={config.matchAnalystModelId} models={primaryModels} onChange={props.onSetMatchAnalystModel} />
                    <ModelSelect label="内容优化师" description="项目经历改写和定向优化建议。" value={config.contentWriterModelId} models={primaryModels} onChange={props.onSetContentWriterModel} />
                    <ModelSelect label="HR 审核官" description="招聘筛选视角、风险和真实性边界。" value={config.hrReviewerModelId} models={primaryModels} onChange={props.onSetHrReviewerModel} />
                    <ModelSelect label="质量审核" description="检查结构、完整性与多 Agent 结果一致性。" value={config.reflectorModelId} models={primaryModels} onChange={props.onSetReflectorModel} />
                </div>
            </Section>

            <Section
                icon={Database}
                title="RAG 与长期记忆"
                description="这些通道会随相关请求发送给后端；未配置时仅使用服务端已经存在的兜底配置。"
            >
                <div className="grid gap-5 md:grid-cols-2">
                    <ModelSelect label="RAG Embedding" description="题库、面经和候选人资料的向量检索。" value={config.ragEmbeddingModelId} models={embeddingOptions} onChange={props.onSetRagEmbeddingModel} />
                    <ModelSelect label="mem0 提取 LLM" description="从面试对话中提取可复用长期记忆。" value={config.mem0LlmModelId} models={primaryModels} onChange={props.onSetMem0LlmModel} />
                    <ModelSelect label="mem0 Embedding" description="长期记忆的语义检索。" value={config.mem0EmbedderModelId} models={embeddingOptions} onChange={props.onSetMem0EmbedderModel} />
                </div>
            </Section>

            <Section
                icon={AudioLines}
                title="语音面试"
                description="语音统一走 MiMo ASR、文本对话与 TTS 拆分链路，不回退到其他语音模型。"
            >
                <ModelSelect label="小米 MiMo" description="Key 随当前请求发送，后端固定调用 mimo-v2.5-asr、mimo-v2.5 与 mimo-v2.5-tts。" value={config.mimoModelId} models={mimoModels} onChange={props.onSetMimoModel} required />
            </Section>

            <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-xs leading-5 text-slate-600 sm:grid-cols-3">
                <span className="flex items-start gap-2"><Network className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />后端统一做超时、URL 校验、冷却与 fallback。</span>
                <span className="flex items-start gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />通道路由不会绕过工具权限或外部动作审批。</span>
                <span className="flex items-start gap-2"><FileText className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />模型连接名仅用于本地识别和运行观测。</span>
            </div>
        </div>
    );
}

'use client';

import { useState, useEffect } from 'react';
import { Settings, Plus, Copy, HelpCircle, ExternalLink, Key, Award } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { ModelConfig, API_PROVIDERS, useInterviewStore } from '@/store/useInterviewStore';

import { ModelFormDialog } from './settings/ModelFormDialog';
import { ModelAssignments } from './settings/ModelAssignments';

interface SettingsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

// 主设置弹窗
export function SettingsDialog({
    open,
    onOpenChange
}: SettingsDialogProps) {
    const {
        apiConfig: config,
        addModel: onAddModel,
        updateModel: onUpdateModel,
        deleteModel: onDeleteModel,
        setSmartModel: onSetSmartModel,
        setFastModel: onSetFastModel,
        toggleReasoningPoolModel: onToggleReasoningPoolModel,
        toggleFastPoolModel: onToggleFastPoolModel,
        // 简历工具专家模型
        setGeneralModel: onSetGeneralModel,
        setMatchAnalystModel: onSetMatchAnalystModel,
        setContentWriterModel: onSetContentWriterModel,
        setHrReviewerModel: onSetHrReviewerModel,
        setReflectorModel: onSetReflectorModel,
        setVoiceModel: onSetVoiceModel
    } = useInterviewStore();
    const [showModelForm, setShowModelForm] = useState(false);
    const [showTutorial, setShowTutorial] = useState(false);
    const [editingModel, setEditingModel] = useState<ModelConfig | undefined>();
    const [sourceModel, setSourceModel] = useState<ModelConfig | undefined>();

    // 当没有配置任何模型时，默认开启教程
    useEffect(() => {
        if (!open || config.models.length !== 0) return;

        const timer = window.setTimeout(() => setShowTutorial(true), 0);
        return () => window.clearTimeout(timer);
    }, [open, config.models.length]);

    // 打开添加模型弹窗
    const handleAddModel = () => {
        setEditingModel(undefined);
        setSourceModel(undefined);
        setShowModelForm(true);
    };

    // 复制模型配置
    const handleDuplicateModel = (model: ModelConfig, e: React.MouseEvent) => {
        e.stopPropagation();
        setSourceModel(model);
        setEditingModel(undefined);
        setShowModelForm(true);
    };

    // 打开编辑模型弹窗
    const handleEditModel = (model: ModelConfig) => {
        setEditingModel(model);
        setShowModelForm(true);
    };

    // 保存模型配置
    const handleSaveModel = (modelData: Omit<ModelConfig, 'id' | 'createdAt'>) => {
        if (editingModel) {
            onUpdateModel(editingModel.id, modelData);
        } else {
            onAddModel(modelData);
        }
        setShowModelForm(false);
        setEditingModel(undefined);
    };

    // 删除模型
    const handleDeleteModel = (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        if (confirm('确定要删除这个模型配置吗？')) {
            onDeleteModel(id);
        }
    };

    return (
        <>
            <Dialog open={open && !showModelForm} onOpenChange={onOpenChange}>
                <DialogContent className="sm:max-w-[550px] max-h-[90vh] p-0 flex flex-col gap-0 overflow-hidden">
                    <DialogHeader className="p-6 pb-4 border-b">
                        <div className="flex items-center justify-between">
                            <DialogTitle className="flex items-center gap-2">
                                <Settings className="w-5 h-5 text-orange-600" />
                                API 设置
                            </DialogTitle>
                            <button
                                onClick={() => setShowTutorial(!showTutorial)}
                                className="flex items-center gap-1 text-xs text-orange-600 hover:text-orange-700 font-medium bg-orange-50 px-2 py-1 rounded-md transition-colors"
                            >
                                <HelpCircle className="w-3.5 h-3.5" />
                                配置教程
                            </button>
                        </div>
                        <DialogDescription>
                            添加和管理您的大模型 API 配置
                        </DialogDescription>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto p-6">
                        <div className="space-y-5">
                            {/* 配置教程面板 */}
                            {showTutorial && (
                                <div className="p-5 rounded-2xl border border-orange-100 bg-orange-50/40 space-y-4 animate-in fade-in slide-in-from-top-4 duration-300 shadow-inner">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2 text-base font-bold text-orange-900">
                                            <HelpCircle className="w-5 h-5" />
                                            小白配置全攻略 (2026年1月版)
                                        </div>
                                        <button onClick={() => setShowTutorial(false)} className="text-orange-400 hover:text-orange-600">×</button>
                                    </div>

                                    {/* 1. 核心概念 */}
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="p-3 bg-white/60 rounded-xl border border-orange-50">
                                            <div className="font-bold text-xs text-orange-800 mb-1 flex items-center gap-1">
                                                <Key className="w-3 h-3" /> API Key 是什么？
                                            </div>
                                            <p className="text-[11px] text-orange-600 leading-snug">就像是给 AI 拨号的“手机卡卡密”，每个账号独有且必须有余额才能通话。</p>
                                        </div>
                                        <div className="p-3 bg-white/60 rounded-xl border border-orange-50">
                                            <div className="font-bold text-xs text-orange-800 mb-1 flex items-center gap-1">
                                                <ExternalLink className="w-3 h-3" /> Base URL 是什么？
                                            </div>
                                            <p className="text-[11px] text-orange-600 leading-snug">AI 的“服务器地址”，通常以 <code>/v1</code> 结尾，不能填错。</p>
                                        </div>
                                    </div>

                                    {/* 2. 步骤引导 */}
                                    <div className="space-y-3">
                                        <div className="flex gap-3">
                                            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-orange-600 text-white flex items-center justify-center text-xs font-bold">1</div>
                                            <div className="space-y-1">
                                                <p className="text-sm font-bold text-orange-900">获取密钥 (福利推荐)</p>
                                                <p className="text-[11px] text-orange-700 leading-relaxed">
                                                    首选 <a href="https://www.aiping.cn/#?invitation_code=SJY0NW" target="_blank" className="underline font-bold text-orange-600">AI Ping</a> 注册（通过此链接或者输入邀请码 <b>SJY0NW</b> 可领<b>20元</b>算力点奖励）
                                                </p>
                                            </div>
                                        </div>
                                        <div className="flex gap-3">
                                            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-orange-600 text-white flex items-center justify-center text-xs font-bold">2</div>
                                            <div className="space-y-1">
                                                <p className="text-sm font-bold text-orange-900">录入模型配置</p>
                                                <p className="text-[11px] text-orange-700">点击下方的 <span className="px-1.5 py-0.5 bg-white border border-gray-200 rounded text-gray-400"><Plus className="w-2.5 h-2.5 inline" /></span> 按钮，提供商选 <b>AI Ping</b> 或 <b>其他免费模型提供商</b>，粘贴 Key，保存即可。</p>
                                            </div>
                                        </div>
                                        <div className="flex gap-3">
                                            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-orange-600 text-white flex items-center justify-center text-xs font-bold">3</div>
                                            <div className="space-y-1">
                                                <p className="text-sm font-bold text-orange-900">分配各个“大脑”任务</p>
                                                <p className="text-[11px] text-orange-700 leading-relaxed">
                                                    在下方下拉框中选择你刚才添加的模型：<br />
                                                    - <b>Smart (指挥官):</b> 选 <code>deepseek-v3</code> 或 <code>qwen3-max</code>。<br />
                                                    - <b>Fast (对话员):</b> 选 <code>mimo-v2-flash</code>，速度极快顺滑。
                                                </p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* 3. 最佳方案推荐 */}
                                    <div className="p-3 bg-orange-600/5 rounded-xl border border-orange-200 dashed">
                                        <div className="text-xs font-bold text-orange-900 mb-2 flex items-center gap-1.5">
                                            <Award className="w-4 h-4 text-orange-500" /> 当前最省心组合方案（均可免费白嫖）
                                        </div>
                                        <div className="grid grid-cols-2 gap-2 text-[10px]">
                                            <div className="flex items-center gap-1 text-orange-800">
                                                <span className="w-1 h-1 rounded-full bg-orange-400"></span>
                                                主力模型：DeepSeek-Chat
                                            </div>
                                            <div className="flex items-center gap-1 text-orange-800">
                                                <span className="w-1 h-1 rounded-full bg-orange-400"></span>
                                                对话模型：MiMo-V2（ai ping）
                                            </div>
                                            <div className="flex items-center gap-1 text-orange-800">
                                                <span className="w-1 h-1 rounded-full bg-orange-400"></span>
                                                通用任务：GLM-4.7（ai ping）
                                            </div>
                                            <div className="flex items-center gap-1 text-orange-800">
                                                <span className="w-1 h-1 rounded-full bg-orange-400"></span>
                                                语音面试：Qwen3-Omni（阿里云百炼）
                                            </div>
                                        </div>
                                    </div>

                                    <div className="pt-2 border-t border-orange-100/50 flex items-center justify-between">
                                        <div className="flex gap-2.5">
                                            {API_PROVIDERS.filter(p => p.apiKeyUrl).slice(0, 3).map(p => (
                                                <a key={p.id} href={p.apiKeyUrl} target="_blank" className="flex items-center gap-0.5 text-[10px] text-orange-600 hover:underline">
                                                    <ExternalLink className="w-2 h-2" />
                                                    {p.name.split('(')[0]}
                                                </a>
                                            ))}
                                        </div>
                                        <span className="text-[10px] text-orange-500 italic">设置将实时保存到浏览器本地</span>
                                    </div>
                                </div>
                            )}
                            {/* 添加模型区域 - 水平排列的卡片 */}
                            <div className="space-y-3">
                                <label className="text-sm font-medium text-gray-700">添加模型：</label>
                                <div className="flex flex-wrap gap-3">
                                    {/* 已配置的模型卡片 */}
                                    {config.models.map((model) => {
                                        return (
                                            <div
                                                key={model.id}
                                                onClick={() => handleEditModel(model)}
                                                className="group relative px-4 py-3 rounded-xl border border-gray-200 bg-white hover:border-orange-400 hover:shadow-sm transition-all cursor-pointer min-w-[120px]"
                                            >
                                                <div className="text-sm font-medium text-gray-900 truncate max-w-[100px]">
                                                    {model.name.split(' - ')[0]}
                                                </div>
                                                <div className="text-xs text-gray-400 truncate">
                                                    {model.model}
                                                </div>
                                                <div className="absolute -top-2 -right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <button
                                                        onClick={(e) => handleDuplicateModel(model, e)}
                                                        className="w-5 h-5 rounded-full bg-orange-500 text-white flex items-center justify-center hover:bg-orange-600 shadow-sm"
                                                        title="复制配置"
                                                    >
                                                        <Copy className="w-3 h-3" />
                                                    </button>
                                                    <button
                                                        onClick={(e) => handleDeleteModel(model.id, e)}
                                                        className="w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center hover:bg-red-600 shadow-sm"
                                                        title="删除配置"
                                                    >
                                                        ×
                                                    </button>
                                                </div>
                                            </div>
                                        );
                                    })}

                                    {/* 添加按钮 */}
                                    <button
                                        onClick={handleAddModel}
                                        className="w-[72px] h-[72px] border-2 border-dashed border-gray-200 rounded-xl flex items-center justify-center text-gray-400 hover:border-orange-400 hover:text-orange-600 hover:bg-orange-50/50 transition-all"
                                    >
                                        <Plus className="w-6 h-6" />
                                    </button>
                                </div>
                            </div>

                            <ModelAssignments
                                config={config}
                                onSetSmartModel={onSetSmartModel}
                                onSetFastModel={onSetFastModel}
                                onToggleReasoningPoolModel={onToggleReasoningPoolModel}
                                onToggleFastPoolModel={onToggleFastPoolModel}
                                onSetGeneralModel={onSetGeneralModel}
                                onSetMatchAnalystModel={onSetMatchAnalystModel}
                                onSetContentWriterModel={onSetContentWriterModel}
                                onSetHrReviewerModel={onSetHrReviewerModel}
                                onSetReflectorModel={onSetReflectorModel}
                                onSetVoiceModel={onSetVoiceModel}
                            />

                            {/* 空状态提示 */}
                            {config.models.length === 0 && (
                                <div className="text-center py-6 text-gray-400 text-sm">
                                    点击上方 + 按钮添加模型配置
                                </div>
                            )}
                        </div>
                    </div>

                    <DialogFooter className="p-6 pt-4 border-t bg-gray-50/50">
                        <Button onClick={() => onOpenChange(false)} className="bg-orange-600 hover:bg-orange-700">
                            完成
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* 添加/编辑模型的二级弹窗 */}
            {showModelForm && (
                <ModelFormDialog
                    open={showModelForm}
                    onClose={() => {
                        setShowModelForm(false);
                        setEditingModel(undefined);
                        setSourceModel(undefined);
                    }}
                    onSave={handleSaveModel}
                    editingModel={editingModel}
                    initialValues={sourceModel}
                />
            )}
        </>
    );
}

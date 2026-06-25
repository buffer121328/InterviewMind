'use client';

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import {
    Loader2,
    Wand2,
    Copy,
    Save,
    Target,
    BarChart3,
    MessageSquare,
    AlertTriangle,
    CheckCircle,
    HelpCircle,
} from 'lucide-react';
import {
    rewriteProject,
    ProjectRewriteMode,
    ProjectRewriteResult,
    updateMaterial,
    createMaterial,
} from '@/lib/api/resume';

// 重写模式配置
const REWRITE_MODE_CONFIG: Record<ProjectRewriteMode, { label: string; description: string; icon: React.ReactNode }> = {
    star_rewrite: {
        label: 'STAR 重写',
        description: '按 Situation-Task-Action-Result 结构重写',
        icon: <Wand2 className="h-4 w-4" />,
    },
    quantify_results: {
        label: '量化结果',
        description: '补强量化指标和数据表达',
        icon: <BarChart3 className="h-4 w-4" />,
    },
    jd_customize: {
        label: 'JD 定制',
        description: '针对目标岗位定制项目描述',
        icon: <Target className="h-4 w-4" />,
    },
    followup_prediction: {
        label: '追问预测',
        description: '预测面试官可能追问的问题',
        icon: <MessageSquare className="h-4 w-4" />,
    },
};

interface ProjectRewriteDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    projectTitle: string;
    projectContent: string;
    materialId?: number;
    apiConfig: any;
    onApply?: (newContent: string) => void;
    onRefreshMaterials?: () => void;
}

export function ProjectRewriteDialog({
    open,
    onOpenChange,
    projectTitle: initialTitle,
    projectContent: initialContent,
    materialId,
    apiConfig,
    onApply,
    onRefreshMaterials,
}: ProjectRewriteDialogProps) {
    // 表单状态
    const [projectTitle, setProjectTitle] = useState(initialTitle);
    const [projectContent, setProjectContent] = useState(initialContent);
    const [rewriteMode, setRewriteMode] = useState<ProjectRewriteMode>('star_rewrite');
    const [jobDescription, setJobDescription] = useState('');

    // 结果状态
    const [result, setResult] = useState<ProjectRewriteResult | null>(null);
    const [isRewriting, setIsRewriting] = useState(false);
    const [activeResultTab, setActiveResultTab] = useState('rewritten');

    // 同步外部传入的项目信息
    useEffect(() => {
        if (open) {
            setProjectTitle(initialTitle);
            setProjectContent(initialContent);
            setResult(null);
            setActiveResultTab('rewritten');
        }
    }, [open, initialTitle, initialContent]);

    // 执行重写
    const handleRewrite = async () => {
        if (!projectContent.trim()) {
            toast.error('请输入项目内容');
            return;
        }
        if (!projectTitle.trim()) {
            toast.error('请输入项目标题');
            return;
        }
        if (!apiConfig) {
            toast.error('请先配置 API Key');
            return;
        }
        if (rewriteMode === 'jd_customize' && !jobDescription.trim()) {
            toast.error('JD 定制模式需要输入目标岗位描述');
            return;
        }

        setIsRewriting(true);
        setResult(null);

        try {
            const response = await rewriteProject({
                project_content: projectContent,
                project_title: projectTitle,
                rewrite_mode: rewriteMode,
                job_description: jobDescription || undefined,
                material_id: materialId,
                api_config: apiConfig,
            });

            if (response.success && response.result) {
                setResult(response.result);
                setActiveResultTab('rewritten');
                toast.success('重写完成');
            } else {
                toast.error(response.message || '重写失败');
            }
        } catch (error) {
            toast.error('重写失败，请重试');
        } finally {
            setIsRewriting(false);
        }
    };

    // 复制到剪贴板
    const handleCopy = async (text: string) => {
        try {
            await navigator.clipboard.writeText(text);
            toast.success('已复制到剪贴板');
        } catch {
            toast.error('复制失败');
        }
    };

    // 覆盖当前素材
    const handleOverwriteMaterial = async () => {
        if (!result || !materialId) return;
        try {
            const res = await updateMaterial(materialId, { content: result.rewritten_content });
            if (res.success) {
                toast.success('已覆盖素材内容');
                onRefreshMaterials?.();
            } else {
                toast.error(res.message || '更新失败');
            }
        } catch {
            toast.error('更新失败');
        }
    };

    // 另存为新素材
    const handleSaveAsNew = async () => {
        if (!result) return;
        try {
            const res = await createMaterial({
                material_type: 'project',
                title: `${projectTitle} (重写版)`,
                content: result.rewritten_content,
                source_type: 'ai_extract',
                confidence_score: 0.7,
                is_verified: false,
            });
            if (res.success) {
                toast.success('已另存为新素材');
                onRefreshMaterials?.();
            } else {
                toast.error(res.message || '保存失败');
            }
        } catch {
            toast.error('保存失败');
        }
    };

    // 应用到当前（回调）
    const handleApply = () => {
        if (result) {
            onApply?.(result.rewritten_content);
            toast.success('已应用重写内容');
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Wand2 className="h-5 w-5 text-orange-600" />
                        项目经历重写助手
                    </DialogTitle>
                    <DialogDescription>
                        选择重写模式，AI 将帮你优化项目描述
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-hidden min-h-0">
                    <Tabs defaultValue="input" className="flex flex-col h-full min-h-0">
                        <TabsList className="grid w-full grid-cols-2 shrink-0">
                            <TabsTrigger value="input">输入</TabsTrigger>
                            <TabsTrigger value="result" disabled={!result}>
                                结果 {result && <CheckCircle className="h-3 w-3 ml-1" />}
                            </TabsTrigger>
                        </TabsList>

                        {/* 输入 Tab */}
                        <TabsContent value="input" className="flex-1 overflow-hidden mt-2 data-[state=active]:flex flex-col min-h-0">
                            <ScrollArea className="flex-1">
                                <div className="space-y-4 pr-4">
                                    {/* 项目标题 */}
                                    <div className="space-y-2">
                                        <Label className="text-sm font-medium">项目标题</Label>
                                        <Input
                                            value={projectTitle}
                                            onChange={(e) => setProjectTitle(e.target.value)}
                                            placeholder="请输入项目标题"
                                        />
                                    </div>

                                    {/* 项目内容 */}
                                    <div className="space-y-2">
                                        <Label className="text-sm font-medium">项目内容</Label>
                                        <Textarea
                                            value={projectContent}
                                            onChange={(e) => setProjectContent(e.target.value)}
                                            placeholder="请输入项目经历描述..."
                                            className="min-h-[150px] resize-y font-mono text-sm"
                                        />
                                    </div>

                                    {/* 重写模式 */}
                                    <div className="space-y-2">
                                        <Label className="text-sm font-medium">重写模式</Label>
                                        <div className="grid grid-cols-2 gap-2">
                                            {Object.entries(REWRITE_MODE_CONFIG).map(([mode, config]) => (
                                                <div
                                                    key={mode}
                                                    className={`p-3 rounded-lg border cursor-pointer transition-all ${
                                                        rewriteMode === mode
                                                            ? 'border-orange-500 bg-orange-50'
                                                            : 'border-gray-200 hover:border-gray-300'
                                                    }`}
                                                    onClick={() => setRewriteMode(mode as ProjectRewriteMode)}
                                                >
                                                    <div className="flex items-center gap-2 mb-1">
                                                        {config.icon}
                                                        <span className="text-sm font-medium">{config.label}</span>
                                                    </div>
                                                    <p className="text-xs text-muted-foreground">{config.description}</p>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    {/* JD 输入（jd_customize 模式） */}
                                    {rewriteMode === 'jd_customize' && (
                                        <div className="space-y-2">
                                            <Label className="text-sm font-medium">
                                                目标岗位描述
                                                <span className="text-red-500 ml-1">*</span>
                                            </Label>
                                            <Textarea
                                                value={jobDescription}
                                                onChange={(e) => setJobDescription(e.target.value)}
                                                placeholder="粘贴目标岗位的 JD..."
                                                className="min-h-[100px] resize-y text-sm"
                                            />
                                        </div>
                                    )}
                                </div>
                            </ScrollArea>

                            {/* 执行按钮 */}
                            <div className="shrink-0 pt-3 border-t">
                                <Button
                                    onClick={handleRewrite}
                                    disabled={isRewriting || !projectContent.trim() || !apiConfig}
                                    className="w-full bg-gradient-to-r from-orange-500 to-emerald-500 hover:from-orange-600 hover:to-emerald-600 text-white"
                                >
                                    {isRewriting ? (
                                        <>
                                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                            重写中...
                                        </>
                                    ) : (
                                        <>
                                            <Wand2 className="h-4 w-4 mr-2" />
                                            开始重写
                                        </>
                                    )}
                                </Button>
                            </div>
                        </TabsContent>

                        {/* 结果 Tab */}
                        <TabsContent value="result" className="flex-1 overflow-hidden mt-2 data-[state=active]:flex flex-col min-h-0">
                            {result && (
                                <>
                                    <ScrollArea className="flex-1">
                                        <div className="space-y-4 pr-4">
                                            {/* 重写后内容 */}
                                            <Card>
                                                <CardHeader className="pb-2">
                                                    <div className="flex items-center justify-between">
                                                        <CardTitle className="text-sm">重写后内容</CardTitle>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={() => handleCopy(result.rewritten_content)}
                                                        >
                                                            <Copy className="h-3 w-3 mr-1" />
                                                            复制
                                                        </Button>
                                                    </div>
                                                </CardHeader>
                                                <CardContent>
                                                    <div className="p-3 bg-gray-50 rounded-lg text-sm whitespace-pre-wrap leading-relaxed">
                                                        {result.rewritten_content}
                                                    </div>
                                                </CardContent>
                                            </Card>

                                            {/* 重写理由 */}
                                            <Card>
                                                <CardHeader className="pb-2">
                                                    <CardTitle className="text-sm">重写说明</CardTitle>
                                                </CardHeader>
                                                <CardContent>
                                                    <p className="text-sm text-muted-foreground">{result.rewrite_reason}</p>
                                                </CardContent>
                                            </Card>

                                            {/* 建议补充的数据点 */}
                                            {result.suggested_data_points.length > 0 && (
                                                <Card>
                                                    <CardHeader className="pb-2">
                                                        <CardTitle className="text-sm flex items-center gap-2">
                                                            <HelpCircle className="h-4 w-4" />
                                                            建议补充的数据点
                                                        </CardTitle>
                                                    </CardHeader>
                                                    <CardContent>
                                                        <ul className="space-y-1">
                                                            {result.suggested_data_points.map((point, idx) => (
                                                                <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                                                                    <span className="text-orange-500 mt-0.5">•</span>
                                                                    {point}
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </CardContent>
                                                </Card>
                                            )}

                                            {/* 可能追问的问题 */}
                                            {result.possible_followup_questions.length > 0 && (
                                                <Card>
                                                    <CardHeader className="pb-2">
                                                        <CardTitle className="text-sm flex items-center gap-2">
                                                            <MessageSquare className="h-4 w-4" />
                                                            可能追问的问题
                                                        </CardTitle>
                                                    </CardHeader>
                                                    <CardContent>
                                                        <ul className="space-y-2">
                                                            {result.possible_followup_questions.map((q, idx) => (
                                                                <li key={idx} className="text-sm p-2 bg-blue-50 rounded-lg text-blue-800">
                                                                    {q}
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </CardContent>
                                                </Card>
                                            )}

                                            {/* 推断内容警告 */}
                                            {result.inferred_content && result.inferred_content.length > 0 && (
                                                <Card className="border-orange-200">
                                                    <CardHeader className="pb-2">
                                                        <CardTitle className="text-sm flex items-center gap-2 text-orange-600">
                                                            <AlertTriangle className="h-4 w-4" />
                                                            推断内容（需核实）
                                                        </CardTitle>
                                                    </CardHeader>
                                                    <CardContent>
                                                        <ul className="space-y-1">
                                                            {result.inferred_content.map((item, idx) => (
                                                                <li key={idx} className="text-sm text-orange-700 flex items-start gap-2">
                                                                    <span className="mt-0.5">⚠</span>
                                                                    {item}
                                                                </li>
                                                            ))}
                                                        </ul>
                                                        <p className="text-xs text-orange-500 mt-2">
                                                            以上内容为 AI 推断，请核实后再使用
                                                        </p>
                                                    </CardContent>
                                                </Card>
                                            )}
                                        </div>
                                    </ScrollArea>

                                    {/* 操作按钮 */}
                                    <div className="shrink-0 pt-3 border-t flex gap-2">
                                        {materialId && (
                                            <Button variant="outline" onClick={handleOverwriteMaterial} className="flex-1">
                                                <Save className="h-4 w-4 mr-1" />
                                                覆盖素材
                                            </Button>
                                        )}
                                        <Button variant="outline" onClick={handleSaveAsNew} className="flex-1">
                                            <Save className="h-4 w-4 mr-1" />
                                            另存为素材
                                        </Button>
                                        {onApply && (
                                            <Button onClick={handleApply} className="flex-1 bg-orange-600 hover:bg-orange-700 text-white">
                                                <CheckCircle className="h-4 w-4 mr-1" />
                                                应用到当前
                                            </Button>
                                        )}
                                    </div>
                                </>
                            )}
                        </TabsContent>
                    </Tabs>
                </div>
            </DialogContent>
        </Dialog>
    );
}

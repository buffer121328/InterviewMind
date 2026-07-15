'use client';

import React, { useState, useEffect } from 'react';
import { useInterviewStore } from '@/store/useInterviewStore';
import { CandidateMaterial, MaterialType, type ApiConfig } from '@/lib/api/resume';
import { ProjectRewriteDialog } from './ProjectRewriteDialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { 
    Search, 
    Plus, 
    Edit, 
    Trash2, 
    CheckCircle, 
    Circle,
    Briefcase,
    Code,
    GraduationCap,
    Award,
    Star,
    FileText,
    Loader2,
    Wand2
} from 'lucide-react';

// 素材类型配置
const MATERIAL_TYPE_CONFIG: Record<MaterialType, { label: string; icon: React.ReactNode; color: string }> = {
    tech_stack: { label: '技术栈', icon: <Code className="h-4 w-4" />, color: 'bg-blue-100 text-blue-800' },
    project: { label: '项目经历', icon: <Briefcase className="h-4 w-4" />, color: 'bg-green-100 text-green-800' },
    internship: { label: '实习经历', icon: <Briefcase className="h-4 w-4" />, color: 'bg-yellow-100 text-yellow-800' },
    work_experience: { label: '工作经验', icon: <Briefcase className="h-4 w-4" />, color: 'bg-purple-100 text-purple-800' },
    education: { label: '教育背景', icon: <GraduationCap className="h-4 w-4" />, color: 'bg-pink-100 text-pink-800' },
    certificate: { label: '证书', icon: <Award className="h-4 w-4" />, color: 'bg-orange-100 text-orange-800' },
    highlight: { label: '亮点/成就', icon: <Star className="h-4 w-4" />, color: 'bg-red-100 text-red-800' },
};

interface CandidateMaterialLibraryProps {
    onSelectMaterial?: (material: CandidateMaterial) => void;
    selectionMode?: boolean;
    selectedIds?: number[];
    apiConfig?: ApiConfig;
}

export function CandidateMaterialLibrary({
    onSelectMaterial,
    selectionMode = false,
    selectedIds = [],
    apiConfig,
}: CandidateMaterialLibraryProps) {
    const {
        candidateMaterials,
        candidateMaterialsLoading,
        currentMaterial,
        fetchCandidateMaterials,
        selectMaterial,
        deleteMaterial,
    } = useInterviewStore();

    const [searchKeyword, setSearchKeyword] = useState('');
    const [filterType, setFilterType] = useState<MaterialType | 'all'>('all');
    const [showEditor, setShowEditor] = useState(false);
    const [editingMaterial, setEditingMaterial] = useState<CandidateMaterial | null>(null);

    // 项目重写弹窗状态
    const [showRewriteDialog, setShowRewriteDialog] = useState(false);
    const [rewriteMaterial, setRewriteMaterial] = useState<CandidateMaterial | null>(null);

    // 加载素材列表
    useEffect(() => {
        fetchCandidateMaterials();
    }, [fetchCandidateMaterials]);

    // 过滤素材
    const filteredMaterials = candidateMaterials.filter((m) => {
        // 类型过滤
        if (filterType !== 'all' && m.material_type !== filterType) {
            return false;
        }
        // 关键词搜索
        if (searchKeyword) {
            const keyword = searchKeyword.toLowerCase();
            return (
                m.title.toLowerCase().includes(keyword) ||
                m.content.toLowerCase().includes(keyword) ||
                m.tags.some(t => t.toLowerCase().includes(keyword))
            );
        }
        return true;
    });

    // 处理删除
    const handleDelete = async (materialId: number) => {
        if (window.confirm('确定要删除这个素材吗？')) {
            await deleteMaterial(materialId);
        }
    };

    // 处理编辑
    const handleEdit = (material: CandidateMaterial) => {
        setEditingMaterial(material);
        setShowEditor(true);
    };

    // 处理选择
    const handleSelect = (material: CandidateMaterial) => {
        if (selectionMode && onSelectMaterial) {
            onSelectMaterial(material);
        } else {
            selectMaterial(material.id);
        }
    };

    return (
        <div className="flex flex-col h-full">
            {/* 头部操作栏 */}
            <div className="flex items-center gap-2 p-4 border-b">
                <div className="relative flex-1">
                    <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="搜索素材..."
                        value={searchKeyword}
                        onChange={(e) => setSearchKeyword(e.target.value)}
                        className="pl-8"
                    />
                </div>
                <Select value={filterType} onValueChange={(value: string) => setFilterType(value as MaterialType | 'all')}>
                    <SelectTrigger className="w-[140px]">
                        <SelectValue placeholder="素材类型" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">全部类型</SelectItem>
                        {Object.entries(MATERIAL_TYPE_CONFIG).map(([key, config]) => (
                            <SelectItem key={key} value={key}>
                                <div className="flex items-center gap-2">
                                    {config.icon}
                                    {config.label}
                                </div>
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Button onClick={() => { setEditingMaterial(null); setShowEditor(true); }}>
                    <Plus className="h-4 w-4 mr-2" />
                    添加素材
                </Button>
            </div>

            {/* 素材列表 */}
            <ScrollArea className="flex-1">
                <div className="p-4 space-y-3">
                    {candidateMaterialsLoading ? (
                        <div className="flex items-center justify-center py-8">
                            <Loader2 className="h-6 w-6 animate-spin" />
                            <span className="ml-2">加载中...</span>
                        </div>
                    ) : filteredMaterials.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                            <FileText className="h-12 w-12 mb-4" />
                            <p>暂无素材</p>
                            <p className="text-sm">点击“添加素材”开始创建</p>
                        </div>
                    ) : (
                        filteredMaterials.map((material) => {
                            const typeConfig = MATERIAL_TYPE_CONFIG[material.material_type];
                            const isSelected = selectedIds.includes(material.id);
                            const isCurrent = currentMaterial?.id === material.id;

                            return (
                                <Card
                                    key={material.id}
                                    className={`cursor-pointer transition-all hover:shadow-md ${
                                        isCurrent ? 'ring-2 ring-primary' : ''
                                    } ${isSelected ? 'bg-primary/5' : ''}`}
                                    onClick={() => handleSelect(material)}
                                >
                                    <CardHeader className="pb-2">
                                        <div className="flex items-start justify-between">
                                            <div className="flex items-center gap-2">
                                                {selectionMode && (
                                                    isSelected ? (
                                                        <CheckCircle className="h-5 w-5 text-primary" />
                                                    ) : (
                                                        <Circle className="h-5 w-5 text-muted-foreground" />
                                                    )
                                                )}
                                                <Badge className={typeConfig.color}>
                                                    <span className="flex items-center gap-1">
                                                        {typeConfig.icon}
                                                        {typeConfig.label}
                                                    </span>
                                                </Badge>
                                                {material.is_verified && (
                                                    <Badge variant="outline" className="text-green-600">
                                                        已验证
                                                    </Badge>
                                                )}
                                            </div>
                                            {!selectionMode && (
                                                <div className="flex items-center gap-1">
                                                    {material.material_type === 'project' && apiConfig && (
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            title="AI 重写"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setRewriteMaterial(material);
                                                                setShowRewriteDialog(true);
                                                            }}
                                                        >
                                                            <Wand2 className="h-4 w-4 text-orange-600" />
                                                        </Button>
                                                    )}
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={(e) => { e.stopPropagation(); handleEdit(material); }}
                                                    >
                                                        <Edit className="h-4 w-4" />
                                                    </Button>
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={(e) => { e.stopPropagation(); handleDelete(material.id); }}
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </Button>
                                                </div>
                                            )}
                                        </div>
                                        <CardTitle className="text-base">{material.title}</CardTitle>
                                    </CardHeader>
                                    <CardContent>
                                        <CardDescription className="line-clamp-3">
                                            {material.content}
                                        </CardDescription>
                                        {material.tags.length > 0 && (
                                            <div className="flex flex-wrap gap-1 mt-2">
                                                {material.tags.slice(0, 5).map((tag, index) => (
                                                    <Badge key={index} variant="secondary" className="text-xs">
                                                        {tag}
                                                    </Badge>
                                                ))}
                                                {material.tags.length > 5 && (
                                                    <Badge variant="secondary" className="text-xs">
                                                        +{material.tags.length - 5}
                                                    </Badge>
                                                )}
                                            </div>
                                        )}
                                        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                                            <span>重要性: {(material.importance_score * 100).toFixed(0)}%</span>
                                            <span>可信度: {(material.confidence_score * 100).toFixed(0)}%</span>
                                        </div>
                                    </CardContent>
                                </Card>
                            );
                        })
                    )}
                </div>
            </ScrollArea>

            {/* 素材编辑对话框 */}
            {showEditor && (
                <MaterialEditorDialog
                    open={showEditor}
                    onOpenChange={setShowEditor}
                    material={editingMaterial}
                    onSave={() => {
                        setShowEditor(false);
                        fetchCandidateMaterials();
                    }}
                />
            )}

            {/* 项目重写对话框 */}
            {showRewriteDialog && rewriteMaterial && apiConfig && (
                <ProjectRewriteDialog
                    open={showRewriteDialog}
                    onOpenChange={setShowRewriteDialog}
                    projectTitle={rewriteMaterial.title}
                    projectContent={rewriteMaterial.content}
                    materialId={rewriteMaterial.id}
                    apiConfig={apiConfig}
                    onRefreshMaterials={() => fetchCandidateMaterials()}
                />
            )}
        </div>
    );
}

// 素材编辑对话框组件
interface MaterialEditorDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    material: CandidateMaterial | null;
    onSave: () => void;
}

function createMaterialFormData(material: CandidateMaterial | null) {
    if (material) {
        return {
            material_type: material.material_type,
            title: material.title,
            content: material.content,
            tags: material.tags,
            importance_score: material.importance_score,
            confidence_score: material.confidence_score,
            is_verified: material.is_verified,
        };
    }

    return {
        material_type: 'project' as MaterialType,
        title: '',
        content: '',
        tags: [] as string[],
        importance_score: 0.5,
        confidence_score: 0.5,
        is_verified: false,
    };
}

function MaterialEditorDialog({ open, onOpenChange, material, onSave }: MaterialEditorDialogProps) {
    const [formData, setFormData] = useState(() => createMaterialFormData(material));
    const [tagInput, setTagInput] = useState('');
    const [saving, setSaving] = useState(false);

    // 添加标签
    const handleAddTag = () => {
        if (tagInput.trim() && !formData.tags.includes(tagInput.trim())) {
            setFormData({ ...formData, tags: [...formData.tags, tagInput.trim()] });
            setTagInput('');
        }
    };

    // 删除标签
    const handleRemoveTag = (tag: string) => {
        setFormData({ ...formData, tags: formData.tags.filter(t => t !== tag) });
    };

    // 保存素材
    const handleSave = async () => {
        if (!formData.title || !formData.content) {
            alert('请填写标题和内容');
            return;
        }

        setSaving(true);
        try {
            const { createMaterial, updateMaterial } = await import('@/lib/api/resume');
            
            if (material) {
                // 更新
                const result = await updateMaterial(material.id, formData);
                if (result.success) {
                    onSave();
                } else {
                    alert(result.message || '更新失败');
                }
            } else {
                // 创建
                const result = await createMaterial(formData);
                if (result.success) {
                    onSave();
                } else {
                    alert(result.message || '创建失败');
                }
            }
        } catch (error) {
            console.error('保存素材失败:', error);
            alert('保存失败');
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>{material ? '编辑素材' : '添加素材'}</DialogTitle>
                    <DialogDescription>
                        {material ? '修改素材信息' : '创建新的候选人素材'}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    {/* 素材类型 */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium">素材类型</label>
                        <Select
                            value={formData.material_type}
                            onValueChange={(value: string) => setFormData({ ...formData, material_type: value as MaterialType })}
                        >
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {Object.entries(MATERIAL_TYPE_CONFIG).map(([key, config]) => (
                                    <SelectItem key={key} value={key}>
                                        <div className="flex items-center gap-2">
                                            {config.icon}
                                            {config.label}
                                        </div>
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {/* 标题 */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium">标题</label>
                        <Input
                            value={formData.title}
                            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                            placeholder="请输入素材标题"
                        />
                    </div>

                    {/* 内容 */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium">内容</label>
                        <textarea
                            className="w-full min-h-[120px] p-3 border rounded-md resize-y"
                            value={formData.content}
                            onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                            placeholder="请输入素材内容"
                        />
                    </div>

                    {/* 标签 */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium">标签</label>
                        <div className="flex gap-2">
                            <Input
                                value={tagInput}
                                onChange={(e) => setTagInput(e.target.value)}
                                placeholder="输入标签后按回车"
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        handleAddTag();
                                    }
                                }}
                            />
                            <Button type="button" variant="outline" onClick={handleAddTag}>
                                添加
                            </Button>
                        </div>
                        {formData.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                                {formData.tags.map((tag) => (
                                    <Badge key={tag} variant="secondary" className="cursor-pointer" onClick={() => handleRemoveTag(tag)}>
                                        {tag} ×
                                    </Badge>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* 重要性评分 */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium">
                            重要性: {(formData.importance_score * 100).toFixed(0)}%
                        </label>
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.1"
                            value={formData.importance_score}
                            onChange={(e) => setFormData({ ...formData, importance_score: parseFloat(e.target.value) })}
                            className="w-full"
                        />
                    </div>

                    {/* 可信度评分 */}
                    <div className="space-y-2">
                        <label className="text-sm font-medium">
                            可信度: {(formData.confidence_score * 100).toFixed(0)}%
                        </label>
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.1"
                            value={formData.confidence_score}
                            onChange={(e) => setFormData({ ...formData, confidence_score: parseFloat(e.target.value) })}
                            className="w-full"
                        />
                    </div>

                    {/* 是否已验证 */}
                    <div className="flex items-center gap-2">
                        <input
                            type="checkbox"
                            id="is_verified"
                            checked={formData.is_verified}
                            onChange={(e) => setFormData({ ...formData, is_verified: e.target.checked })}
                        />
                        <label htmlFor="is_verified" className="text-sm font-medium">
                            已验证
                        </label>
                    </div>
                </div>

                <Separator className="my-4" />

                <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        取消
                    </Button>
                    <Button onClick={handleSave} disabled={saving}>
                        {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                        {material ? '保存修改' : '创建素材'}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}

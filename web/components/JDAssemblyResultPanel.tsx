'use client';

import React, { useState, useEffect } from 'react';
import { useInterviewStore } from '@/store/useInterviewStore';
import { AssemblyResult, CandidateMaterial } from '@/lib/api/resume';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { 
    FileText, 
    CheckCircle, 
    XCircle, 
    ChevronDown, 
    ChevronUp,
    Loader2,
    Trash2,
    Eye
} from 'lucide-react';

interface JDAssemblyResultPanelProps {
    assemblyResult: AssemblyResult;
    materials: CandidateMaterial[];
    onGenerateResume?: (resultId: number) => void;
    onDelete?: (resultId: number) => void;
}

export function JDAssemblyResultPanel({
    assemblyResult,
    materials,
    onGenerateResume,
    onDelete,
}: JDAssemblyResultPanelProps) {
    const [showDetails, setShowDetails] = useState(false);
    const [showContent, setShowContent] = useState(false);

    // 获取选中的素材
    const selectedMaterials = materials.filter(m => 
        assemblyResult.selected_material_ids.includes(m.id)
    );

    // 获取未选中的素材
    const unselectedMaterials = materials.filter(m => 
        !assemblyResult.selected_material_ids.includes(m.id)
    );

    return (
        <Card className="w-full">
            <CardHeader>
                <div className="flex items-center justify-between">
                    <div>
                        <CardTitle className="text-lg">简历组装结果</CardTitle>
                        <CardDescription>
                            已选择 {selectedMaterials.length} 个素材
                        </CardDescription>
                    </div>
                    <div className="flex items-center gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setShowDetails(!showDetails)}
                        >
                            {showDetails ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            {showDetails ? '收起详情' : '查看详情'}
                        </Button>
                        {onGenerateResume && (
                            <Button
                                size="sm"
                                onClick={() => onGenerateResume(assemblyResult.id)}
                            >
                                生成简历
                            </Button>
                        )}
                        {onDelete && (
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => onDelete(assemblyResult.id)}
                            >
                                <Trash2 className="h-4 w-4" />
                            </Button>
                        )}
                    </div>
                </div>
            </CardHeader>

            <CardContent>
                {/* JD 摘要 */}
                <div className="mb-4">
                    <h4 className="text-sm font-medium mb-2">目标岗位 JD</h4>
                    <p className="text-sm text-muted-foreground line-clamp-3">
                        {assemblyResult.job_description}
                    </p>
                </div>

                {/* 筛选理由 */}
                {assemblyResult.selection_reason && (
                    <div className="mb-4">
                        <h4 className="text-sm font-medium mb-2">筛选理由</h4>
                        <p className="text-sm text-muted-foreground">
                            {assemblyResult.selection_reason}
                        </p>
                    </div>
                )}

                {/* 详情展开 */}
                {showDetails && (
                    <>
                        <Separator className="my-4" />
                        
                        {/* 选中的素材 */}
                        <div className="mb-4">
                            <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
                                <CheckCircle className="h-4 w-4 text-green-500" />
                                选中的素材 ({selectedMaterials.length})
                            </h4>
                            <div className="space-y-2">
                                {selectedMaterials.map((material) => (
                                    <div
                                        key={material.id}
                                        className="flex items-center justify-between p-2 bg-green-50 rounded-md"
                                    >
                                        <div className="flex items-center gap-2">
                                            <Badge variant="outline">{material.material_type}</Badge>
                                            <span className="text-sm font-medium">{material.title}</span>
                                        </div>
                                        <span className="text-xs text-muted-foreground">
                                            {(material.importance_score * 100).toFixed(0)}% 重要
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* 未选中的素材 */}
                        {unselectedMaterials.length > 0 && (
                            <div className="mb-4">
                                <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
                                    <XCircle className="h-4 w-4 text-gray-400" />
                                    未选中的素材 ({unselectedMaterials.length})
                                </h4>
                                <div className="space-y-2">
                                    {unselectedMaterials.map((material) => (
                                        <div
                                            key={material.id}
                                            className="flex items-center justify-between p-2 bg-gray-50 rounded-md"
                                        >
                                            <div className="flex items-center gap-2">
                                                <Badge variant="outline" className="opacity-50">{material.material_type}</Badge>
                                                <span className="text-sm text-muted-foreground">{material.title}</span>
                                            </div>
                                            <span className="text-xs text-muted-foreground">
                                                {(material.importance_score * 100).toFixed(0)}% 重要
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* 组装大纲 */}
                        {assemblyResult.assembled_outline && Object.keys(assemblyResult.assembled_outline).length > 0 && (
                            <div className="mb-4">
                                <h4 className="text-sm font-medium mb-2">简历大纲</h4>
                                <pre className="text-sm bg-gray-50 p-3 rounded-md overflow-auto">
                                    {JSON.stringify(assemblyResult.assembled_outline, null, 2)}
                                </pre>
                            </div>
                        )}

                        {/* 组装内容预览 */}
                        {assemblyResult.assembled_content && (
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <h4 className="text-sm font-medium">组装内容预览</h4>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => setShowContent(!showContent)}
                                    >
                                        <Eye className="h-4 w-4 mr-2" />
                                        {showContent ? '收起' : '展开'}
                                    </Button>
                                </div>
                                {showContent && (
                                    <div className="prose prose-sm max-w-none bg-white p-4 border rounded-md">
                                        <pre className="whitespace-pre-wrap">{assemblyResult.assembled_content}</pre>
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}

                {/* 时间信息 */}
                <div className="mt-4 text-xs text-muted-foreground">
                    创建时间: {new Date(assemblyResult.created_at).toLocaleString()}
                </div>
            </CardContent>
        </Card>
    );
}


// 组装结果列表组件
interface AssemblyResultListProps {
    onSelectResult?: (result: AssemblyResult) => void;
}

export function AssemblyResultList({ onSelectResult }: AssemblyResultListProps) {
    const {
        assemblyResults,
        assemblyResultsLoading,
        fetchAssemblyResults,
        deleteAssemblyResult,
    } = useInterviewStore();

    const [materialsMap, setMaterialsMap] = useState<Record<number, CandidateMaterial>>({});

    // 加载组装结果
    useEffect(() => {
        fetchAssemblyResults();
    }, [fetchAssemblyResults]);

    // 加载所有素材
    useEffect(() => {
        const loadMaterials = async () => {
            const { getMaterials } = await import('@/lib/api/resume');
            const response = await getMaterials();
            if (response.success) {
                const map: Record<number, CandidateMaterial> = {};
                response.materials.forEach(m => { map[m.id] = m; });
                setMaterialsMap(map);
            }
        };
        loadMaterials();
    }, []);

    // 处理删除
    const handleDelete = async (resultId: number) => {
        if (window.confirm('确定要删除这个组装结果吗？')) {
            await deleteAssemblyResult(resultId);
        }
    };

    // 获取素材列表
    const getMaterialsForResult = (result: AssemblyResult): CandidateMaterial[] => {
        return result.selected_material_ids
            .map(id => materialsMap[id])
            .filter(Boolean);
    };

    if (assemblyResultsLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
                <span className="ml-2">加载中...</span>
            </div>
        );
    }

    if (assemblyResults.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                <FileText className="h-12 w-12 mb-4" />
                <p>暂无组装结果</p>
                <p className="text-sm">请先进行简历组装</p>
            </div>
        );
    }

    return (
        <ScrollArea className="h-full">
            <div className="space-y-4 p-4">
                {assemblyResults.map((result) => (
                    <JDAssemblyResultPanel
                        key={result.id}
                        assemblyResult={result}
                        materials={getMaterialsForResult(result)}
                        onDelete={handleDelete}
                    />
                ))}
            </div>
        </ScrollArea>
    );
}

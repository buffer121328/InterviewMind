import type { ReactNode, RefObject } from 'react';
import { BarChart3, FileText, Loader2, Target, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ResumeOptimizeMode } from '@/lib/api/resume';

type ResumeInputMode = 'analyze' | 'optimize' | 'jd-match';

interface ResumeInputPanelProps {
    mode: ResumeInputMode;
    resume: string;
    jobDescription: string;
    isUploading: boolean;
    isSubmitting: boolean;
    submitDisabled: boolean;
    submitLabel: string;
    submittingLabel: string;
    optimizeProgress?: string;
    sessionPicker?: ReactNode;
    includeProfile?: boolean;
    optimizeMode?: ResumeOptimizeMode;
    fileInputRef: RefObject<HTMLInputElement | null>;
    onResumeChange: (value: string) => void;
    onJobDescriptionChange: (value: string) => void;
    onSubmit: () => void;
    onIncludeProfileChange?: (value: boolean) => void;
    onOptimizeModeChange?: (value: ResumeOptimizeMode) => void;
}

/** Renders the resume input panel UI and coordinates its typed props, local state, and approved backend interactions. */
export function ResumeInputPanel({
    mode,
    resume,
    jobDescription,
    isUploading,
    isSubmitting,
    submitDisabled,
    submitLabel,
    submittingLabel,
    optimizeProgress,
    sessionPicker,
    includeProfile = false,
    optimizeMode = 'balanced',
    fileInputRef,
    onResumeChange,
    onJobDescriptionChange,
    onSubmit,
    onIncludeProfileChange,
    onOptimizeModeChange,
}: ResumeInputPanelProps) {
    const SubmitIcon = mode === 'analyze' ? BarChart3 : mode === 'jd-match' ? Target : FileText;
    const requiresJD = mode !== 'analyze';

    return (
        <div className="flex min-w-0 flex-col self-start rounded-xl border border-gray-100 bg-white shadow-sm">
            <div className="p-4 border-b border-gray-100 flex items-center justify-between shrink-0 bg-gray-50/50">
                <Label className="text-base font-medium text-gray-900">输入信息</Label>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading}
                    className="h-8 bg-white"
                >
                    {isUploading ? (
                        <>
                            <Loader2 className="animate-spin mr-1.5" size={12} />
                            上传中...
                        </>
                    ) : (
                        <>
                            <Upload size={14} className="mr-1.5" />
                            导入简历
                        </>
                    )}
                </Button>
            </div>

            <div className="border-b border-teal-100 bg-teal-50/40 p-3">
                <Button
                    onClick={onSubmit}
                    disabled={submitDisabled}
                    className="h-11 w-full bg-teal-600 text-[15px] font-medium shadow-md shadow-teal-100 transition-all hover:bg-teal-700"
                >
                    {isSubmitting ? (
                        <>
                            <Loader2 className="mr-2 animate-spin" size={18} />
                            {optimizeProgress || submittingLabel}
                        </>
                    ) : (
                        <>
                            <SubmitIcon className="mr-2" size={18} />
                            {submitLabel}
                        </>
                    )}
                </Button>
            </div>

            <div className="space-y-5 p-4">
                        <div className="space-y-2 flex flex-col">
                            <div className="flex items-center justify-between">
                                <Label className="text-xs font-normal text-gray-500">简历纯文本内容</Label>
                            </div>
                            <Textarea
                                placeholder="粘贴简历内容，或点击上方导入文件..."
                                value={resume}
                                onChange={(e) => onResumeChange(e.target.value)}
                                className="h-[300px] min-h-[300px] max-h-[300px] resize-none overflow-y-auto border-gray-200 p-4 font-mono text-sm leading-relaxed [scrollbar-color:#cbd5e1_transparent] [scrollbar-width:thin] focus:border-teal-500 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-slate-300 [&::-webkit-scrollbar-track]:bg-transparent"
                            />
                        </div>

                        <div className="space-y-2">
                            <Label className="text-xs font-normal text-gray-500">
                                目标职位描述 {requiresJD && <span className="text-red-500">*</span>}
                            </Label>
                            <Textarea
                                placeholder={requiresJD ? '输入目标职位的 JD/岗位名...' : '输入目标职位的 JD/岗位名，分析匹配度更准确...'}
                                value={jobDescription}
                                onChange={(e) => onJobDescriptionChange(e.target.value)}
                                className="h-[180px] min-h-[180px] max-h-[180px] resize-none overflow-y-auto border-gray-200 text-sm [scrollbar-color:#cbd5e1_transparent] [scrollbar-width:thin] focus:border-teal-500 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-slate-300 [&::-webkit-scrollbar-track]:bg-transparent"
                            />
                        </div>

                        {sessionPicker}


                        {mode === 'optimize' && onOptimizeModeChange && (
                            <div className="space-y-2 rounded-lg border border-gray-100 bg-white p-3">
                                <Label className="text-xs font-normal text-gray-500">优化模式</Label>
                                <Select value={optimizeMode} onValueChange={(value) => onOptimizeModeChange(value as ResumeOptimizeMode)}>
                                    <SelectTrigger className="h-9 border-gray-200 bg-white">
                                        <SelectValue placeholder="选择优化模式" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="fast">快速预览 · 更快给建议</SelectItem>
                                        <SelectItem value="balanced">智能优化 · 速度质量均衡</SelectItem>
                                        <SelectItem value="quality">高质量精修 · 原流水线</SelectItem>
                                    </SelectContent>
                                </Select>
                                <p className="text-xs text-gray-400 leading-relaxed">
                                    {optimizeMode === 'fast'
                                        ? '适合快速查看可优化点，模型调用更少。'
                                        : optimizeMode === 'quality'
                                            ? '保留原 6 阶段确定性流水线，适合最终投递前精修。'
                                            : '默认推荐：使用受控 Agent 改写节点，并保留事实核验与质量闸门。'}
                                </p>
                            </div>
                        )}

                        {mode === 'optimize' && onIncludeProfileChange && (
                            <div className="flex items-center justify-between p-3 border border-gray-100 rounded-lg hover:bg-gray-50 bg-white cursor-pointer select-none" onClick={() => onIncludeProfileChange(!includeProfile)}>
                                <Label htmlFor="include-profile" className="cursor-pointer flex flex-col pointer-events-none">
                                    <span className="font-medium text-gray-700">包含综合能力画像</span>
                                    <span className="text-xs text-gray-400 font-normal">基于过往面试表现进行评估</span>
                                </Label>
                                <Switch
                                    id="include-profile"
                                    checked={includeProfile}
                                    onCheckedChange={onIncludeProfileChange}
                                    className="data-[state=checked]:bg-teal-600"
                                />
                            </div>
                        )}

            </div>
        </div>
    );
}

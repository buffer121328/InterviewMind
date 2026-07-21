"use client";

import { useState } from "react";
import { Upload, FileText, Loader2, AlertCircle, BrainCircuit, Maximize2, MessageSquare, Headphones, Link2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type InterviewMode = "text" | "voice";
type InterviewType = "tech_initial" | "tech_deep" | "hr_comprehensive";

const INTERVIEW_TYPE_OPTIONS: Array<{ value: InterviewType; label: string; description: string; defaultQuestions: number }> = [
    { value: "tech_initial", label: "综合面", description: "技术、项目、行为与岗位匹配均衡考察", defaultQuestions: 10 },
    { value: "tech_deep", label: "技术面", description: "深挖技术原理、项目架构与工程取舍", defaultQuestions: 20 },
    { value: "hr_comprehensive", label: "HR面", description: "关注动机、沟通、稳定性与文化匹配", defaultQuestions: 5 },
];

const getDefaultQuestionCount = (interviewType: InterviewType): number => (
    INTERVIEW_TYPE_OPTIONS.find((option) => option.value === interviewType)?.defaultQuestions ?? 10
);

interface InterviewSetupProps {
    resume: { original_name: string; content?: string } | null;
    onUploadResume: (file: File) => Promise<void>;
    jobDescription: string;
    onJobDescriptionChange: (value: string) => void;
    companyInfo: string;
    onCompanyInfoChange: (value: string) => void;
    maxQuestions: number;
    onMaxQuestionsChange: (value: number) => void;
    interviewType: InterviewType;
    onInterviewTypeChange: (value: InterviewType) => void;
    questionBankCount: number;
    onQuestionBankCountChange: (value: number) => void;
    experienceQuestionCount?: number;
    isLoading: boolean;
    hasApiConfig: boolean;
    onStartInterview: (mode: InterviewMode, options?: { interviewType: InterviewType; maxQuestions: number }) => Promise<void>;
    onConfigureApi: () => void;
    hasVoiceConfig?: boolean;  // 是否配置了语音模型
}

export function InterviewSetup({
    resume,
    onUploadResume,
    jobDescription,
    onJobDescriptionChange,
    companyInfo,
    onCompanyInfoChange,
    maxQuestions,
    onMaxQuestionsChange,
    interviewType,
    onInterviewTypeChange,
    questionBankCount,
    onQuestionBankCountChange,
    experienceQuestionCount = 0,
    isLoading,
    hasApiConfig,
    onStartInterview,
    onConfigureApi,
    hasVoiceConfig = false
}: InterviewSetupProps) {
    const [isJobDialogOpen, setIsJobDialogOpen] = useState(false);
    const [tempJobDescription, setTempJobDescription] = useState("");
    const [selectedMode, setSelectedMode] = useState<InterviewMode>("text");
    const [isStartDialogOpen, setIsStartDialogOpen] = useState(false);
    const [draftInterviewType, setDraftInterviewType] = useState<InterviewType>(interviewType);
    const [draftQuestionCount, setDraftQuestionCount] = useState("");

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            await onUploadResume(e.target.files[0]);
        }
    };

    const handleOpenJobDialog = () => {
        setTempJobDescription(jobDescription);
        setIsJobDialogOpen(true);
    };

    const handleSaveJobDescription = () => {
        onJobDescriptionChange(tempJobDescription);
        setIsJobDialogOpen(false);
    };

    const handleStartInterview = () => {
        setDraftInterviewType(interviewType);
        setDraftQuestionCount("");
        setIsStartDialogOpen(true);
    };

    const handleConfirmStartInterview = async () => {
        const parsedCount = Number.parseInt(draftQuestionCount, 10);
        const finalQuestionCount = Number.isFinite(parsedCount) && parsedCount > 0
            ? Math.min(parsedCount, 20)
            : getDefaultQuestionCount(draftInterviewType);

        onInterviewTypeChange(draftInterviewType);
        onMaxQuestionsChange(finalQuestionCount);
        setIsStartDialogOpen(false);
        await onStartInterview(selectedMode, {
            interviewType: draftInterviewType,
            maxQuestions: finalQuestionCount,
        });
    };

    return (
        <>
            <div className="bg-white rounded-xl shadow-lg border border-gray-100 p-5 space-y-5">
                {/* 1. 上传简历 */}
                <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-orange-100 text-orange-600 text-xs font-bold">1</span>
                        上传简历 (PDF/Word)
                    </label>
                    <div className="relative group">
                        <input
                            type="file"
                            accept=".pdf,.doc,.docx,.txt,.md"
                            onChange={handleFileUpload}
                            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                        />
                        <div className={cn(
                            "w-full h-12 rounded-lg border-2 border-dashed flex items-center justify-center gap-2 transition-all text-sm",
                            resume
                                ? "border-orange-200 bg-orange-50 text-orange-700"
                                : "border-gray-200 bg-gray-50 text-gray-400 group-hover:border-orange-300 group-hover:bg-orange-50/30"
                        )}>
                            {isLoading ? (
                                <Loader2 className="w-5 h-5 animate-spin" />
                            ) : resume ? (
                                <>
                                    <FileText className="w-5 h-5" />
                                    <span className="font-medium truncate max-w-[200px]">{resume.original_name}</span>
                                    <span className="text-xs bg-orange-200/50 px-2 py-0.5 rounded-full">已上传</span>
                                </>
                            ) : (
                                <>
                                    <Upload className="w-5 h-5" />
                                    <span className="font-medium">点击上传简历</span>
                                </>
                            )}
                        </div>
                    </div>
                </div>

                {/* 2. 职位描述 - 点击弹窗编辑 */}
                <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-orange-100 text-orange-600 text-xs font-bold">2</span>
                        目标岗位
                    </label>

                    <div
                        onClick={handleOpenJobDialog}
                        className="relative group cursor-pointer"
                    >
                        <div className={cn(
                            "w-full rounded-xl border border-gray-200 bg-white p-4 text-sm transition-all",
                            "hover:border-orange-500 hover:ring-2 hover:ring-orange-50",
                            "min-h-[100px] max-h-[100px] overflow-hidden relative"
                        )}>
                            {jobDescription ? (
                                <p className="text-gray-700 whitespace-pre-wrap line-clamp-3">{jobDescription}</p>
                            ) : (
                                <p className="text-gray-400">例如：高级Java工程师，要求熟悉Spring Boot和微服务架构...</p>
                            )}

                            {/* 悬停遮罩和提示 */}
                            <div className="absolute inset-0 bg-gradient-to-t from-white/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end justify-center pb-2">
                                <span className="text-orange-600 font-medium flex items-center gap-1 bg-white/90 px-3 py-1 rounded-full shadow-sm text-xs">
                                    <Maximize2 className="w-3 h-3" /> 点击展开编辑
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* 2.5. 公司信息 (选填) */}
                <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-500 flex items-center gap-2">
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">选填</span>
                        公司信息
                    </label>

                    <input
                        type="text"
                        value={companyInfo}
                        onChange={(e) => onCompanyInfoChange(e.target.value)}
                        className="w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm transition-all hover:border-orange-500 hover:ring-2 hover:ring-orange-50 focus:border-orange-500 focus:ring-2 focus:ring-orange-50 focus:outline-none"
                        placeholder="大厂、创业公司、外企等（主要业务、规模大小）"
                    />
                    <p className="text-xs text-gray-400">
                        提供公司信息可以让面试题目更贴近实际场景
                    </p>
                </div>

                {/* 3. 面试类型与题数 */}
                <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-orange-100 text-orange-600 text-xs font-bold">3</span>
                        面试类型与题数
                    </label>

                    <div className="rounded-xl border border-orange-100 bg-orange-50/50 px-4 py-3 text-sm text-orange-900">
                        <div className="flex items-center justify-between gap-3">
                            <span className="font-medium">{INTERVIEW_TYPE_OPTIONS.find((option) => option.value === interviewType)?.label ?? "综合面"}</span>
                            <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-orange-700 shadow-sm">
                                {maxQuestions} 道主问题
                            </span>
                        </div>
                        <p className="mt-2 text-xs text-orange-700/80">
                            点击开始面试后会弹窗确认；题数可留空，默认 HR 面 5 道、技术面 20 道、综合面 10 道。追问不单独计数。
                        </p>
                    </div>
                </div>

                <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700">
                        从个人题库抽取（0-{maxQuestions}）
                    </label>
                    <div className="flex items-center gap-4">
                        <input
                            type="range"
                            min="0"
                            max={maxQuestions}
                            step="1"
                            value={Math.min(questionBankCount, maxQuestions)}
                            onChange={(e) => onQuestionBankCountChange(parseInt(e.target.value))}
                            className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-orange-600"
                        />
                        <div className="w-12 h-10 flex items-center justify-center bg-orange-50 border border-orange-100 rounded-lg text-orange-700 font-semibold">
                            {Math.min(questionBankCount, maxQuestions)}
                        </div>
                    </div>
                    <p className="text-xs text-gray-400">
                        {experienceQuestionCount > 0
                            ? `另有 ${experienceQuestionCount} 道已选面经题优先用于本次面试，剩余题目由模型补足。`
                            : "题库题优先使用，剩余题目由模型补足，可减少规划等待。"}
                    </p>
                </div>

                {/* 4. 面试模式选择 */}
                <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-orange-100 text-orange-600 text-xs font-bold">4</span>
                        面试模式
                    </label>

                    <div className="grid grid-cols-2 gap-4">
                        {/* 文字模式 */}
                        <button
                            type="button"
                            onClick={() => setSelectedMode("text")}
                            className={cn(
                                "relative p-4 rounded-xl border-2 transition-all text-left",
                                selectedMode === "text"
                                    ? "border-orange-500 bg-orange-50 ring-2 ring-orange-100"
                                    : "border-gray-200 bg-white hover:border-gray-300"
                            )}
                        >
                            <div className="flex items-center gap-3 mb-2">
                                <div className={cn(
                                    "w-10 h-10 rounded-full flex items-center justify-center",
                                    selectedMode === "text" ? "bg-orange-100" : "bg-gray-100"
                                )}>
                                    <MessageSquare className={cn(
                                        "w-5 h-5",
                                        selectedMode === "text" ? "text-orange-600" : "text-gray-500"
                                    )} />
                                </div>
                                <div>
                                    <h4 className={cn(
                                        "font-semibold",
                                        selectedMode === "text" ? "text-orange-700" : "text-gray-700"
                                    )}>文字对话</h4>
                                    <p className="text-xs text-gray-500">打字回答问题</p>
                                </div>
                            </div>
                            {selectedMode === "text" && (
                                <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-orange-500 flex items-center justify-center">
                                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                    </svg>
                                </div>
                            )}
                        </button>

                        {/* 语音模式 */}
                        <button
                            type="button"
                            onClick={() => hasVoiceConfig && setSelectedMode("voice")}
                            disabled={!hasVoiceConfig}
                            className={cn(
                                "relative p-4 rounded-xl border-2 transition-all text-left",
                                !hasVoiceConfig && "opacity-60 cursor-not-allowed",
                                selectedMode === "voice"
                                    ? "border-purple-500 bg-purple-50 ring-2 ring-purple-100"
                                    : "border-gray-200 bg-white hover:border-gray-300"
                            )}
                        >
                            <div className="flex items-center gap-3 mb-2">
                                <div className={cn(
                                    "w-10 h-10 rounded-full flex items-center justify-center",
                                    selectedMode === "voice" ? "bg-purple-100" : "bg-gray-100"
                                )}>
                                    <Headphones className={cn(
                                        "w-5 h-5",
                                        selectedMode === "voice" ? "text-purple-600" : "text-gray-500"
                                    )} />
                                </div>
                                <div>
                                    <h4 className={cn(
                                        "font-semibold",
                                        selectedMode === "voice" ? "text-purple-700" : "text-gray-700"
                                    )}>语音对话</h4>
                                    <p className="text-xs text-gray-500">
                                        {hasVoiceConfig ? "像打电话一样交流" : "需配置语音模型"}
                                    </p>
                                </div>
                            </div>
                            {selectedMode === "voice" && (
                                <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-purple-500 flex items-center justify-center">
                                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                    </svg>
                                </div>
                            )}
                            {!hasVoiceConfig && (
                                <div className="absolute inset-0 flex items-center justify-center bg-white/50 rounded-xl">
                                    <span className="text-xs text-gray-500 bg-white px-2 py-1 rounded shadow-sm">
                                        请先在设置中配置语音模型
                                    </span>
                                </div>
                            )}
                        </button>
                    </div>
                </div>

                {/* 本次面试共享上下文 */}
                <div className="rounded-xl border border-orange-100 bg-orange-50/50 p-4">
                    <div className="mb-3 flex items-center gap-2">
                        <Link2 className="h-4 w-4 text-orange-600" />
                        <div>
                            <p className="text-sm font-medium text-gray-800">本次面试上下文</p>
                            <p className="text-xs text-gray-500">以下信息会一起用于定制问题</p>
                        </div>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                        {[
                            { label: "简历", value: resume ? resume.original_name : "待上传", ready: Boolean(resume) },
                            { label: "目标岗位", value: jobDescription.trim() ? "已设置" : "待填写", ready: Boolean(jobDescription.trim()) },
                            {
                                label: "个性化题目",
                                value: experienceQuestionCount + questionBankCount > 0
                                    ? `面经 ${experienceQuestionCount} · 题库 ${questionBankCount}`
                                    : "由模型生成",
                                ready: true,
                            },
                        ].map((item) => (
                            <div key={item.label} className="rounded-lg border border-orange-100 bg-white px-3 py-2">
                                <div className="flex items-center gap-1.5 text-xs text-gray-500">
                                    <CheckCircle2 className={cn("h-3.5 w-3.5", item.ready ? "text-emerald-500" : "text-gray-300")} />
                                    {item.label}
                                </div>
                                <p className="mt-1 truncate text-sm font-medium text-gray-700">{item.value}</p>
                            </div>
                        ))}
                    </div>
                </div>

                {/* API 配置提示 */}
                {!hasApiConfig && (
                    <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 flex items-start gap-3">
                        <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                            <p className="text-sm font-medium text-amber-900">需要配置 API</p>
                            <p className="text-xs text-amber-700 mt-1">
                                请先在右上角设置中配置您的大模型 API，才能开始使用面试功能
                            </p>
                        </div>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={onConfigureApi}
                            className="border-amber-300 text-amber-700 hover:bg-amber-100"
                        >
                            去配置
                        </Button>
                    </div>
                )}

                {/* 5. 开始按钮 */}
                <Button
                    className={cn(
                        "w-full h-12 text-base font-medium shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed",
                        selectedMode === "voice"
                            ? "bg-purple-600 hover:bg-purple-700 shadow-purple-200"
                            : "bg-orange-600 hover:bg-orange-700 shadow-orange-200"
                    )}
                    onClick={handleStartInterview}
                    disabled={!resume || !jobDescription.trim() || isLoading || !hasApiConfig}
                >
                    {isLoading ? (
                        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    ) : selectedMode === "voice" ? (
                        <Headphones className="mr-2 h-5 w-5" />
                    ) : (
                        <BrainCircuit className="mr-2 h-5 w-5" />
                    )}
                    {selectedMode === "voice" ? "开始语音面试" : "开始面试"}
                </Button>
            </div>

            {/* 开始面试参数弹窗 */}
            <Dialog open={isStartDialogOpen} onOpenChange={setIsStartDialogOpen}>
                <DialogContent className="sm:max-w-[520px]">
                    <DialogHeader>
                        <DialogTitle>本次面试怎么安排？</DialogTitle>
                        <DialogDescription>
                            请选择面试类型，并填写本次打算练习多少道主问题。题数留空时会按类型使用默认值，追问不单独计数。
                        </DialogDescription>
                    </DialogHeader>

                    <div className="space-y-5 py-2">
                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">面试类型</label>
                            <div className="grid gap-2 sm:grid-cols-3">
                                {INTERVIEW_TYPE_OPTIONS.map((option) => (
                                    <button
                                        key={option.value}
                                        type="button"
                                        onClick={() => setDraftInterviewType(option.value)}
                                        className={cn(
                                            "rounded-xl border p-3 text-left transition-all",
                                            draftInterviewType === option.value
                                                ? "border-orange-500 bg-orange-50 ring-2 ring-orange-100"
                                                : "border-gray-200 bg-white hover:border-orange-200"
                                        )}
                                    >
                                        <div className="font-semibold text-gray-900">{option.label}</div>
                                        <div className="mt-1 text-xs text-gray-500">默认 {option.defaultQuestions} 道</div>
                                    </button>
                                ))}
                            </div>
                            <p className="text-xs text-gray-500">
                                {INTERVIEW_TYPE_OPTIONS.find((option) => option.value === draftInterviewType)?.description}
                            </p>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-medium text-gray-700">本次面试题数</label>
                            <input
                                type="number"
                                min="1"
                                max="20"
                                value={draftQuestionCount}
                                onChange={(e) => setDraftQuestionCount(e.target.value)}
                                className="w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm transition-all focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-50"
                                placeholder={`不填默认 ${getDefaultQuestionCount(draftInterviewType)} 道`}
                            />
                            <p className="text-xs text-gray-400">
                                支持 1-20 道主问题；追问最多 2 次且不单独计入题数。
                            </p>
                        </div>
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setIsStartDialogOpen(false)}>取消</Button>
                        <Button onClick={handleConfirmStartInterview} className="bg-orange-600 hover:bg-orange-700">
                            开始{selectedMode === "voice" ? "语音" : "文字"}面试
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* 职位描述弹窗 */}
            <Dialog open={isJobDialogOpen} onOpenChange={setIsJobDialogOpen}>
                <DialogContent className="sm:max-w-[600px]">
                    <DialogHeader>
                        <DialogTitle>编辑目标岗位</DialogTitle>
                        <DialogDescription>
                            请详细描述您想申请的职位要求，包括技术栈、工作年限、核心职责等。越详细，面试问题越精准。
                        </DialogDescription>
                    </DialogHeader>
                    <div className="py-4">
                        <Textarea
                            value={tempJobDescription}
                            onChange={(e) => setTempJobDescription(e.target.value)}
                            placeholder="例如：
职位名称：高级前端工程师
工作年限：3-5年
技术要求：
1. 精通 React/Vue 框架及其生态
2. 熟悉 TypeScript，有大型项目开发经验
3. 熟悉 HTTP 协议，了解前端性能优化
4. 有 Node.js 服务端开发经验优先
..."
                            className="h-[300px] resize-none"
                        />
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setIsJobDialogOpen(false)}>取消</Button>
                        <Button onClick={handleSaveJobDescription} className="bg-orange-600 hover:bg-orange-700">确认</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}

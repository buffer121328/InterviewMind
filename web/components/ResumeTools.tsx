"use client";

import { useState, useEffect, useRef, startTransition } from "react";
import { FileText, BarChart3, Loader2, Target } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { useInterviewStore } from "@/store/useInterviewStore";
import { ResumeGenerationDialog } from "./ResumeGenerationDialog";
import { ResumePreviewDialog } from "./ResumePreviewDialog";
import { ResumeProcessingView } from "./ResumeProcessingView";
import { ResumeInputPanel } from "./resume-tools/ResumeInputPanel";
import { ResumeSessionPicker } from "./resume-tools/ResumeSessionPicker";
import { ResumeToolEmptyState } from "./resume-tools/ResumeToolEmptyState";
import { ResumeAnalyzeResultPanel, ResumeJDMatchResultPanel, ResumeOptimizeResultPanel } from "./resume-tools/ResumeResultPanels";
import { refreshGeneratedResumes } from "@/store/interviewFacade";

import {
    analyzeResume,
    optimizeResumeStreaming,
    ResumeAnalyzeResult,
    ResumeOptimizeResult,
    ApiConfig,
    OptimizeProgressEvent,
    OptimizeWarningEvent,
    updateGeneratedResume,
    analyzeJDMatch,
    JDMatchResult,
} from "@/lib/api/resume";
import { API_BASE_URL, getUserId } from "@/lib/api/config";

interface ResumeToolsProps {
    apiConfig: ApiConfig | null;
    resumeContent: string;
    onResumeChange?: (content: string) => void;
}

export function ResumeTools({ apiConfig, resumeContent, onResumeChange }: ResumeToolsProps) {
    // 输入状态
    const [localResume, setLocalResume] = useState(resumeContent);
    const [jobDescription, setJobDescription] = useState("");

    // 会话选择状态
    const [selectedSessions, setSelectedSessions] = useState<string[]>([]);
    const [includeProfile, setIncludeProfile] = useState(false);

    // 加载状态
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [isOptimizing, setIsOptimizing] = useState(false);
    const [isJDMatching, setIsJDMatching] = useState(false);

    // 结果状态
    const [analyzeResult, setAnalyzeResult] = useState<ResumeAnalyzeResult | null>(null);
    const [optimizeResult, setOptimizeResult] = useState<ResumeOptimizeResult | null>(null);
    const [jdMatchResult, setJDMatchResult] = useState<JDMatchResult | null>(null);
    const [currentResultId, setCurrentResultId] = useState<number | undefined>(undefined);

    // 生成流程状态
    const [showGenerationDialog, setShowGenerationDialog] = useState(false);
    const [showPreviewDialog, setShowPreviewDialog] = useState(false);
    const [previewContent, setPreviewContent] = useState({ title: "", content: "" });
    const [previewResumeId, setPreviewResumeId] = useState<number | null>(null);

    // UI 状态
    const [activeTab, setActiveTab] = useState("analyze");
    const [showSessionPicker, setShowSessionPicker] = useState(false);
    const [optimizeProgress, setOptimizeProgress] = useState<string>("");
    const [isUploading, setIsUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const resultsBottomRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        resultsBottomRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    const {
        currentResumeResult,
        fetchCompletedSessions,
        fetchResumeResults,
        selectResumeResult,
        completedSessions: storeCompletedSessions,
        completedSessionsLoading: isLoadingSessions,
        currentJDMatchDetail,
    } = useInterviewStore();

    // 监听历史记录选择
    useEffect(() => {
        startTransition(() => {
            if (currentResumeResult) {
                // 填充数据
                setLocalResume(currentResumeResult.resume_content);
                setJobDescription(currentResumeResult.job_description || "");
                setSelectedSessions(currentResumeResult.session_ids || []);
                setIncludeProfile(currentResumeResult.include_profile || false);

                // 设置结果并切换 Tab
                if (currentResumeResult.result_type === 'analyze') {
                    setAnalyzeResult(currentResumeResult.result_data as ResumeAnalyzeResult);
                    setOptimizeResult(null);
                    setActiveTab('analyze');
                } else {
                    setOptimizeResult(currentResumeResult.result_data as ResumeOptimizeResult);
                    setAnalyzeResult(null);
                    setActiveTab('optimize');
                }
                setCurrentResultId(currentResumeResult.id);
            } else {
                // 新建模式：清空结果和非简历输入
                setAnalyzeResult(null);
                setOptimizeResult(null);
                setCurrentResultId(undefined);

                // 重置表单状态
                setJobDescription("");
                setSelectedSessions([]);
                setIncludeProfile(false);
            }
        });
    }, [currentResumeResult]);

    // 同步外部简历内容（仅在非查看历史记录模式下）
    useEffect(() => {
        if (!currentResumeResult) {
            startTransition(() => {
                setLocalResume(resumeContent);
            });
        }
    }, [resumeContent, currentResumeResult]);

    // 同步 store 中的 JD 匹配详情
    useEffect(() => {
        if (currentJDMatchDetail) {
            startTransition(() => {
                setJDMatchResult(currentJDMatchDetail);
                setActiveTab("jd-match");
            });
        }
    }, [currentJDMatchDetail]);

    // 加载已完成会话列表
    useEffect(() => {
        fetchCompletedSessions();
    }, [fetchCompletedSessions]);

    // 使用 store 中的 sessions 覆盖本地 sessions (为了保持向下兼容不需要修改太多渲染代码)
    const displaySessions = storeCompletedSessions;

    // 文件上传处理
    const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        setIsUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch(`${API_BASE_URL}/api/upload/resume`, {
                method: 'POST',
                headers: { 'X-User-ID': getUserId() },
                body: formData,
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail?.message || '上传失败');
            }

            const data = await response.json();
            setLocalResume(data.text_content);
            onResumeChange?.(data.text_content);
            toast.success(`已从 ${file.name} 提取简历内容`);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '文件上传失败');
        } finally {
            setIsUploading(false);
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        }
    };

    const handleSessionToggle = (sessionId: string) => {
        setSelectedSessions((prev) => {
            if (prev.includes(sessionId)) {
                return prev.filter((id) => id !== sessionId);
            }
            if (prev.length >= 3) {
                toast.warning("最多只能选择 3 个面试记录");
                return prev;
            }
            return [...prev, sessionId];
        });
    };

    const handleAnalyze = async () => {
        if (!localResume.trim()) {
            toast.error("请输入简历内容");
            return;
        }
        if (!apiConfig) {
            toast.error("请先配置 API Key");
            return;
        }

        setIsAnalyzing(true);
        setAnalyzeResult(null);

        try {
            const response = await analyzeResume({
                resume_content: localResume,
                job_description: jobDescription || undefined,
                session_ids: selectedSessions,
                api_config: apiConfig,
            });

            if (response.success && response.result) {
                setAnalyzeResult(response.result);
                toast.success("分析完成");
                // 刷新侧边栏历史记录，完成后自动选中新记录
                await fetchResumeResults();
                if (response.result_id) {
                    await selectResumeResult(response.result_id);
                }
            } else {
                toast.error(response.message || "分析失败");
            }
        } catch {
            toast.error("分析失败，请重试");
        } finally {
            setIsAnalyzing(false);
        }
    };

    const handleOptimize = async () => {
        if (!localResume.trim()) {
            toast.error("请输入简历内容");
            return;
        }
        if (!jobDescription.trim()) {
            toast.error("请输入目标职位描述");
            return;
        }
        if (!apiConfig) {
            toast.error("请先配置 API Key");
            return;
        }

        setIsOptimizing(true);
        setOptimizeResult(null);
        setOptimizeProgress("正在初始化...");

        try {
            const response = await optimizeResumeStreaming(
                {
                    resume_content: localResume,
                    job_description: jobDescription,
                    session_ids: selectedSessions,
                    include_overall_profile: includeProfile,
                    api_config: apiConfig,
                },
                (event: OptimizeProgressEvent) => {
                    setOptimizeProgress(event.message);
                },
                (event: OptimizeWarningEvent) => {
                    // 显示节点失败警告
                    toast.warning(`${event.node} 分析失败`, {
                        description: "API 返回异常，部分分析结果可能不完整",
                        duration: 5000,
                    });
                }
            );

            if (response.success && response.result) {
                setOptimizeResult(response.result);
                // 如果有警告，在成功消息中提醒用户
                if (response.warnings && response.warnings.length > 0) {
                    toast.success(`优化建议生成完成（${response.warnings.length} 个节点异常）`, {
                        description: "部分专家节点返回异常，结果可能不完整",
                    });
                } else {
                    toast.success("优化建议生成完成");
                }
                // 刷新侧边栏历史记录，完成后自动选中新记录
                await fetchResumeResults();
                if (response.result_id) {
                    setCurrentResultId(response.result_id);
                    await selectResumeResult(response.result_id);
                }
            } else {
                toast.error(response.message || "优化失败");
            }
        } catch {
            toast.error("优化失败，请重试");
        } finally {
            setIsOptimizing(false);
            setOptimizeProgress("");
        }
    };

    const handleJDMatch = async () => {
        if (!localResume.trim()) {
            toast.error("请输入简历内容");
            return;
        }
        if (!jobDescription.trim()) {
            toast.error("请输入目标职位描述");
            return;
        }
        if (!apiConfig) {
            toast.error("请先配置 API Key");
            return;
        }

        setIsJDMatching(true);
        setJDMatchResult(null);

        try {
            const response = await analyzeJDMatch({
                resume_content: localResume,
                job_description: jobDescription,
                api_config: apiConfig,
            });

            if (response.success && response.result) {
                setJDMatchResult(response.result);
                toast.success("JD 匹配分析完成");
            } else {
                toast.error(response.message || "分析失败");
            }
        } catch {
            toast.error("分析失败，请重试");
        } finally {
            setIsJDMatching(false);
        }
    };

    const renderSessionPicker = () => (
        <ResumeSessionPicker
            sessions={displaySessions}
            selectedSessions={selectedSessions}
            isOpen={showSessionPicker}
            isLoading={isLoadingSessions}
            onToggleOpen={() => setShowSessionPicker(!showSessionPicker)}
            onToggleSession={handleSessionToggle}
        />
    );

    return (
        <div className="h-full flex flex-col">
            <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.doc,.docx,.txt,.md"
                onChange={handleFileUpload}
                className="hidden"
                id="resume-upload"
            />
            <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
                <TabsList className="grid w-full grid-cols-3 mb-4 shrink-0">
                    <TabsTrigger value="analyze">
                        <BarChart3 size={16} className="mr-2" />
                        竞争力分析
                    </TabsTrigger>
                    <TabsTrigger value="jd-match">
                        <Target size={16} className="mr-2" />
                        JD 匹配
                    </TabsTrigger>
                    <TabsTrigger value="optimize">
                        <FileText size={16} className="mr-2" />
                        内容优化
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="analyze" className="flex-1 overflow-hidden data-[state=active]:flex flex-col min-h-0 mt-0">
                    <div className="grid lg:grid-cols-12 gap-6 h-full min-h-0">
                        <ResumeInputPanel
                            mode="analyze"
                            resume={localResume}
                            jobDescription={jobDescription}
                            isUploading={isUploading}
                            isSubmitting={isAnalyzing}
                            submitDisabled={isAnalyzing || !localResume.trim() || !apiConfig}
                            submitLabel="开始竞争力分析"
                            submittingLabel="分析中..."
                            sessionPicker={renderSessionPicker()}
                            fileInputRef={fileInputRef}
                            onResumeChange={(value) => {
                                setLocalResume(value);
                                onResumeChange?.(value);
                            }}
                            onJobDescriptionChange={setJobDescription}
                            onSubmit={handleAnalyze}
                        />

                        {/* 右侧结果区 */}
                        <div className="lg:col-span-7 h-full overflow-hidden flex flex-col min-h-0">
                            {isAnalyzing ? (
                                <ResumeProcessingView type="analyze" />
                            ) : analyzeResult ? (
                                <ScrollArea className="h-full pr-4">
                                    <div className="pb-4">
                                        <ResumeAnalyzeResultPanel result={analyzeResult} />
                                    </div>
                                </ScrollArea>
                            ) : (
                                <ResumeToolEmptyState type="analyze" />
                            )}
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="jd-match" className="flex-1 overflow-hidden data-[state=active]:flex flex-col min-h-0 mt-0">
                    <div className="grid lg:grid-cols-12 gap-6 h-full min-h-0">
                        <ResumeInputPanel
                            mode="jd-match"
                            resume={localResume}
                            jobDescription={jobDescription}
                            isUploading={isUploading}
                            isSubmitting={isJDMatching}
                            submitDisabled={isJDMatching || !localResume.trim() || !jobDescription.trim() || !apiConfig}
                            submitLabel="开始 JD 匹配分析"
                            submittingLabel="分析中..."
                            fileInputRef={fileInputRef}
                            onResumeChange={(value) => {
                                setLocalResume(value);
                                onResumeChange?.(value);
                            }}
                            onJobDescriptionChange={setJobDescription}
                            onSubmit={handleJDMatch}
                        />

                        {/* 右侧结果区 */}
                        <div className="lg:col-span-7 h-full overflow-hidden flex flex-col min-h-0">
                            {isJDMatching ? (
                                <div className="h-full flex flex-col items-center justify-center text-gray-400 p-8 text-center bg-gray-50/50 rounded-xl border border-dashed border-gray-200">
                                    <Loader2 className="animate-spin mb-4" size={40} />
                                    <h3 className="text-lg font-medium text-gray-600 mb-2">正在分析匹配度...</h3>
                                    <p className="text-sm text-gray-500">AI 正在比对简历与 JD 的匹配程度</p>
                                </div>
                            ) : jdMatchResult ? (
                                <ScrollArea className="h-full pr-4">
                                    <div className="pb-4">
                                        <ResumeJDMatchResultPanel
                                            result={jdMatchResult}
                                            onContinueOptimize={() => {
                                                setActiveTab("optimize");
                                                toast.info("已切换到内容优化，可继续优化简历");
                                            }}
                                        />
                                    </div>
                                </ScrollArea>
                            ) : (
<ResumeToolEmptyState type="jd-match" />
                            )}
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="optimize" className="flex-1 overflow-hidden data-[state=active]:flex flex-col min-h-0 mt-0">
                    <div className="grid lg:grid-cols-12 gap-6 h-full min-h-0">
                        <ResumeInputPanel
                            mode="optimize"
                            resume={localResume}
                            jobDescription={jobDescription}
                            isUploading={isUploading}
                            isSubmitting={isOptimizing}
                            submitDisabled={isOptimizing || !localResume.trim() || !jobDescription.trim() || !apiConfig}
                            submitLabel="生成内容优化建议"
                            submittingLabel="优化中..."
                            optimizeProgress={optimizeProgress}
                            sessionPicker={renderSessionPicker()}
                            includeProfile={includeProfile}
                            fileInputRef={fileInputRef}
                            onResumeChange={(value) => {
                                setLocalResume(value);
                                onResumeChange?.(value);
                            }}
                            onJobDescriptionChange={setJobDescription}
                            onSubmit={handleOptimize}
                            onIncludeProfileChange={setIncludeProfile}
                        />

                        {/* 右侧结果区 */}
                        <div className="lg:col-span-7 h-full overflow-hidden flex flex-col min-h-0">
                            {isOptimizing ? (
                                <ResumeProcessingView type="optimize" message={optimizeProgress} />
                            ) : optimizeResult ? (
                                <ScrollArea className="h-full pr-4">
                                    <div className="pb-4">
                                        <ResumeOptimizeResultPanel
                                            result={optimizeResult}
                                            onScrollToGenerate={scrollToBottom}
                                            onGenerate={() => setShowGenerationDialog(true)}
                                            resultsBottomRef={resultsBottomRef}
                                        />
                                    </div>
                                </ScrollArea>
                            ) : (
                                <ResumeToolEmptyState type="optimize" />
                            )}
                        </div>
                    </div>
                </TabsContent>
            </Tabs>

            {/* Dialogs */}
            {showGenerationDialog && apiConfig && optimizeResult && (
                <ResumeGenerationDialog
                    isOpen={showGenerationDialog}
                    onClose={() => setShowGenerationDialog(false)}
                    resumeContent={localResume}
                    jobDescription={jobDescription}
                    optimizationResult={optimizeResult}
                    optimizationResultId={currentResultId}
                    apiConfig={apiConfig}
                    onSuccess={(id, title, content) => {
                        setPreviewContent({ title, content });
                        setPreviewResumeId(id);
                        setShowPreviewDialog(true);
                        // 刷新已生成列表
                        refreshGeneratedResumes();
                    }}
                />
            )}

            {showPreviewDialog && (
                <ResumePreviewDialog
                    isOpen={showPreviewDialog}
                    onClose={() => setShowPreviewDialog(false)}
                    title={previewContent.title}
                    content={previewContent.content}
                    onContentChange={async (newContent) => {
                        setPreviewContent(prev => ({ ...prev, content: newContent }));
                        if (previewResumeId) {
                            await updateGeneratedResume(previewResumeId, newContent);
                            refreshGeneratedResumes();
                        }
                    }}
                />
            )}
        </div>
    );
}

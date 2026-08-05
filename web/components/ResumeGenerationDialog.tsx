import { useEffect, useEffectEvent, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Circle, Loader2, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import {
    getGenerationSessionStatus,
    initResumeGeneration,
    submitGenerationAnswers,
    type ApiConfig,
    type ResumeGenerationProgressStep,
    type ResumeOptimizeResult,
} from "@/lib/api/resume";

interface ResumeGenerationDialogProps {
    isOpen: boolean;
    onClose: () => void;
    resumeContent?: string;
    jobDescription?: string;
    optimizationResult?: ResumeOptimizeResult;
    existingSessionId?: string;
    optimizationResultId?: number;
    apiConfig: ApiConfig;
    onSuccess: (resumeId: number, title: string, content: string) => void;
}

type Step = "init" | "question" | "generating";

const PROGRESS_COPY: Record<ResumeGenerationProgressStep["id"], { title: string; detail: string }> = {
    requirements_analysis: { title: "需求分析", detail: "识别经历信息缺口与需要补充的问题" },
    draft_generation: { title: "生成专业初稿", detail: "结合目标岗位生成含适度包装的完整初稿" },
    draft_optimization: { title: "查漏补缺并优化", detail: "补充遗漏内容，改善完整度、关键词与表达质量" },
    fact_check: { title: "事实与包装边界核查", detail: "检查数据、技能和经历表述，避免过度包装" },
    final_review: { title: "最终润色与质量审阅", detail: "统一结构、措辞和重点，完成最终版本" },
    saving_result: { title: "保存结果并准备导出", detail: "写入任务中心，生成可预览、可导出的简历" },
};

const INITIAL_PROGRESS: ResumeGenerationProgressStep[] = Object.keys(PROGRESS_COPY).map((id, index) => ({
    id: id as ResumeGenerationProgressStep["id"],
    status: index === 0 ? "running" : "pending",
}));

function completedRequirementProgress(): ResumeGenerationProgressStep[] {
    return INITIAL_PROGRESS.map((item, index) => ({ ...item, status: index === 0 ? "completed" : "pending" }));
}

/** Renders real persisted resume-generation stages instead of a single indefinite spinner. */
export function ResumeGenerationDialog({
    isOpen,
    onClose,
    resumeContent,
    jobDescription,
    optimizationResult,
    optimizationResultId,
    existingSessionId,
    apiConfig,
    onSuccess,
}: ResumeGenerationDialogProps) {
    const [step, setStep] = useState<Step>("init");
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState("");
    const [questions, setQuestions] = useState<string[]>([]);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [progressSteps, setProgressSteps] = useState<ResumeGenerationProgressStep[]>(INITIAL_PROGRESS);
    const monitorTokenRef = useRef(0);

    /** Polls the persisted generation graph at a bounded cadence and mirrors every backend stage transition. */
    async function monitorProgress(id: string, token: number) {
        while (monitorTokenRef.current === token) {
            const status = await getGenerationSessionStatus(id);
            if (monitorTokenRef.current !== token) return;
            if (status?.progress_steps?.length) setProgressSteps(status.progress_steps);
            if (status?.status === "completed" || status?.status === "failed") return;
            await new Promise(resolve => setTimeout(resolve, 1200));
        }
    }

    /** Runs the long generation request while a separate status poll keeps the checklist current. */
    async function generate(id: string, submittedAnswers: Record<string, string>) {
        setIsLoading(true);
        setStep("generating");
        setError(null);
        const token = monitorTokenRef.current + 1;
        monitorTokenRef.current = token;
        void monitorProgress(id, token);
        try {
            const response = await submitGenerationAnswers({
                session_id: id,
                answers: submittedAnswers,
                api_config: apiConfig,
            });
            if (response.success && response.resume_id && response.content) {
                setProgressSteps(current => current.map(item => ({ ...item, status: "completed" })));
                onSuccess(response.resume_id, response.title || "新简历", response.content);
                onClose();
                return;
            }
            setError(response.message || "生成失败，请重试");
            setProgressSteps(current => current.map(item => item.status === "running" ? { ...item, status: "failed" } : item));
        } catch {
            setError("提交失败，请重试");
            setProgressSteps(current => current.map(item => item.status === "running" ? { ...item, status: "failed" } : item));
        } finally {
            monitorTokenRef.current += 1;
            setIsLoading(false);
        }
    }

    /** Initializes the requirement gate, then automatically starts generation when no questions are needed. */
    async function handleInit() {
        if (!resumeContent || !jobDescription || !optimizationResult) {
            setError("缺少创建简历生成会话所需的工作台结果");
            return;
        }
        setIsLoading(true);
        setError(null);
        setStep("init");
        setProgressSteps(INITIAL_PROGRESS);
        try {
            const response = await initResumeGeneration({
                resume_content: resumeContent,
                job_description: jobDescription,
                optimization_result: optimizationResult,
                optimization_result_id: optimizationResultId,
                api_config: apiConfig,
            });

            if (!response.success || !response.session_id) {
                setError(response.message || "初始化失败");
                setProgressSteps(current => current.map(item => item.status === "running" ? { ...item, status: "failed" } : item));
                return;
            }

            setSessionId(response.session_id);
            setProgressSteps(completedRequirementProgress());
            if (response.needs_input && response.questions?.length) {
                setQuestions(response.questions);
                setStep("question");
                return;
            }
            if (response.result) {
                onSuccess(response.result.resume_id, response.result.title, response.result.content);
                onClose();
                return;
            }
            await generate(response.session_id, {});
        } catch {
            setError("网络请求失败");
            setProgressSteps(current => current.map(item => item.status === "running" ? { ...item, status: "failed" } : item));
        } finally {
            setIsLoading(false);
        }
    }

    const initializeOnMount = useEffectEvent(async () => {
        if (!existingSessionId) {
            await handleInit();
            return;
        }
        setIsLoading(true);
        setError(null);
        const status = await getGenerationSessionStatus(existingSessionId);
        if (!status) {
            setError("补充信息会话不存在或已过期");
        } else if (status.status !== "awaiting_input" || !status.questions.length) {
            setError("该会话当前不接受补充回答");
        } else {
            setSessionId(existingSessionId);
            setQuestions(status.questions);
            setAnswers(status.user_answers || {});
            if (status.progress_steps?.length) setProgressSteps(status.progress_steps);
            setStep("question");
        }
        setIsLoading(false);
    });

    useEffect(() => {
        void Promise.resolve().then(() => initializeOnMount());
        return () => { monitorTokenRef.current += 1; };
    }, []);

    /** Validates the interactive answers before continuing the same persisted generation session. */
    /** Requires every generated clarification question to be answered before continuing. */
    const handleSubmitAnswers = async () => {
        const answeredCount = questions.filter(question => answers[question]?.trim()).length;
        if (answeredCount < questions.length) {
            toast.error("请回答所有问题以便生成更准确的简历");
            return;
        }
        await generate(sessionId, answers);
    };

    /** Stores one clarification answer by its stable question text. */
    const handleAnswerChange = (index: number, value: string) => {
        setAnswers(previous => ({ ...previous, [questions[index]]: value }));
    };

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !isLoading && !open && onClose()}>
            <DialogContent className="sm:max-w-[680px] max-h-[86vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle>{existingSessionId ? "继续补充简历信息" : "生成专业简历"}</DialogTitle>
                    <DialogDescription>
                        {step === "question" ? "需求分析已完成，请补充关键信息后继续。" : "以下步骤来自真实生成流程，完成后会自动打勾。"}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto min-h-[260px] py-4">
                    {error && (
                        <div className="flex items-start gap-2 p-3 text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg mb-4">
                            <AlertCircle size={17} className="mt-0.5 shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}

                    <div className="rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-50 via-white to-teal-50/60 p-4 sm:p-5 shadow-sm">
                        <div className="mb-4 flex items-center justify-between gap-3">
                            <div>
                                <p className="text-sm font-semibold text-slate-900">生成进度</p>
                                <p className="mt-1 text-xs text-slate-500">需求分析 → 初稿 → 优化 → 核查 → 终审 → 保存</p>
                            </div>
                            {isLoading && <Loader2 className="h-5 w-5 animate-spin text-teal-600" />}
                        </div>
                        <div className="space-y-2.5">
                            {progressSteps.map(item => {
                                const copy = PROGRESS_COPY[item.id];
                                return (
                                    <div key={item.id} className={`flex gap-3 rounded-xl border px-3.5 py-3 transition-colors ${item.status === "running" ? "border-teal-200 bg-teal-50" : item.status === "completed" ? "border-emerald-100 bg-emerald-50/60" : item.status === "failed" ? "border-red-200 bg-red-50" : "border-slate-100 bg-white/70"}`}>
                                        <div className="pt-0.5">
                                            {item.status === "completed" && <CheckCircle2 className="h-5 w-5 text-emerald-600" />}
                                            {item.status === "running" && <Loader2 className="h-5 w-5 animate-spin text-teal-600" />}
                                            {item.status === "failed" && <AlertCircle className="h-5 w-5 text-red-600" />}
                                            {item.status === "pending" && <Circle className="h-5 w-5 text-slate-300" />}
                                        </div>
                                        <div className="min-w-0">
                                            <p className={`text-sm font-medium ${item.status === "pending" ? "text-slate-500" : "text-slate-900"}`}>{copy.title}</p>
                                            <p className="mt-0.5 text-xs leading-5 text-slate-500">{copy.detail}</p>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {step === "question" && !isLoading && (
                        <ScrollArea className="mt-5 max-h-[350px] pr-4">
                            <div className="space-y-5">
                                {questions.map((question, index) => (
                                    <div key={question} className="space-y-2">
                                        <Label className="text-sm font-medium text-gray-700">{index + 1}. {question}</Label>
                                        <Textarea
                                            value={answers[question] || ""}
                                            onChange={(event) => handleAnswerChange(index, event.target.value)}
                                            placeholder="请输入具体内容（如：项目数据、具体贡献等）"
                                            className="min-h-[80px] text-sm resize-y"
                                        />
                                    </div>
                                ))}
                            </div>
                        </ScrollArea>
                    )}
                </div>

                <DialogFooter className="gap-2 sm:gap-2">
                    {step === "question" && (
                        <>
                            <Button variant="outline" onClick={onClose} disabled={isLoading}>取消</Button>
                            <Button onClick={() => void handleSubmitAnswers()} disabled={isLoading} className="bg-teal-700 hover:bg-teal-800">
                                <Wand2 className="mr-2 h-4 w-4" />开始生成
                            </Button>
                        </>
                    )}
                    {error && step === "init" && <Button onClick={() => void handleInit()}>重新分析</Button>}
                    {error && step === "generating" && <Button onClick={() => void generate(sessionId, answers)}>重试生成</Button>}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

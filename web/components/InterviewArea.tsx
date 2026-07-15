import { useState, ReactNode } from "react";
import { Mic, Award, Plus, Loader2 } from "lucide-react";
import { useInterviewStore } from "@/store/useInterviewStore";
import { VoiceInterview } from "./VoiceInterview";
import { DialogueReview } from "./DialogueReview";
import { PreparingInterview } from "./interview/PreparingInterview";
import { Button } from "./ui/button";
import { SessionProfileDialog } from "./SessionProfileDialog";
import { toast } from "sonner";
import { getUserId } from "@/hooks/useUserIdentity";

interface InterviewAreaProps {
    children: ReactNode;
}

export function InterviewArea({ children }: InterviewAreaProps) {
    const isVoiceMode = useInterviewStore((state) => state.isVoiceMode);
    const setVoiceMode = useInterviewStore((state) => state.setVoiceMode);
    const currentSession = useInterviewStore((state) => state.currentSession);
    const threadId = useInterviewStore((state) => state.threadId);
    const isInitializing = useInterviewStore((state) => state.isInitializing);
    const initializationStage = useInterviewStore((state) => state.initializationStage);
    const executionPlan = useInterviewStore((state) => state.executionPlan);
    const fetchSessions = useInterviewStore((state) => state.fetchSessions);
    const selectSession = useInterviewStore((state) => state.selectSession);
    const maxQuestions = useInterviewStore((state) => state.maxQuestions);
    const setMaxQuestions = useInterviewStore((state) => state.setMaxQuestions);
    const setInitializing = useInterviewStore((state) => state.setInitializing);
    const clearVoiceState = useInterviewStore((state) => state.clearVoiceState);

    const [showSessionProfileDialog, setShowSessionProfileDialog] = useState(false);
    const [iscloning, setIsCloning] = useState(false);
    const [isGeneratingSummary, setIsGeneratingSummary] = useState(false);

    // 1. 如果处于语音模式
    if (isVoiceMode) {
        return (
            <>
                {/* 始终渲染 VoiceInterview，用 CSS 控制可见性，避免重新挂载 */}
                <div className={isInitializing ? "hidden" : "flex-1 flex flex-col h-full"}>
                    <VoiceInterview
                        sessionId={threadId || ''}
                        onEnd={() => setVoiceMode(false)}
                    />
                </div>
                {/* 初始化时显示准备界面 */}
                {isInitializing && (
                    <div className="flex-1 flex flex-col h-full items-center justify-center bg-gradient-to-b from-white to-gray-50">
                        <PreparingInterview stage={initializationStage} plan={executionPlan} />
                    </div>
                )}
            </>
        );
    }

    // 2. 如果是语音会话但不在通话中，渲染语音回顾界面
    if (currentSession?.metadata.mode === 'voice') {
        const messages = currentSession.messages || [];
        // 格式化消息
        const formattedMessages = messages.map(m => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            timestamp: m.timestamp,
            audio_url: m.audio_url
        }));

        const isCompleted = currentSession.metadata.status === 'completed';
        const roundIndex = currentSession.metadata.round_index || 1;

        const handleNextRound = async () => {
            if (iscloning) return;
            setIsCloning(true);
            try {
                const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/sessions/${currentSession.session_id}/next-round`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-User-ID': getUserId()
                    },
                    body: JSON.stringify({
                        max_questions: maxQuestions
                    })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.message || '创建下一轮失败');
                }

                const data = await response.json();
                const newSessionId = data.session.session_id;

                // 开启下一轮前，先清理语音状态并设为初始化中（触发 Preparing 动画）
                clearVoiceState();
                setInitializing(true);

                await fetchSessions(undefined);
                await selectSession(newSessionId);

                setVoiceMode(true);
                toast.success('已开启下一轮语音面试');
            } catch (error) {
                console.error('创建下一轮失败:', error);
                toast.error((error as Error).message || '创建下一轮失败');
            } finally {
                setIsCloning(false);
            }
        };

        const handleGenerateSummary = async () => {
            if (isGeneratingSummary) return;
            setIsGeneratingSummary(true);
            const apiConfig = useInterviewStore.getState().getApiConfigForRequest();

            try {
                const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/voice/summary`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: currentSession.session_id,
                        api_config: apiConfig
                    })
                });

                if (!response.ok) throw new Error('生成总结失败');

                const reader = response.body?.getReader();
                if (!reader) throw new Error('无法读取流');

                while (true) {
                    const { done } = await reader.read();
                    if (done) break;
                }

                await selectSession(currentSession.session_id);
                toast.success('总结生成成功');
            } catch (error) {
                console.error(error);
                toast.error('生成总结失败');
            } finally {
                setIsGeneratingSummary(false);
            }
        };

        const hasSummary = formattedMessages.some(m => m.content.includes('【面试总结】'));

        return (
            <div className="flex-1 flex flex-col h-full overflow-hidden bg-slate-50/50">
                <div className="p-8 overflow-y-auto flex-1 custom-scrollbar">
                    <div className="max-w-3xl mx-auto space-y-8 pb-12">
                        <div className="flex items-center justify-between border-b border-slate-200 pb-4">
                            <h2 className="text-xl font-bold text-slate-800 flex items-center gap-3">
                                <div className="w-2.5 h-2.5 rounded-full bg-indigo-500 animate-pulse"></div>
                                语音面试对话回顾
                            </h2>
                            <span className="text-xs font-medium text-slate-400 bg-slate-100 px-2 py-1 rounded">
                                {formattedMessages.length} 条消息
                            </span>
                        </div>

                        {isCompleted && (
                            <div className="p-6 rounded-2xl bg-gradient-to-r from-indigo-50 to-blue-50 border border-indigo-100 shadow-sm animate-in fade-in slide-in-from-top-4 duration-500">
                                <div className="flex flex-col md:flex-row items-center justify-between gap-6">
                                    <div className="flex-1">
                                        {roundIndex >= 3 ? (
                                            <>
                                                <h4 className="font-bold text-indigo-900 mb-1 flex items-center gap-2">
                                                    🎉 所有面试已圆满结束！
                                                </h4>
                                                <p className="text-sm text-indigo-700/80">
                                                    恭喜您完成了全部 3 轮面试，您的表现已记录在案。
                                                </p>
                                            </>
                                        ) : (
                                            <>
                                                <h4 className="font-bold text-indigo-900 mb-1">本轮面试已完成！</h4>
                                                <p className="text-sm text-indigo-700/80">
                                                    您可以查看本轮能力评估，或直接开启下一轮挑战。
                                                </p>
                                            </>
                                        )}
                                    </div>
                                    <div className="flex flex-wrap items-center gap-3">
                                        {!hasSummary && (
                                            <Button
                                                variant="outline"
                                                onClick={handleGenerateSummary}
                                                disabled={isGeneratingSummary}
                                                className="bg-white border-indigo-200 text-indigo-700 hover:bg-indigo-50 gap-2 shadow-sm h-10"
                                            >
                                                {isGeneratingSummary ? <Loader2 className="w-4 h-4 animate-spin" /> : <Award className="w-4 h-4 text-amber-500" />}
                                                生成反馈总结
                                            </Button>
                                        )}

                                        <Button
                                            variant="outline"
                                            onClick={() => setShowSessionProfileDialog(true)}
                                            className="bg-white border-indigo-200 text-indigo-700 hover:bg-indigo-50 gap-2 shadow-sm h-10"
                                        >
                                            <Award className="w-4 h-4 text-pink-500" />
                                            查看能力画像
                                        </Button>

                                        {roundIndex < 3 && (
                                            <div className="flex items-center gap-2 bg-white p-1 rounded-lg border border-indigo-100 shadow-sm">
                                                <select
                                                    className="h-8 px-2 rounded bg-transparent text-sm focus:outline-none text-indigo-900"
                                                    value={maxQuestions}
                                                    onChange={(e) => setMaxQuestions(parseInt(e.target.value))}
                                                >
                                                    {[3, 4, 5, 6, 7, 8, 9, 10].map(n => (
                                                        <option key={n} value={n}>{n} 题</option>
                                                    ))}
                                                </select>
                                                <Button
                                                    onClick={handleNextRound}
                                                    disabled={iscloning}
                                                    className="bg-indigo-600 hover:bg-indigo-700 text-white h-8 gap-2 px-3 text-xs font-bold"
                                                >
                                                    {iscloning ? (
                                                        <Loader2 className="w-3 h-3 animate-spin" />
                                                    ) : (
                                                        <Plus className="w-3 h-3" />
                                                    )}
                                                    开启下一轮
                                                </Button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* 活跃面试提醒：如果面试未完成，在顶部显示一个精致的恢复入口 */}
                        {!isCompleted && (
                            <div className="p-1.5 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-600 shadow-xl shadow-indigo-200/50 mb-8 mt-2 group relative overflow-hidden animate-in slide-in-from-top-4 duration-700">
                                {/* 装饰性微光动画 */}
                                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-1000"></div>

                                <div className="bg-white/5 backdrop-blur-sm rounded-xl px-6 py-4 flex items-center justify-between border border-white/10 relative z-10">
                                    <div className="flex items-center gap-4">
                                        <div className="relative">
                                            <div className="w-12 h-12 rounded-full bg-white/20 flex items-center justify-center text-white">
                                                <Mic className="w-5 h-5" />
                                            </div>
                                            <div className="absolute -top-1 -right-1 w-4 h-4 bg-green-400 rounded-full border-2 border-indigo-600 animate-pulse"></div>
                                        </div>
                                        <div>
                                            <h4 className="font-bold text-white text-base">语音面试正在进行</h4>
                                            <p className="text-indigo-100/70 text-xs text-left">面试官正在等待您的回应，点击继续通话</p>
                                        </div>
                                    </div>
                                    <Button
                                        onClick={() => setVoiceMode(true)}
                                        className="bg-white text-indigo-600 hover:bg-slate-50 font-bold px-6 h-10 rounded-full shadow-lg transition-all hover:scale-105 active:scale-95 whitespace-nowrap"
                                    >
                                        继续面试
                                    </Button>
                                </div>
                            </div>
                        )}

                        <DialogueReview messages={formattedMessages} />
                    </div>
                </div>

                {showSessionProfileDialog && (
                    <SessionProfileDialog
                        sessionId={currentSession.session_id}
                        open={showSessionProfileDialog}
                        onOpenChange={setShowSessionProfileDialog}
                    />
                )}
            </div>
        );
    }

    return <>{children}</>;
}

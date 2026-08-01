'use client';

import { useState } from 'react';
import { Award, Loader2, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { getUserId } from '@/hooks/useUserIdentity';
import { API_BASE_URL } from '@/lib/api/config';
import { QUESTION_COUNT_OPTIONS, defaultQuestionsForRoundIndex } from '@/lib/interview/questionDefaults';
import { waitForInterviewStartRun, type InterviewStartRunState } from '@/lib/interviewStartRun';
import { useInterviewStore } from '@/store/useInterviewStore';

interface InterviewNextRoundBannerProps {
    roundIndex: number;
    sessionId: string;
    isLoading: boolean;
    isStreaming: boolean;
    onOpenReport: () => void;
}

/** Offers the next-round launch with a question-count selector after one text interview round completes. */
export function InterviewNextRoundBanner({
    roundIndex,
    sessionId,
    isLoading,
    isStreaming,
    onOpenReport,
}: InterviewNextRoundBannerProps) {
    const [nextRoundQuestionOverride, setNextRoundQuestionOverride] = useState<number | null>(null);

    /** Creates the next-round session and starts it through the recoverable AgentRun contract. */
    const handleStartNextRound = async () => {
        try {
            // 从 store 获取最新的题目数量
            const nextRoundQuestions = nextRoundQuestionOverride ?? defaultQuestionsForRoundIndex(roundIndex + 1);

            // 设置加载状态，清空消息以显示加载动画
            useInterviewStore.setState({
                isLoading: true,
                isStreaming: true,
                messages: [],
                interviewProgress: { current: 0, total: nextRoundQuestions }
            });

            // 1. 创建下一轮会话
            const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}/next-round`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-ID': getUserId()
                },
                body: JSON.stringify({
                    max_questions: nextRoundQuestions,
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || '创建下一轮失败');
            }

            const data = await response.json();
            const newSessionId = data.session.session_id;

            // 2. 刷新会话列表并选择新会话
            await useInterviewStore.getState().fetchSessions(undefined);
            await useInterviewStore.getState().selectSession(newSessionId);

            // 3. 通过可恢复 AgentRun 启动下一轮，避免同步启动请求在模型超时时锁住页面。
            const apiConfig = useInterviewStore.getState().getApiConfigForRequest();
            if (!apiConfig) {
                throw new Error('请先配置 API');
            }

            useInterviewStore.setState({
                isInitializing: true,
                initializationStage: 'queued',
                executionPlan: [
                    { id: 'queued', title: '等待执行资源', status: 'running' },
                    { id: 'loading_context', title: '读取简历与面试上下文', status: 'pending' },
                    { id: 'generating_question', title: '规划面试并生成首题', status: 'pending' },
                ],
            });
            const startResponse = await fetch(`${API_BASE_URL}/api/agent-runs/interview-start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-ID': getUserId(),
                    'Idempotency-Key': newSessionId,
                },
                body: JSON.stringify({
                    thread_id: newSessionId,
                    mode: 'mock',
                    max_questions: nextRoundQuestions,
                    api_config: apiConfig,
                })
            });

            if (!startResponse.ok) {
                const message = await startResponse.text();
                throw new Error(message || '启动面试失败');
            }

            const initialRun = await startResponse.json() as InterviewStartRunState;
            const result = await waitForInterviewStartRun(
                initialRun,
                async (runId) => {
                    const runResponse = await fetch(`${API_BASE_URL}/api/agent-runs/${runId}`, {
                        headers: { 'X-User-ID': getUserId() },
                    });
                    if (!runResponse.ok) throw new Error('读取面试任务状态失败');
                    return runResponse.json() as Promise<InterviewStartRunState>;
                },
                {
                    onProgress: (run) => useInterviewStore.setState({
                        initializationStage: run.stage || 'queued',
                        executionPlan: Array.isArray(run.plan)
                            ? run.plan
                            : useInterviewStore.getState().executionPlan,
                    }),
                },
            );

            useInterviewStore.setState({
                messages: [{
                    role: 'assistant',
                    content: result.first_question!,
                    timestamp: new Date().toISOString(),
                }],
                isLoading: false,
                isStreaming: false,
                isInitializing: false,
                initializationStage: null,
            });
            await useInterviewStore.getState().fetchSessions(undefined);

        } catch (error) {
            console.error('创建下一轮失败:', error);
            toast.error((error as Error).message || '创建下一轮失败');
            useInterviewStore.setState({ isLoading: false, isStreaming: false, isInitializing: false, initializationStage: null });
        }
    };

    return (
        <div className="mb-4 p-4 rounded-xl bg-gradient-to-r from-teal-50 to-amber-50 border border-teal-200">
            <div className="flex items-center justify-between gap-4">
                <div className="flex-1">
                    {/* 判断是否为最后一轮（第3轮） */}
                    {roundIndex >= 3 ? (
                        <>
                            <h4 className="font-semibold text-gray-900 mb-1">🎉 所有面试已结束！</h4>
                            <p className="text-sm text-gray-600">
                                恭喜您完成了全部 3 轮面试，点击查看本轮能力画像
                            </p>
                        </>
                    ) : (
                        <>
                            <h4 className="font-semibold text-gray-900 mb-1">面试已完成！</h4>
                            <p className="text-sm text-gray-600">
                                继续进行下一轮面试，深入考察您的专业能力
                            </p>
                        </>
                    )}
                </div>
                <div className="flex items-center gap-3">
                    <Button
                        variant="outline"
                        onClick={onOpenReport}
                        className="gap-2"
                    >
                        <Award className="w-4 h-4 text-pink-500" />
                        本轮完整评估
                    </Button>
                    {/* 仅在非最后一轮时显示下一轮选项 */}
                    {roundIndex < 3 && (
                        <div className="flex items-center gap-2 bg-white p-1 rounded-lg border border-teal-100 shadow-sm">
                            <select
                                id="next-round-questions"
                                className="h-8 px-2 rounded-md bg-transparent text-sm focus:outline-none text-teal-900"
                                defaultValue={defaultQuestionsForRoundIndex(roundIndex + 1)}
                                onChange={(e) => {
                                    // 更新全局状态中的 maxQuestions
                                    setNextRoundQuestionOverride(parseInt(e.target.value));
                                    useInterviewStore.setState({ maxQuestions: parseInt(e.target.value) });
                                }}
                            >
                                {QUESTION_COUNT_OPTIONS.map((n) => (
                                    <option key={n} value={n}>{n} 道题</option>
                                ))}
                            </select>
                            <Button
                                onClick={() => void handleStartNextRound()}
                                disabled={isLoading || isStreaming}
                                className="bg-teal-600 hover:bg-teal-700 text-white gap-2 disabled:opacity-50 h-8 px-3 text-xs font-bold"
                            >
                                {isLoading ? (
                                    <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                    <Plus className="w-3 h-3" />
                                )}
                                {isLoading ? '准备中...' : '开启下一轮'}
                            </Button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

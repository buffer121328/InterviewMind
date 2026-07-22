import { useEffect, useEffectEvent, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { toast } from 'sonner';
import { getUserId } from '@/hooks/useUserIdentity';
import { API_BASE_URL } from '@/lib/api/config';
import { useInterviewStore } from '@/store/useInterviewStore';
import type { Message } from '@/store/types';
import {
    buildVoiceStartRequestPayload,
    clearPendingExperienceQuestions,
    getVoiceRequestApiConfig,
    selectInterviewSession,
    setVoiceInterviewProgress,
    type VoiceRequestApiConfig,
} from '@/store/interviewFacade';

export type VoiceInterviewStatus = 'initializing' | 'listening' | 'speaking' | 'processing' | 'idle';

type VoiceStartResponse = {
    session_id?: string;
    question_count?: number;
    max_questions?: number;
    history?: Message[];
    greeting_text?: string;
    system_prompt?: string;
};

interface UseVoiceInterviewSessionParams {
    sessionId: string;
    status: VoiceInterviewStatus;
    abortControllerRef: MutableRefObject<AbortController | null>;
    onEnd: () => void;
    onHangUp: () => void | Promise<void>;
    startRecording: () => void;
    setStatus: Dispatch<SetStateAction<VoiceInterviewStatus>>;
    sendGreeting: (apiConfig: NonNullable<VoiceRequestApiConfig>, prompt: string, greetingText: string) => Promise<void>;
    markWaitingForPlayback: () => void;
    resetPlaybackFlow: () => void;
}

function isAbortError(error: unknown): boolean {
    return error instanceof Error && error.name === 'AbortError';
}

export function useVoiceInterviewSession({
    sessionId,
    status,
    abortControllerRef,
    onEnd,
    onHangUp,
    startRecording,
    setStatus,
    sendGreeting,
    markWaitingForPlayback,
    resetPlaybackFlow,
}: UseVoiceInterviewSessionParams) {
    const setVoiceHistory = useInterviewStore(state => state.setVoiceHistory);
    const setInitializing = useInterviewStore(state => state.setInitializing);
    const fetchSessions = useInterviewStore(state => state.fetchSessions);
    const hasInitialized = useRef(false);

    const initializeSession = useEffectEvent(async () => {
        if (status !== 'initializing') return;
        if (hasInitialized.current) return;
        hasInitialized.current = true;

        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();
        const signal = abortControllerRef.current.signal;

        try {
            const apiConfig = getVoiceRequestApiConfig();
            if (!apiConfig || !apiConfig.voice) {
                toast.error('请先在设置中配置语音模型 (Voice)');
                onEnd();
                return;
            }

            const response = await fetch(`${API_BASE_URL}/api/voice/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-ID': getUserId(),
                },
                signal,
                body: JSON.stringify(buildVoiceStartRequestPayload(sessionId, apiConfig)),
            });

            if (signal.aborted) return;
            if (!response.ok) throw new Error('初始化失败');

            const data = await response.json() as VoiceStartResponse;
            if (signal.aborted) return;

            if (data.session_id && data.session_id !== sessionId) {
                console.info(`[VoiceInterview] 检测到 Session 变更 (文字->语音切换): ${sessionId} -> ${data.session_id}`);
                useInterviewStore.setState({ threadId: data.session_id });
                await selectInterviewSession(data.session_id);
            }
            if (signal.aborted) return;

            if (typeof data.question_count === 'number') {
                setVoiceInterviewProgress(data.question_count + 1, data.max_questions);
            }

            const hasExistingHistory = Array.isArray(data.history) && data.history.length > 0;
            if (hasExistingHistory) {
                console.log(`[VoiceInterview] 恢复历史消息: ${data.history!.length} 条`);
                setVoiceHistory(data.history!);
            }

            clearPendingExperienceQuestions();
            setInitializing(false);
            fetchSessions();

            if (hasExistingHistory) {
                console.log('[VoiceInterview] 检测到已有历史记录，跳过开场白，直接进入录音状态');
                startRecording();
                setStatus('listening');
                return;
            }

            if (signal.aborted) return;

            console.log('[VoiceInterview] 初始化完成，开始流式生成开场白...');
            if (data.greeting_text) {
                markWaitingForPlayback();
                await sendGreeting(apiConfig, data.system_prompt || '', data.greeting_text);
                console.log('[VoiceInterview] 开场白 SSE 流结束，等待音频播放完成...');
            } else {
                startRecording();
                setStatus('listening');
            }
        } catch (error) {
            if (isAbortError(error)) return;
            console.error(error);
            toast.error('无法启动语音面试');
            hasInitialized.current = false;
            setInitializing(false);
            void onHangUp();
        }
    });

    useEffect(() => {
        void Promise.resolve().then(() => initializeSession());
        return () => {
            console.log('[VoiceInterview] 组件卸载，清理资源...');
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
                abortControllerRef.current = null;
            }
            hasInitialized.current = false;
            resetPlaybackFlow();
        };
    }, [sessionId, abortControllerRef, resetPlaybackFlow]);
}

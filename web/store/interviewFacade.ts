import { useInterviewStore } from './useInterviewStore';
import type { Message } from './types';

type InterviewStoreSnapshot = ReturnType<typeof useInterviewStore.getState>;
export type VoiceRequestApiConfig = ReturnType<InterviewStoreSnapshot['getApiConfigForRequest']>;


export function getRequestApiConfig(): VoiceRequestApiConfig {
    return useInterviewStore.getState().getApiConfigForRequest();
}

export async function refreshGeneratedResumes(): Promise<void> {
    await useInterviewStore.getState().fetchGeneratedResumes?.();
}

export function getVoiceRequestApiConfig(): VoiceRequestApiConfig {
    return useInterviewStore.getState().getApiConfigForRequest();
}

export function getVoiceGreetingHistorySnapshot(): Message[] {
    return useInterviewStore.getState().voiceHistory;
}

export function getVoiceTurnContext(): {
    apiConfig: VoiceRequestApiConfig;
    history: Message[];
    systemPrompt: string;
} {
    const state = useInterviewStore.getState();
    return {
        apiConfig: state.getApiConfigForRequest(),
        history: state.voiceHistory,
        systemPrompt: state.voiceSystemPrompt,
    };
}

export function buildVoiceStartRequestPayload(sessionId: string, apiConfig: NonNullable<VoiceRequestApiConfig>) {
    const state = useInterviewStore.getState();
    return {
        thread_id: sessionId,
        mode: 'mock',
        api_config: apiConfig,
        resume_content: state.resume?.content,
        resume_filename: state.resume?.filename,
        job_description: state.jobDescription,
        company_info: state.companyInfo,
        max_questions: state.maxQuestions,
        round_type: state.interviewType,
        question_bank_count: state.questionBankCount,
        experience_questions: state.experienceQuestions.slice(0, state.maxQuestions),
    };
}

export async function selectInterviewSession(sessionId: string): Promise<void> {
    await useInterviewStore.getState().selectSession(sessionId);
}

export function setVoiceInterviewProgress(current: number, total?: number): void {
    const state = useInterviewStore.getState();
    state.setInterviewProgress({
        current,
        total: total || state.maxQuestions,
    });
}

export function clearPendingExperienceQuestions(): void {
    useInterviewStore.getState().setExperienceQuestions([]);
}

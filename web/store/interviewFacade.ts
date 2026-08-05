import { useInterviewStore } from './useInterviewStore';
import type { Message } from './types';

type InterviewStoreSnapshot = ReturnType<typeof useInterviewStore.getState>;
export type VoiceRequestApiConfig = ReturnType<InterviewStoreSnapshot['getApiConfigForRequest']>;


/** Provides the get request api config store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export function getRequestApiConfig(): VoiceRequestApiConfig {
    return useInterviewStore.getState().getApiConfigForRequest();
}

/** Provides the refresh generated resumes store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export async function refreshGeneratedResumes(): Promise<void> {
    await useInterviewStore.getState().fetchGeneratedResumes?.();
}

/** Provides the get voice request api config store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export function getVoiceRequestApiConfig(): VoiceRequestApiConfig {
    return useInterviewStore.getState().getApiConfigForRequest();
}

/** Provides the get voice greeting history snapshot store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export function getVoiceGreetingHistorySnapshot(): Message[] {
    return useInterviewStore.getState().voiceHistory;
}

/** Provides the get voice turn context store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
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

/** Provides the build voice start request payload store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
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
        job_context_snapshot: state.jobContextSnapshot
            ? { ...state.jobContextSnapshot, job_description: state.jobDescription }
            : null,
        max_questions: state.maxQuestions,
        round_type: state.interviewType,
        question_bank_count: state.questionBankCount,
        experience_questions: state.experienceQuestions.slice(0, state.maxQuestions),
    };
}

/** Provides the select interview session store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export async function selectInterviewSession(sessionId: string): Promise<void> {
    await useInterviewStore.getState().selectSession(sessionId);
}

/** Provides the set voice interview progress store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export function setVoiceInterviewProgress(current: number, total?: number): void {
    const state = useInterviewStore.getState();
    state.setInterviewProgress({
        current,
        total: total || state.maxQuestions,
    });
}

/** Provides the clear pending experience questions store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
export function clearPendingExperienceQuestions(): void {
    useInterviewStore.getState().setExperienceQuestions([]);
}

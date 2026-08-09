import { API_BASE_URL, getUserId } from './config';

export type ExperienceSource = 'nowcoder';

export interface ExperienceQuestionCandidate {
    question_text: string;
    reference_answer?: string;
    tags: string[];
    difficulty: 'easy' | 'medium' | 'hard';
    target_skill?: string;
    question_type: 'intro' | 'tech' | 'behavior' | 'system_design';
    source_type: string;
    source_id: string;
}

export interface ExperienceCollectResponse {
    success: boolean;
    experiences: Array<{
        source: string;
        source_id: string;
        title: string;
        url: string;
        query: string;
        content_preview: string;
    }>;
    questions: ExperienceQuestionCandidate[];
    document_count: number;
    candidate_count: number;
    filtered_count: number;
    duplicate_count: number;
    imported_count: number;
    failed_count: number;
    import_id?: number;
    message?: string;
    warnings?: string[];
}

/** Calls the backend for collect interview experiences; the shared API client supplies request identity and error normalization, and this helper returns the typed endpoint result. */
export async function collectInterviewExperiences(input: {
    source: ExperienceSource;
    queries: string[];
    max_pages?: number;
    exported_items?: Array<Record<string, unknown>>;
    api_config: Record<string, unknown>;
}): Promise<ExperienceCollectResponse> {
    const response = await fetch(`${API_BASE_URL}/api/interview-experiences/collect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-ID': getUserId() },
        body: JSON.stringify(input),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message ?? data.detail ?? '面经采集失败');
    return data;
}

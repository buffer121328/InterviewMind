import { API_BASE_URL, getUserId } from './config';

export type ExperienceSource = 'nowcoder' | 'xiaohongshu';

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
    message?: string;
}

export async function collectInterviewExperiences(input: {
    source: ExperienceSource;
    queries: string[];
    max_pages?: number;
    exported_items?: Array<Record<string, unknown>>;
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

export async function importExperienceQuestions(questions: ExperienceQuestionCandidate[]): Promise<{
    success: boolean;
    success_count: number;
    total_count: number;
    message?: string;
}> {
    const response = await fetch(`${API_BASE_URL}/api/interview-experiences/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-ID': getUserId() },
        body: JSON.stringify({ questions }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message ?? data.detail ?? '面经题导入失败');
    return data;
}

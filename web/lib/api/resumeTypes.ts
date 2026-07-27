/**
 * 简历工具 API 类型定义
 */

export type JsonObject = Record<string, unknown>;

export type ResumeOptimizeMode = 'fast' | 'balanced' | 'quality';

export interface DimensionScore {
    score: number;
    comment: string;
}

export interface ResumeAnalyzeResult {
    overall_score: number;
    dimension_scores: Record<string, DimensionScore>;
    strengths: string[];
    weaknesses: string[];
    priority_improvements: string[];
    interview_insights?: string;
}

export interface OptimizedSection {
    section_name: string;
    original_issues?: string[];
    optimized_content?: string;
    /** 新版 pipeline 输出：段落级别变更集合 */
    section?: string;
    changes?: Array<{
        original?: string;
        optimized?: string;
        reason?: string;
        [k: string]: unknown;
    }>;
}

export interface KeyImprovement {
    priority: number;
    area: string;
    issue: string;
    action: string;
    example?: string;
}

/**
 * pipeline 输出的单项变更（新版 /optimize 同步接口）
 */
export interface ResumeChangeItem {
    change_type?: string;
    section_name?: string;
    original_text?: string | null;
    optimized_text?: string;
    confidence?: number;
    requires_user_confirmation?: boolean;
    reason?: string | null;
}

export interface ResumeOptimizeResult {
    /** 后端优化运行模式 */
    mode?: ResumeOptimizeMode;
    match_score: number;
    hr_pass_rate: number;
    optimized_sections: OptimizedSection[];
    /** 新版后端返回的是字符串数组（原因摘要），旧版是结构化对象。两者兼容 */
    key_improvements: KeyImprovement[] | string[];
    keyword_analysis?: {
        jd_keywords: string[];
        matched: string[];
        missing: string[];
        bonus: string[];
        /** 新版字段 */
        required?: string[];
        preferred?: string[];
    };
    hr_feedback?: {
        first_impression: { score: number; comment: string };
        highlights: string[];
        concerns: string[];
    };
    interview_insights?: string;
    reflection_notes?: {
        additional_suggestions: string[];
        risk_warnings: string[];
        quality_score: number;
    };
    node_errors?: Array<{ node: string; error: string }>;
    /** 新版 pipeline 字段：单项变更列表 */
    change_items?: ResumeChangeItem[];
    /** 整体置信度 0-1 */
    overall_confidence?: number;
    /** 是否需要用户人工复核 */
    requires_user_review?: boolean;
}

export type ResumeReviewDecision = 'approved' | 'rejected';

export interface ResumeReviewItem extends ResumeChangeItem {
    item_id: string;
    status: 'pending' | ResumeReviewDecision;
}

export interface ResumeReviewState {
    status: 'pending' | 'completed' | 'not_required';
    version: number;
    items: ResumeReviewItem[];
    resolved_resume?: string | null;
}

export interface JDMatchResult {
    overall_match_score: number;
    skill_match_score: number;
    project_match_score: number;
    experience_match_score: number;
    education_match_score: number;
    matched_keywords: string[];
    missing_keywords: string[];
    strengths: string[];
    risks: string[];
    priority_actions: string[];
    selection_hints?: {
        recommended_projects?: string[];
        recommended_skills?: string[];
        rewrite_focus?: string[];
    };
}

export type ResumeWorkspaceWarning = { node?: string; message?: string } | string;

/** The terminal result returned by the backend's unified resume workspace AgentRun. */
export interface ResumeWorkspaceResult {
    success: true;
    competition_analysis: ResumeAnalyzeResult;
    jd_matching: JDMatchResult;
    content_optimization: ResumeOptimizeResult;
    result_id: number;
    review: ResumeReviewState;
    warnings: ResumeWorkspaceWarning[];
}

export interface CompletedSession {
    session_id: string;
    title: string;
    updated_at: string;
    round_index: number;
    round_type: string;
    message_count: number;
}

export interface ApiConfig {
    smart: {
        api_key: string;
        base_url: string;
        model: string;
    };
    fast: {
        api_key: string;
        base_url: string;
        model: string;
    };
}

export interface GeneratedResumeItem {
    id: number;
    title: string;
    job_description?: string;
    created_at: string;
    content?: string; // 详情时返回
}

export interface ResumeGenerateInitResponse {
    success: boolean;
    session_id: string;
    needs_input: boolean;
    questions?: string[];
    result?: {
        resume_id: number;
        title: string;
        content: string;
    };
    message?: string;
}

export interface ResumeGenerateSubmitResponse {
    success: boolean;
    resume_id?: number;
    title?: string;
    content?: string;
    message?: string;
}

export interface GenerationSessionStatus {
    session_id: string;
    status: string;
    questions: string[];
    user_answers: Record<string, string>;
    final_markdown?: string;
}

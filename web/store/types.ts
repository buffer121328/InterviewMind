/**
 * Store Types & Constants
 * 
 * 所有 store 相关的类型定义和常量配置
 */

import { JsonObject, ResumeAnalyzeResult, ResumeOptimizeResult } from '@/lib/api/resume';
import { API_BASE_URL as NORMALIZED_API_BASE_URL } from '@/lib/api/config';

// ============================================================================
// 类型定义
// ============================================================================

export type InterviewType = 'tech_initial' | 'tech_deep' | 'hr_comprehensive';

export interface Message {
    role: 'user' | 'assistant' | 'system';
    content: string;
    timestamp: string;
    audio_url?: string;
}

export interface SessionMetadata {
    mode: 'mock' | 'voice';
    resume_filename?: string;
    job_description?: string;
    question_count: number;
    max_questions: number;
    status: 'active' | 'completed' | 'archived';
    pinned?: boolean;
    round_index?: number;
    round_type?: InterviewType | string;
}

export interface InterviewSession {
    session_id: string;
    title: string;
    created_at: string;
    updated_at: string;
    metadata: SessionMetadata;
    messages: Message[];
}

export interface SessionListItem {
    session_id: string;
    title: string;
    created_at: string;
    updated_at: string;
    mode: 'mock' | 'voice';
    status: 'active' | 'completed' | 'archived';
    message_count: number;
    question_count: number;
    pinned?: boolean;
    round_index?: number;
    round_type?: InterviewType | string;
}

export interface ResumeInfo {
    filename: string;
    original_name: string;
    content: string;
}

export interface ModelConfig {
    id: string;
    name: string;
    provider: string;
    apiKey: string;
    baseUrl: string;
    model: string;
    createdAt: string;
}

export interface ApiConfig {
    models: ModelConfig[];
    smartModelId: string;
    fastModelId: string;
    reasoningPoolModelIds: string[];
    fastPoolModelIds: string[];
    // 简历工具专家模型
    generalModelId: string;        // 通用任务（简历分析 + 主持人）
    matchAnalystModelId: string;   // 匹配分析师
    contentWriterModelId: string;  // 内容优化师
    hrReviewerModelId: string;     // HR审核官
    reflectorModelId: string;      // 质量审核
    voiceModelId: string;          // 语音面试 (Qwen3-Omni)
    ragEmbeddingModelId: string;   // RAG 向量检索 Embedding
    mem0LlmModelId: string;        // mem0 记忆提取 LLM
    mem0EmbedderModelId: string;   // mem0 语义检索 Embedding
}

export interface InterviewProgress {
    current: number;
    total: number;
}

export type ExecutionPlanStepStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface ExecutionPlanStep {
    id: string;
    title: string;
    status: ExecutionPlanStepStatus;
}

export interface ResumeResultItem {
    id: number;
    user_id: string;
    result_type: 'analyze' | 'optimize';
    resume_content: string;
    job_description: string | null;
    session_ids: string[];
    include_profile: boolean;
    result_data: ResumeAnalyzeResult | ResumeOptimizeResult;
    created_at: string;
}

export interface ResumeResultSummary {
    id: number;
    result_type: 'analyze' | 'optimize';
    resume_preview: string;
    job_description: string | null;
    session_ids: string[];
    include_profile: boolean;
    created_at: string;
}

// ============================================================================
// 阶段 0 预留类型 - 后续阶段使用
// ============================================================================

/**
 * JD 匹配分析结果项
 * 对应表: jd_analysis_results
 * 阶段 1 实现
 */
export interface JDMatchResultItem {
    id: number;
    user_id: string;
    resume_source_type: 'uploaded_resume' | 'generated_resume' | 'manual_input';
    resume_source_id: number | null;
    job_description: string;
    analysis_result: {
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
    };
    created_at: string;
}

/**
 * 候选人素材项
 * 对应表: candidate_materials
 * 阶段 1 实现
 */
export interface CandidateMaterialItem {
    id: number;
    user_id: string;
    material_type: 'tech_stack' | 'project' | 'internship' | 'work_experience' | 'education' | 'certificate' | 'highlight';
    title: string;
    content: string;
    structured_data: JsonObject;
    tags: string[];
    source_type: 'manual' | 'import' | 'ai_extract';
    source_resume_id: number | null;
    importance_score: number;
    confidence_score: number;
    is_verified: boolean;
    created_at: string;
    updated_at: string;
}

/**
 * 简历组装结果项
 * 对应表: resume_assembly_results
 * 阶段 1 实现
 */
export interface ResumeAssemblyResultItem {
    id: number;
    user_id: string;
    job_description: string;
    selected_material_ids: number[];
    selection_reason: string;
    assembled_outline: JsonObject;
    generated_resume_id: number | null;
    created_at: string;
}

/**
 * 项目经历重写记录项
 * 对应表: project_rewrite_records
 * 阶段 1 实现
 */
export interface ProjectRewriteRecordItem {
    id: number;
    user_id: string;
    material_id: number | null;
    project_title: string;
    original_content: string;
    rewrite_mode: 'star_rewrite' | 'quantify_results' | 'jd_customize' | 'followup_prediction';
    job_description: string | null;
    result_data: {
        rewritten_content: string;
        rewrite_reason: string;
        suggested_data_points: string[];
        possible_followup_questions: string[];
        should_update_material: boolean;
        inferred_content: string[] | null;
    };
    created_at: string;
}

/**
 * 面试短板报告项
 * 对应表: interview_weakness_reports
 * 阶段 2 实现
 */
export interface WeaknessReportItem {
    id: number;
    user_id: string;
    session_id: string;
    series_id: string | null;
    report_data: {
        weakness_categories: Array<{
            category: string;
            description: string;
            severity: 'high' | 'medium' | 'low';
        }>;
        question_failures: Array<{
            question: string;
            user_answer: string;
            issue: string;
            better_example: string;
        }>;
        improvement_actions: Array<{
            action: string;
            priority: number;
            estimated_effort: string;
        }>;
        recommended_questions: string[];
    };
    created_at: string;
    updated_at: string;
}

/**
 * 求职投递记录项
 * 对应表: job_applications
 * 阶段 2 实现
 */
export interface JobApplicationItem {
    id: number;
    user_id: string;
    company_name: string;
    job_title: string;
    job_description: string | null;
    channel: string | null;
    resume_version_id: number | null;
    latest_status: 'saved' | 'applied' | 'interview' | 'offer' | 'rejected' | 'accepted';
    priority: 'high' | 'medium' | 'low';
    notes: string | null;
    created_at: string;
    updated_at: string;
}

/**
 * 投递事件项
 * 对应表: application_events
 * 阶段 2 实现
 */
export interface ApplicationEventItem {
    id: number;
    application_id: number;
    event_type: 'applied' | 'phone_screen' | 'technical' | 'behavioral' | 'final' | 'offer' | 'rejected' | 'accepted' | 'note';
    event_time: string;
    event_data: JsonObject;
    created_at: string;
}

/**
 * 题库条目项
 * 对应表: question_bank_items
 * 阶段 3 实现
 */
export interface QuestionBankItem {
    id: number;
    user_id: string;
    source_type: 'manual' | 'generated' | 'imported';
    source_id?: string;
    origin_session_id?: string;
    question_text: string;
    reference_answer?: string;
    tags: string[];
    difficulty: 'easy' | 'medium' | 'hard';
    target_skill?: string;
    question_type: 'intro' | 'tech' | 'behavior' | 'system_design';
    is_verified: boolean;
    usage_count: number;
    created_at: string;
    updated_at: string;
}

/**
 * 题库导入记录项
 * 对应表: question_bank_imports
 * 阶段 3 实现
 */
export interface QuestionBankImportItem {
    id: number;
    user_id: string;
    import_source: string;
    import_status: 'pending' | 'processing' | 'completed' | 'failed';
    file_name?: string;
    total_count: number;
    success_count: number;
    summary?: string;
    created_at: string;
}

// ============================================================================
// 常量配置
// ============================================================================

// API 提供商配置 (2025年最新模型)
export const API_PROVIDERS = [
    { id: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', apiKeyUrl: 'https://platform.openai.com/api-keys', models: ['gpt-5.2', 'gpt-5.1', 'gpt-5-mini', 'gpt-4o-mini', 'gpt-4o'] },
    { id: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', apiKeyUrl: 'https://platform.deepseek.com/api_keys', models: ['deepseek-v4-flash', 'deepseek-v4-pro'] },
    { id: 'zhipu', name: '智谱 AI', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', apiKeyUrl: 'https://open.bigmodel.cn/usercenter/apikeys', models: ['glm-5', 'glm-4.7', 'glm-4.6', 'glm-4.7-flash'] },
    { id: 'aliyun', name: '阿里云百炼 (含语音配置，新用户实名赠送百万token)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', apiKeyUrl: 'https://bailian.console.aliyun.com/#/api-key', models: ['text-embedding-v4', 'qwen3-omni-flash-2025-12-01', 'qwen3-max', 'qwen3-235b-a22b-instruct-2507', 'deepseek-v3.2', 'Moonshot-Kimi-K2-Instruct', 'qwen3-next-80b-a3b-instruct', 'qwen3-30b-a3b-instruct-2507'] },
    { id: 'moonshot', name: 'Moonshot', baseUrl: 'https://api.moonshot.cn/v1', apiKeyUrl: 'https://platform.moonshot.cn/console/api-keys', models: ['kimi-k2.5', 'kimi-k2-turbo-preview', 'kimi-k2'] },
    { id: 'siliconflow', name: 'SiliconFlow', baseUrl: 'https://api.siliconflow.cn/v1', apiKeyUrl: 'https://cloud.siliconflow.cn/account/ak', models: ['deepseek-ai/DeepSeek-V3.2', 'MiniMaxAI/MiniMax-M2', 'zai-org/GLM-4.7', 'moonshotai/Kimi-K2-Instruct-0905'] },
    { id: 'modelscope', name: '魔搭社区（免费，含资源限制，且需关联阿里云百炼）', baseUrl: 'https://api-inference.modelscope.cn/v1', apiKeyUrl: 'https://www.modelscope.cn/my/myaccesstoken', models: ['deepseek-ai/DeepSeek-V3.2', 'XiaomiMiMo/MiMo-V2-Flash', 'Qwen/Qwen3-Coder-480B-A35B-Instruct', 'Qwen/Qwen3-235B-A22B-Instruct-2507'] },
    { id: 'aiping', name: 'AI Ping ', baseUrl: 'https://aiping.cn/api/v1', apiKeyUrl: 'https://www.aiping.cn/user/apikey', models: ['GLM-5', 'DeepSeek-V3.2', 'Qwen3-235B-A22B', 'MiMo-V2-Flash'] },
    { id: 'custom', name: '自定义', baseUrl: '', apiKeyUrl: '', models: [] },
];

export const DEFAULT_API_CONFIG: ApiConfig = {
    models: [],
    smartModelId: '',
    fastModelId: '',
    reasoningPoolModelIds: [],
    fastPoolModelIds: [],
    generalModelId: '',
    matchAnalystModelId: '',
    contentWriterModelId: '',
    hrReviewerModelId: '',
    reflectorModelId: '',
    voiceModelId: '',
    ragEmbeddingModelId: '',
    mem0LlmModelId: '',
    mem0EmbedderModelId: '',
};

export const API_BASE_URL = NORMALIZED_API_BASE_URL;

// ============================================================================
// 辅助函数
// ============================================================================

export function maskApiKey(key: string): string {
    if (!key || key.length < 8) return '****';
    return key.slice(0, 4) + '****' + key.slice(-4);
}

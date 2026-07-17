/**
 * 简历工具 API 接口
 */

import { apiRequest } from './config';
import { createResumeOptimizeRun, pollAgentRun, type AgentRun } from './agentRuns';
import type { ApiConfig, CompletedSession, GeneratedResumeItem, ResumeAnalyzeResult, ResumeGenerateInitResponse, ResumeGenerateSubmitResponse, ResumeOptimizeResult } from './resumeTypes';

// ============================================================================
// 类型定义
// ============================================================================

export type { JsonObject, DimensionScore, ResumeAnalyzeResult, OptimizedSection, KeyImprovement, ResumeChangeItem, ResumeOptimizeResult, CompletedSession, ApiConfig, GeneratedResumeItem, ResumeGenerateInitResponse, ResumeGenerateSubmitResponse, GenerationSessionStatus } from './resumeTypes';

// ============================================================================
// API 函数
// ============================================================================

/**
 * 获取可用于简历工具的已完成会话列表
 */
export async function getCompletedSessionsForResume(limit: number = 10): Promise<CompletedSession[]> {
    try {
        const response = await apiRequest<{
            success: boolean;
            sessions: CompletedSession[];
            message?: string;
        }>(`/api/resume/sessions?limit=${limit}`);

        if (response.success) {
            return response.sessions;
        }
        return [];
    } catch (error) {
        console.error('获取已完成会话列表失败:', error);
        return [];
    }
}

/**
 * 简历竞争力分析
 */
export async function analyzeResume(params: {
    resume_content: string;
    job_description?: string;
    session_ids?: string[];
    api_config: ApiConfig;
}): Promise<{
    success: boolean;
    result?: ResumeAnalyzeResult;
    result_id?: number;
    message?: string;
}> {
    try {
        return await apiRequest('/api/resume/analyze', {
            method: 'POST',
            body: JSON.stringify({
                resume_content: params.resume_content,
                job_description: params.job_description || null,
                session_ids: params.session_ids || [],
                api_config: params.api_config,
            }),
        });
    } catch (error) {
        console.error('简历分析失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '分析失败',
        };
    }
}

/**
 * 简历内容优化
 */
export async function optimizeResume(params: {
    resume_content: string;
    job_description: string;
    session_ids?: string[];
    include_overall_profile?: boolean;
    api_config: ApiConfig;
}): Promise<{
    success: boolean;
    result?: ResumeOptimizeResult;
    result_id?: number;
    message?: string;
}> {
    try {
        return await apiRequest('/api/resume/optimize', {
            method: 'POST',
            body: JSON.stringify({
                resume_content: params.resume_content,
                job_description: params.job_description,
                session_ids: params.session_ids || [],
                include_overall_profile: params.include_overall_profile || false,
                api_config: params.api_config,
            }),
        });
    } catch (error) {
        console.error('简历优化失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '优化失败',
        };
    }
}

/**
 * 获取历史结果列表
 */
export async function getResumeResults(
    resultType?: 'analyze' | 'optimize',
    limit: number = 20,
    offset: number = 0,
): Promise<{
    success: boolean;
    results: Array<{
        id: number;
        result_type: 'analyze' | 'optimize';
        resume_preview: string;
        job_description: string | null;
        session_ids: string[];
        include_profile: boolean;
        created_at: string;
    }>;
    total: number;
    limit: number;
    offset: number;
}> {
    try {
        const params = new URLSearchParams({
            limit: String(limit),
            offset: String(offset),
            include_data: 'false',
        });
        if (resultType) params.append('result_type', resultType);

        return await apiRequest(`/api/resume/results?${params}`);
    } catch (error) {
        console.error('获取历史结果失败:', error);
        return { success: false, results: [], total: 0, limit, offset };
    }
}

/**
 * 删除结果
 */
export async function deleteResumeResult(resultId: number): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/results/${resultId}`, {
            method: 'DELETE',
        });
        return response.success;
    } catch (error) {
        console.error('删除结果失败:', error);
        return false;
    }
}

/**
 * 获取历史结果详情
 * GET /api/resume/results/{result_id}
 */
export async function getResumeResultDetail(resultId: number): Promise<{
    id: number;
    user_id: string;
    result_type: 'analyze' | 'optimize';
    resume_content: string;
    created_at: string;
    result_data: ResumeAnalyzeResult | ResumeOptimizeResult;
    job_description: string | null;
    session_ids: string[];
    include_profile: boolean;
} | null> {
    try {
        const response = await apiRequest<{
            success: boolean;
            result: {
                id: number;
                user_id: string;
                result_type: 'analyze' | 'optimize';
                resume_content: string;
                created_at: string;
                result_data: ResumeAnalyzeResult | ResumeOptimizeResult;
                job_description: string | null;
                session_ids: string[];
                include_profile: boolean;
            };
        }>(`/api/resume/results/${resultId}`);
        return response.result;
    } catch (error) {
        console.error('获取结果详情失败:', error);
        return null;
    }
}

// ============================================================================
// SSE 流式接口类型
// ============================================================================

export interface OptimizeProgressEvent {
    type: 'progress';
    stage: string;
    message: string;
    complete?: boolean;
}

export interface OptimizeResultEvent {
    type: 'result';
    data: ResumeOptimizeResult;
}

export interface OptimizeDoneEvent {
    type: 'done';
    content: string;
    result_id?: number;
}

export interface OptimizeErrorEvent {
    type: 'error';
    content: string;
}

export interface OptimizeWarningEvent {
    type: 'warning';
    node: string;
    message: string;
}

export type OptimizeStreamEvent = OptimizeProgressEvent | OptimizeResultEvent | OptimizeDoneEvent | OptimizeErrorEvent | OptimizeWarningEvent;

/**
 * 简历内容优化 (SSE 流式)
 * 
 * @param params 优化参数
 * @param onProgress 进度回调
 * @param onWarning 警告回调（当节点失败时调用）
 * @returns 最终结果
 */
export async function optimizeResumeStreaming(
    params: {
        resume_content: string;
        job_description: string;
        session_ids?: string[];
        include_overall_profile?: boolean;
        api_config: ApiConfig;
    },
    onProgress?: (event: OptimizeProgressEvent) => void,
    onWarning?: (event: OptimizeWarningEvent) => void
): Promise<{
    success: boolean;
    result?: ResumeOptimizeResult;
    result_id?: number;
    message?: string;
    warnings?: Array<{ node: string; message: string }>;
}> {
    try {
        const created = await createResumeOptimizeRun({
            resume_content: params.resume_content,
            job_description: params.job_description,
            session_ids: params.session_ids || [],
            include_overall_profile: params.include_overall_profile || false,
            api_config: params.api_config,
        });
        let completed: AgentRun | { status: 'succeeded'; result: Record<string, unknown> } = created;
        if ('run_id' in created) {
            completed = await pollAgentRun(created.run_id, run => {
                const runningStep = run.plan.find(step => step.status === 'running');
                onProgress?.({
                    type: 'progress',
                    stage: run.stage,
                    message: runningStep?.title || (run.status === 'queued' ? '任务正在排队' : run.title),
                    complete: run.status === 'succeeded',
                });
            });
        }

        if (completed.status !== 'succeeded' || !completed.result) {
            const errorMessage = 'error_message' in completed ? completed.error_message : null;
            return { success: false, message: errorMessage || '简历优化任务未完成' };
        }

        const taskResult = completed.result as {
            success?: boolean;
            result?: ResumeOptimizeResult;
            result_id?: number;
            warnings?: Array<{ node?: string; message?: string } | string>;
        };
        const warnings = (taskResult.warnings || []).map((warning, index) => (
            typeof warning === 'string'
                ? { node: `pipeline-${index + 1}`, message: warning }
                : { node: warning.node || `pipeline-${index + 1}`, message: warning.message || '节点执行异常' }
        ));
        warnings.forEach(warning => onWarning?.({ type: 'warning', ...warning }));
        return {
            success: taskResult.success !== false && Boolean(taskResult.result),
            result: taskResult.result,
            result_id: taskResult.result_id,
            warnings: warnings.length > 0 ? warnings : undefined,
            message: taskResult.result ? undefined : '未收到优化结果',
        };

    } catch (error) {
        console.error('可恢复简历优化失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '优化失败',
        };
    }
}

// ============================================================================
// 简历生成 API
// ============================================================================

/**
 * 初始化简历生成
 */
export async function initResumeGeneration(params: {
    resume_content: string;
    job_description: string;
    optimization_result: ResumeOptimizeResult;
    optimization_result_id?: number;
    template_style?: string;
    api_config: ApiConfig;
}): Promise<ResumeGenerateInitResponse> {
    try {
        return await apiRequest('/api/resume/generation/init', {
            method: 'POST',
            body: JSON.stringify({
                ...params,
                template_style: params.template_style || 'professional'
            }),
        });
    } catch (error) {
        console.error('初始化简历生成失败:', error);
        return {
            success: false,
            session_id: '',
            needs_input: false,
            message: error instanceof Error ? error.message : '初始化失败',
        };
    }
}

/**
 * 提交生成问答
 */
export async function submitGenerationAnswers(params: {
    session_id: string;
    answers: Record<string, string>;
    api_config: ApiConfig;
}): Promise<ResumeGenerateSubmitResponse> {
    try {
        return await apiRequest('/api/resume/generation/submit', {
            method: 'POST',
            body: JSON.stringify(params),
        });
    } catch (error) {
        console.error('提交回答失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '提交失败',
        };
    }
}

/**
 * 获取生成的简历列表
 */
export async function getGeneratedResumes(limit: number = 20): Promise<GeneratedResumeItem[]> {
    try {
        const response = await apiRequest<{
            success: boolean;
            resumes: GeneratedResumeItem[];
        }>(`/api/resume/generated?limit=${limit}`);

        if (response.success) {
            return response.resumes;
        }
        return [];
    } catch (error) {
        console.error('获取已生成简历列表失败:', error);
        return [];
    }
}

/**
 * 获取单个简历详情
 */
export async function getGeneratedResume(resumeId: number): Promise<GeneratedResumeItem | null> {
    try {
        const response = await apiRequest<{
            success: boolean;
            resume: GeneratedResumeItem;
        }>(`/api/resume/generated/${resumeId}`);

        if (response.success) {
            return response.resume;
        }
        return null;
    } catch (error) {
        console.error('获取简历详情失败:', error);
        return null;
    }
}


/**
 * 删除已生成的简历
 */
export async function deleteGeneratedResume(resumeId: number): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/generated/${resumeId}`, {
            method: 'DELETE',
        });
        return response.success;
    } catch (error) {
        console.error('删除简历失败:', error);
        return false;
    }
}

/**
 * 更新已生成的简历内容
 */
export async function updateGeneratedResume(resumeId: number, content: string, title?: string): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/generated/${resumeId}`, {
            method: 'PUT',
            body: JSON.stringify({ content, title }),
        });
        return response.success;
    } catch (error) {
        console.error('更新简历失败:', error);
        return false;
    }
}


// ============================================================================
// JD 匹配分析 API
// ============================================================================

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

export interface JDMatchHistoryItem {
    id: number;
    resume_source_type: string;
    resume_source_id: number | null;
    job_description: string;
    created_at: string;
}

/**
 * JD 匹配分析
 */
export async function analyzeJDMatch(params: {
    resume_content: string;
    job_description: string;
    resume_source_type?: string;
    resume_source_id?: number;
    api_config: ApiConfig;
}): Promise<{
    success: boolean;
    result?: JDMatchResult;
    analysis_id?: number;
    message?: string;
}> {
    try {
        return await apiRequest('/api/resume/jd-match', {
            method: 'POST',
            body: JSON.stringify({
                resume_content: params.resume_content,
                job_description: params.job_description,
                resume_source_type: params.resume_source_type || 'manual_input',
                resume_source_id: params.resume_source_id || null,
                api_config: params.api_config,
            }),
        });
    } catch (error) {
        console.error('JD 匹配分析失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '分析失败',
        };
    }
}

/**
 * 获取 JD 匹配分析历史列表
 */
export async function getJDMatchHistory(limit: number = 20): Promise<{
    success: boolean;
    results: JDMatchHistoryItem[];
    message?: string;
}> {
    try {
        return await apiRequest(`/api/resume/jd-match?limit=${limit}`);
    } catch (error) {
        console.error('获取 JD 分析历史失败:', error);
        return { success: false, results: [] };
    }
}

/**
 * 获取单个 JD 匹配分析结果详情
 */
export async function getJDMatchDetail(analysisId: number): Promise<{
    success: boolean;
    result?: {
        id: number;
        user_id: string;
        resume_source_type: string;
        resume_source_id: number | null;
        resume_content_snapshot: string;
        job_description: string;
        analysis_result: JDMatchResult;
        created_at: string;
    };
    message?: string;
}> {
    try {
        return await apiRequest(`/api/resume/jd-match/${analysisId}`);
    } catch (error) {
        console.error('获取 JD 分析详情失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '获取失败' };
    }
}

/**
 * 删除 JD 匹配分析结果
 */
export async function deleteJDMatchResult(analysisId: number): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/jd-match/${analysisId}`, {
            method: 'DELETE',
        });
        return response.success;
    } catch (error) {
        console.error('删除 JD 分析结果失败:', error);
        return false;
    }
}

export * from './resumeMaterials';

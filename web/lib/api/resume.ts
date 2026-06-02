/**
 * 简历工具 API 接口
 */

import { apiRequest, API_BASE_URL, getUserId } from './config';

// ============================================================================
// 类型定义
// ============================================================================

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
}

export interface KeyImprovement {
    priority: number;
    area: string;
    issue: string;
    action: string;
    example?: string;
}

export interface ResumeOptimizeResult {
    match_score: number;
    hr_pass_rate: number;
    optimized_sections: OptimizedSection[];
    key_improvements: KeyImprovement[];
    keyword_analysis?: {
        jd_keywords: string[];
        matched: string[];
        missing: string[];
        bonus: string[];
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
export async function getResumeResults(resultType?: 'analyze' | 'optimize', limit: number = 20): Promise<{
    success: boolean;
    results: Array<{
        id: number;
        result_type: string;
        created_at: string;
        result_data: ResumeAnalyzeResult | ResumeOptimizeResult;
    }>;
}> {
    try {
        const params = new URLSearchParams({ limit: String(limit) });
        if (resultType) params.append('result_type', resultType);

        return await apiRequest(`/api/resume/results?${params}`);
    } catch (error) {
        console.error('获取历史结果失败:', error);
        return { success: false, results: [] };
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
        const response = await fetch(`${API_BASE_URL}/api/resume/optimize/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-ID': getUserId(),
            },
            body: JSON.stringify({
                resume_content: params.resume_content,
                job_description: params.job_description,
                session_ids: params.session_ids || [],
                include_overall_profile: params.include_overall_profile || false,
                api_config: params.api_config,
            }),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
            throw new Error('无法读取响应流');
        }

        const decoder = new TextDecoder();
        let buffer = '';
        let finalResult: ResumeOptimizeResult | undefined;
        let resultId: number | undefined;
        const warnings: Array<{ node: string; message: string }> = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6)) as OptimizeStreamEvent;

                        if (event.type === 'progress' && onProgress) {
                            onProgress(event);
                        } else if (event.type === 'warning') {
                            warnings.push({ node: event.node, message: event.message });
                            if (onWarning) {
                                onWarning(event);
                            }
                        } else if (event.type === 'result') {
                            finalResult = event.data;
                        } else if (event.type === 'done') {
                            resultId = event.result_id;
                        } else if (event.type === 'error') {
                            throw new Error(event.content);
                        }
                    } catch (e) {
                        // 只忽略 JSON 解析错误，其他错误应该抛出
                        if (e instanceof SyntaxError) {
                            console.warn('SSE 解析跳过:', line);
                        } else {
                            throw e;
                        }
                    }
                }
            }
        }

        if (finalResult) {
            return { success: true, result: finalResult, result_id: resultId, warnings: warnings.length > 0 ? warnings : undefined };
        } else {
            return { success: false, message: '未收到优化结果', warnings: warnings.length > 0 ? warnings : undefined };
        }

    } catch (error) {
        console.error('流式简历优化失败:', error);
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


// ============================================================================
// 候选人素材库 API
// ============================================================================

/**
 * 素材类型
 */
export type MaterialType = 'tech_stack' | 'project' | 'internship' | 'work_experience' | 'education' | 'certificate' | 'highlight';

/**
 * 素材项
 */
export interface CandidateMaterial {
    id: number;
    user_id: string;
    material_type: MaterialType;
    title: string;
    content: string;
    structured_data: Record<string, any>;
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
 * 创建素材
 */
export async function createMaterial(data: {
    material_type: MaterialType;
    title: string;
    content: string;
    structured_data?: Record<string, any>;
    tags?: string[];
    source_type?: string;
    source_resume_id?: number;
    importance_score?: number;
    confidence_score?: number;
    is_verified?: boolean;
}): Promise<{ success: boolean; material_id?: number; message?: string }> {
    try {
        return await apiRequest('/api/resume/materials', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    } catch (error) {
        console.error('创建素材失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '创建失败' };
    }
}

/**
 * 从简历导入素材
 */
export async function importMaterialsFromResume(
    resumeContent: string,
    apiConfig: any
): Promise<{ success: boolean; material_ids?: number[]; message?: string }> {
    try {
        return await apiRequest('/api/resume/materials/import', {
            method: 'POST',
            body: JSON.stringify({
                resume_content: resumeContent,
                api_config: apiConfig,
            }),
        });
    } catch (error) {
        console.error('导入素材失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '导入失败' };
    }
}

/**
 * 获取素材列表
 */
export async function getMaterials(
    materialType?: MaterialType,
    isVerified?: boolean,
    limit?: number,
    offset?: number
): Promise<{ success: boolean; materials: CandidateMaterial[]; message?: string }> {
    try {
        const params = new URLSearchParams();
        if (materialType) params.append('material_type', materialType);
        if (isVerified !== undefined) params.append('is_verified', String(isVerified));
        if (limit) params.append('limit', String(limit));
        if (offset) params.append('offset', String(offset));
        
        const queryString = params.toString();
        const url = `/api/resume/materials${queryString ? `?${queryString}` : ''}`;
        
        return await apiRequest(url);
    } catch (error) {
        console.error('获取素材列表失败:', error);
        return { success: false, materials: [], message: error instanceof Error ? error.message : '获取失败' };
    }
}

/**
 * 获取单个素材
 */
export async function getMaterial(
    materialId: number
): Promise<{ success: boolean; material?: CandidateMaterial; message?: string }> {
    try {
        return await apiRequest(`/api/resume/materials/${materialId}`);
    } catch (error) {
        console.error('获取素材失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '获取失败' };
    }
}

/**
 * 更新素材
 */
export async function updateMaterial(
    materialId: number,
    data: {
        title?: string;
        content?: string;
        structured_data?: Record<string, any>;
        tags?: string[];
        importance_score?: number;
        confidence_score?: number;
        is_verified?: boolean;
    }
): Promise<{ success: boolean; message?: string }> {
    try {
        return await apiRequest(`/api/resume/materials/${materialId}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    } catch (error) {
        console.error('更新素材失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '更新失败' };
    }
}

/**
 * 删除素材
 */
export async function deleteMaterial(materialId: number): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/materials/${materialId}`, {
            method: 'DELETE',
        });
        return response.success;
    } catch (error) {
        console.error('删除素材失败:', error);
        return false;
    }
}


// ============================================================================
// 简历组装 API
// ============================================================================

/**
 * 组装结果项
 */
export interface AssemblyResult {
    id: number;
    user_id: string;
    job_description: string;
    selected_material_ids: number[];
    selection_reason: string;
    assembled_outline: Record<string, any>;
    assembled_content: string | null;
    generated_resume_id: number | null;
    created_at: string;
}

/**
 * 组装简历
 */
export async function assembleResume(data: {
    job_description: string;
    api_config: any;
    selected_material_ids?: number[];
    material_type_filter?: MaterialType;
    max_materials?: number;
}): Promise<{
    success: boolean;
    result_id?: number;
    selected_material_ids?: number[];
    selection_reason?: string;
    assembled_outline?: Record<string, any>;
    assembled_content?: string;
    materials_used?: Array<{ id: number; type: string; title: string }>;
    message?: string;
}> {
    try {
        return await apiRequest('/api/resume/assemble', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    } catch (error) {
        console.error('简历组装失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '组装失败' };
    }
}

/**
 * 获取组装结果列表
 */
export async function getAssemblyResults(
    limit?: number
): Promise<{ success: boolean; results: AssemblyResult[]; message?: string }> {
    try {
        const url = limit ? `/api/resume/assemble?limit=${limit}` : '/api/resume/assemble';
        return await apiRequest(url);
    } catch (error) {
        console.error('获取组装结果列表失败:', error);
        return { success: false, results: [], message: error instanceof Error ? error.message : '获取失败' };
    }
}

/**
 * 获取单个组装结果
 */
export async function getAssemblyResult(
    resultId: number
): Promise<{ success: boolean; result?: AssemblyResult; message?: string }> {
    try {
        return await apiRequest(`/api/resume/assemble/${resultId}`);
    } catch (error) {
        console.error('获取组装结果失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '获取失败' };
    }
}

/**
 * 删除组装结果
 */
export async function deleteAssemblyResult(resultId: number): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/assemble/${resultId}`, {
            method: 'DELETE',
        });
        return response.success;
    } catch (error) {
        console.error('删除组装结果失败:', error);
        return false;
    }
}


// ============================================================================
// 项目经历重写 API
// ============================================================================

export type ProjectRewriteMode = 'star_rewrite' | 'quantify_results' | 'jd_customize' | 'followup_prediction';

export interface ProjectRewriteResult {
    rewritten_content: string;
    rewrite_reason: string;
    suggested_data_points: string[];
    possible_followup_questions: string[];
    should_update_material: boolean;
    inferred_content: string[] | null;
}

export interface ProjectRewriteHistoryItem {
    id: number;
    project_title: string;
    rewrite_mode: ProjectRewriteMode;
    created_at: string;
}

/**
 * 项目经历重写
 */
export async function rewriteProject(params: {
    project_content: string;
    project_title: string;
    rewrite_mode: ProjectRewriteMode;
    job_description?: string;
    material_id?: number;
    api_config: ApiConfig;
}): Promise<{
    success: boolean;
    result?: ProjectRewriteResult;
    rewrite_id?: number;
    message?: string;
}> {
    try {
        return await apiRequest('/api/resume/project-rewrite', {
            method: 'POST',
            body: JSON.stringify({
                project_content: params.project_content,
                project_title: params.project_title,
                rewrite_mode: params.rewrite_mode,
                job_description: params.job_description || null,
                material_id: params.material_id || null,
                api_config: params.api_config,
            }),
        });
    } catch (error) {
        console.error('项目重写失败:', error);
        return {
            success: false,
            message: error instanceof Error ? error.message : '重写失败',
        };
    }
}

/**
 * 获取项目重写历史列表
 */
export async function getProjectRewriteHistory(
    rewriteMode?: ProjectRewriteMode,
    limit: number = 20
): Promise<{
    success: boolean;
    records: ProjectRewriteHistoryItem[];
    message?: string;
}> {
    try {
        const params = new URLSearchParams({ limit: String(limit) });
        if (rewriteMode) params.append('rewrite_mode', rewriteMode);
        return await apiRequest(`/api/resume/project-rewrite?${params}`);
    } catch (error) {
        console.error('获取项目重写历史失败:', error);
        return { success: false, records: [] };
    }
}

/**
 * 获取单个项目重写详情
 */
export async function getProjectRewriteDetail(rewriteId: number): Promise<{
    success: boolean;
    record?: {
        id: number;
        user_id: string;
        material_id: number | null;
        project_title: string;
        original_content: string;
        rewrite_mode: string;
        job_description: string | null;
        result_data: ProjectRewriteResult;
        created_at: string;
    };
    message?: string;
}> {
    try {
        return await apiRequest(`/api/resume/project-rewrite/${rewriteId}`);
    } catch (error) {
        console.error('获取项目重写详情失败:', error);
        return { success: false, message: error instanceof Error ? error.message : '获取失败' };
    }
}

/**
 * 删除项目重写记录
 */
export async function deleteProjectRewrite(rewriteId: number): Promise<boolean> {
    try {
        const response = await apiRequest<{ success: boolean }>(`/api/resume/project-rewrite/${rewriteId}`, {
            method: 'DELETE',
        });
        return response.success;
    } catch (error) {
        console.error('删除项目重写记录失败:', error);
        return false;
    }
}


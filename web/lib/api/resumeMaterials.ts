/**
 * 简历素材、组装与项目重写 API
 */

import { apiRequest } from './config';
import type { ApiConfig, JsonObject } from './resumeTypes';

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
 * 创建素材
 */
export async function createMaterial(data: {
    material_type: MaterialType;
    title: string;
    content: string;
    structured_data?: JsonObject;
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
    apiConfig: unknown
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
        structured_data?: JsonObject;
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
    assembled_outline: JsonObject;
    assembled_content: string | null;
    generated_resume_id: number | null;
    created_at: string;
}

/**
 * 组装简历
 */
export async function assembleResume(data: {
    job_description: string;
    api_config: unknown;
    selected_material_ids?: number[];
    material_type_filter?: MaterialType;
    max_materials?: number;
}): Promise<{
    success: boolean;
    result_id?: number;
    selected_material_ids?: number[];
    selection_reason?: string;
    assembled_outline?: JsonObject;
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

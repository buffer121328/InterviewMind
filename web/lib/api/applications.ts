/**
 * 投递追踪 API 模块
 * 统一管理岗位投递记录和事件流水的 API 调用
 */

import { apiRequest } from './config';

// ============================================================================
// 类型定义
// ============================================================================

export interface ApplicationEvent {
    id: number;
    application_id: number;
    event_type: string;
    event_time: string;
    event_data: Record<string, unknown>;
    created_at: string;
}

export interface JobApplication {
    id: number;
    user_id: string;
    company_name: string;
    job_title: string;
    job_description: string | null;
    channel: string | null;
    generated_resume_id: number | null;
    latest_status: string;
    priority: string;
    notes: string | null;
    created_at: string;
    updated_at: string;
    events: ApplicationEvent[];
}

export interface JobApplicationListItem {
    id: number;
    company_name: string;
    job_title: string;
    channel: string | null;
    generated_resume_id: number | null;
    latest_status: string;
    priority: string;
    notes: string | null;
    created_at: string;
    updated_at: string;
}

export interface CreateApplicationRequest {
    company_name: string;
    job_title: string;
    job_description?: string;
    channel?: string;
    generated_resume_id?: number;
    latest_status?: string;
    priority?: string;
    notes?: string;
}

export interface UpdateApplicationRequest {
    company_name?: string;
    job_title?: string;
    job_description?: string;
    channel?: string;
    generated_resume_id?: number;
    latest_status?: string;
    priority?: string;
    notes?: string;
}

export interface CreateEventRequest {
    event_type: string;
    event_time?: string;
    event_data?: Record<string, unknown>;
}

// ============================================================================
// API 函数
// ============================================================================

/**
 * 获取投递记录列表
 */
export async function fetchApplications(
    status?: string,
    limit: number = 50,
    offset: number = 0
): Promise<{ applications: JobApplicationListItem[]; total: number; limit: number; offset: number }> {
    try {
        const params = new URLSearchParams();
        if (status) params.append('status', status);
        params.append('limit', String(limit));
        params.append('offset', String(offset));

        const response = await apiRequest<{
            success: boolean;
            applications: JobApplicationListItem[];
            total: number;
            limit: number;
            offset: number;
        }>(`/api/applications/?${params}`);

        return {
            applications: response.applications || [],
            total: response.total || 0,
            limit: response.limit ?? limit,
            offset: response.offset ?? offset,
        };
    } catch (error) {
        console.error('获取投递列表失败:', error);
        return { applications: [], total: 0, limit, offset };
    }
}

/**
 * 获取投递记录详情（含事件列表）
 */
export async function getApplicationDetail(
    applicationId: number
): Promise<JobApplication | null> {
    try {
        const response = await apiRequest<{
            success: boolean;
            application: JobApplication;
        }>(`/api/applications/${applicationId}`);

        return response.application;
    } catch (error) {
        console.error('获取投递详情失败:', error);
        return null;
    }
}

/**
 * 创建投递记录
 */
export async function createApplication(
    data: CreateApplicationRequest
): Promise<JobApplication | null> {
    try {
        const response = await apiRequest<{
            success: boolean;
            application: JobApplication;
        }>('/api/applications/', {
            method: 'POST',
            body: JSON.stringify(data),
        });

        return response.application;
    } catch (error) {
        console.error('创建投递记录失败:', error);
        return null;
    }
}

/**
 * 更新投递记录
 */
export async function updateApplication(
    applicationId: number,
    data: UpdateApplicationRequest
): Promise<JobApplication | null> {
    try {
        const response = await apiRequest<{
            success: boolean;
            application: JobApplication;
        }>(`/api/applications/${applicationId}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });

        return response.application;
    } catch (error) {
        console.error('更新投递记录失败:', error);
        return null;
    }
}

/**
 * 删除投递记录
 */
export async function deleteApplication(
    applicationId: number
): Promise<boolean> {
    try {
        await apiRequest<{ success: boolean }>(
            `/api/applications/${applicationId}`,
            { method: 'DELETE' }
        );
        return true;
    } catch (error) {
        console.error('删除投递记录失败:', error);
        return false;
    }
}

/**
 * 添加投递事件
 */
export async function addApplicationEvent(
    applicationId: number,
    data: CreateEventRequest
): Promise<ApplicationEvent | null> {
    try {
        const response = await apiRequest<{
            success: boolean;
            event: ApplicationEvent;
        }>(`/api/applications/${applicationId}/events`, {
            method: 'POST',
            body: JSON.stringify(data),
        });

        return response.event;
    } catch (error) {
        console.error('添加投递事件失败:', error);
        return null;
    }
}

/**
 * 获取投递事件列表
 */
export async function fetchApplicationEvents(
    applicationId: number
): Promise<ApplicationEvent[]> {
    try {
        const response = await apiRequest<{
            success: boolean;
            events: ApplicationEvent[];
        }>(`/api/applications/${applicationId}/events`);

        return response.events || [];
    } catch (error) {
        console.error('获取投递事件失败:', error);
        return [];
    }
}

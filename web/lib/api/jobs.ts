/**
 * 岗位自动化 API 接口
 *
 * 对应后端 backend/app/api/jobs.py，路径前缀 /api/jobs
 *
 * 主要功能：
 * 1. 单个岗位采集：从 URL 或手动 JD 文本提取结构化信息
 * 2. 列表/详情/删除：管理已采集岗位
 * 3. 批量推荐采集（BOSS 半自动化）：搜索页抓取前 N 个 + 匹配度排序 + 生成投递资产
 */

import { apiRequest, getUserId } from './config';

// ============================================================================
// 类型定义
// ============================================================================

export interface ApiChannelConfig {
    api_key: string;
    base_url: string;
    model: string;
}

export interface ApiConfig {
    smart?: ApiChannelConfig;
    fast?: ApiChannelConfig;
    general?: ApiChannelConfig;
    match_analyst?: ApiChannelConfig;
    content_writer?: ApiChannelConfig;
    hr_reviewer?: ApiChannelConfig;
    reflector?: ApiChannelConfig;
}

export interface JobCaptureRequest {
    /** 岗位链接（优先） */
    source_url?: string;
    /** 手动粘贴的 JD 文本（当没有 URL 时） */
    job_description?: string;
    /** 平台标识：boss / lagou / linkedin / ... */
    platform?: string;
    /** 公司名提示 */
    company_name_hint?: string;
    /** 岗位名提示 */
    job_title_hint?: string;
    /** 用户 API 配置，不传则使用后端 .env 默认 */
    api_config?: ApiConfig;
    /** 用户登录 Cookies（List[Playwright Cookie Dict]），仅 URL 采集时有效 */
    cookies?: Array<Record<string, unknown>>;
    /** 浏览器无头模式，无 cookies 时建议 false 让用户完成验证 */
    headless?: boolean;
}

export interface NormalizedJob {
    company_name: string;
    job_title: string;
    job_description: string;
    salary_text: string;
    city: string;
    [k: string]: unknown;
}

export interface JobCaptureResponse {
    success: boolean;
    message?: string;
    job_id?: number;
    normalized_job?: NormalizedJob;
    is_duplicate?: boolean;
}

export interface JobListItem {
    id: number;
    company_name: string;
    job_title: string;
    salary_text: string;
    city: string;
    captured_at: string;
    status?: string;
    [k: string]: unknown;
}

export interface JobListResponse {
    success: boolean;
    total: number;
    jobs: JobListItem[];
}

export interface JobDetailResponse {
    success: boolean;
    job: JobListItem & {
        jd_analysis?: Record<string, unknown>;
        assets?: Record<string, unknown>;
        [k: string]: unknown;
    };
}

export interface GreetingItem {
    tone: string;
    message_text: string;
    highlights_used?: string[];
    risk_notes?: string[];
}

export interface CapturedJobSummary {
    job_id: number;
    company_name: string;
    job_title: string;
    salary_text: string;
    city: string;
    match_score?: number | null;
    custom_resume_id?: number | null;
    greetings: GreetingItem[];
    risk_flags: string[];
    asset_run_id?: string | null;
    asset_status?: 'queued' | 'retrying' | 'running' | 'succeeded' | 'failed' | 'cancelled' | null;
}

export interface CaptureRecommendationsRequest {
    /** 搜索关键词，如 "Java架构师" */
    query: string;
    /** 候选人简历内容 */
    resume_content: string;
    /** 可选城市名（仅作提示，BOSS 默认按 IP 自动定位） */
    city?: string;
    /** 抓取前 N 个岗位，1-10，默认 5 */
    top_n?: number;
    /** 用户标识，也可走 X-User-ID header */
    user_id?: string;
    /** 用户自定义 API 配置 */
    api_config?: ApiConfig;
}

export interface CaptureRecommendationsResponse {
    success: boolean;
    total: number;
    jobs: CapturedJobSummary[];
    message?: string;
}

// ============================================================================
// API 调用
// ============================================================================

/**
 * 单个岗位采集
 * POST /api/jobs/capture
 */
export async function captureJob(req: JobCaptureRequest): Promise<JobCaptureResponse> {
    return apiRequest<JobCaptureResponse>('/api/jobs/capture', {
        method: 'POST',
        body: JSON.stringify(req),
    });
}

/**
 * 获取岗位列表
 * GET /api/jobs?platform=boss&limit=50&offset=0
 */
export async function listJobs(params?: {
    platform?: string;
    limit?: number;
    offset?: number;
    status?: string;
}): Promise<JobListResponse> {
    const q = new URLSearchParams();
    if (params?.platform) q.set('platform', params.platform);
    if (params?.limit != null) q.set('limit', String(params.limit));
    if (params?.offset != null) q.set('offset', String(params.offset));
    if (params?.status) q.set('status', params.status);
    const qs = q.toString();
    return apiRequest<JobListResponse>(`/api/jobs${qs ? `?${qs}` : ''}`);
}

/**
 * 获取岗位详情
 * GET /api/jobs/{job_id}
 */
export async function getJobDetail(jobId: number): Promise<JobDetailResponse> {
    return apiRequest<JobDetailResponse>(`/api/jobs/${jobId}`);
}

/**
 * 删除已采集岗位
 * DELETE /api/jobs/{job_id}
 */
export async function deleteJob(jobId: number): Promise<{ success: boolean; message?: string }> {
    return apiRequest(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

/**
 * 批量抓取 BOSS 推荐页/搜索页前 N 个岗位 + 生成投递资产
 *
 * 注意：本接口依赖 macOS + 已登录 BOSS 的 Chrome + AppleScript JS 权限。
 * 后端会在 Chrome 中新开 tab，若触发反爬验证页会最长等待 3 分钟，
 * 等用户手动完成验证后继续抓取。
 *
 * POST /api/jobs/capture-recommendations
 */
export async function captureRecommendations(
    req: CaptureRecommendationsRequest,
): Promise<CaptureRecommendationsResponse> {
    const body: CaptureRecommendationsRequest & { user_id?: string } = { ...req };
    // 同步把 user_id 也写进 body（后端可二选一接收）
    const userId = getUserId();
    if (!body.user_id) body.user_id = userId;
    return apiRequest<CaptureRecommendationsResponse>('/api/jobs/capture-recommendations', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

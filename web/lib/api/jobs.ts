/**
 * 岗位采集与投递资产 API 接口
 *
 * 对应后端 backend/app/api/jobs.py，路径前缀 /api/jobs
 *
 * 主要功能：
 * 1. 列表/详情/删除：管理已导入岗位
 * 2. 现有浏览器标签页：复用用户已登录的 Edge/Chrome BOSS 页面搜索并读取有限岗位卡片
 * 3. 复用现有登录标签页打开已入库岗位
 */

import { apiRequest } from './config';
import type { AgentRun } from './agentRunTypes';

// ============================================================================
// 类型定义
// ============================================================================

export interface ApiChannelConfig {
    credential_id: string;
    api_key?: string;
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

export interface JobListItem {
    id: number;
    company_name: string;
    company_size_text: string;
    job_title: string;
    platform: string;
    salary_text: string;
    city: string;
    source_url: string;
    match_score?: number | null;
    asset_run_id?: string | null;
    asset_status?: string | null;
    tags?: string[];
    captured_at?: string;
    status?: string;
}

export interface JobListResponse {
    success: boolean;
    total: number;
    jobs: JobListItem[];
}

export interface JobAssetPayload {
    jd_analysis?: Record<string, unknown> | null;
    custom_resume_id?: number | null;
    custom_resume_preview?: string | null;
    risk_flags?: string[];
    messages?: string[];
}

export interface JobDetail extends JobListItem {
    job_description?: string;
    source_text?: string;
    asset_payload?: JobAssetPayload | null;
}

export interface JobDetailResponse {
    success: boolean;
    job: JobDetail;
    message?: string;
}

export interface CapturedJobSummary {
    /** 入库后的岗位库 ID；采集阶段尚未入库时为 null。 */
    job_id: number | null;
    /** 采集阶段返回的待入库卡片标记。 */
    pending_import?: boolean;
    source_url?: string;
    company_name: string;
    company_size_text?: string;
    job_title: string;
    job_description?: string;
    salary_text: string;
    city: string;
    match_score?: number | null;
    custom_resume_id?: number | null;
    risk_flags: string[];
    asset_run_id?: string | null;
    asset_status?: 'queued' | 'retrying' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled' | null;
}

export interface BossDomJobCard {
    company_name: string;
    company_size_text: string;
    job_title: string;
    salary_text: string;
    city: string;
    title_summary: string;
    job_description: string;
    source_url: string;
}

export interface BossDomCapturePayload {
    kind: 'interviewmind-boss-dom-capture-v1';
    source_page_url: string;
    captured_at: string;
    cards: BossDomJobCard[];
}

export type BossBrowserChannel = 'msedge' | 'chrome';

export interface BossTabStatusResponse {
    success: boolean;
    browser_channel: BossBrowserChannel;
    browser_label: string;
    connected: boolean;
    current_url: string;
    page_status: 'search_ready' | 'search_loading' | 'login_required' | 'security_check' | 'boss_page' | 'blank' | string;
    ready_state: string;
    visible_card_count: number;
    message: string;
}

export interface BossTabCaptureRequest {
    /** 搜索关键词；后端会写入现有 BOSS 标签页。 */
    query: string;
    /** BOSS 城市代码；留空时复用当前标签页的 city 参数。 */
    city?: string;
    /** 单次 DOM 候选卡片读取上限，后端硬限制为 20。 */
    max_cards?: number;
    /** 要接管的现有浏览器渠道。 */
    browser_channel?: BossBrowserChannel;
}

export interface BossTabCaptureResponse extends BossDomCapturePayload {
    success: boolean;
    browser_channel: BossBrowserChannel;
    browser_label: string;
    page_status: string;
    ready_state: string;
    message: string;
}

export interface CaptureRecommendationsRequest {
    /** 已由现有浏览器标签页执行的搜索关键词，用于匹配度排序。 */
    query: string;
    /** 候选人简历内容。 */
    resume_content: string;
    /** 用户当前已登录的 BOSS 搜索页 URL。 */
    source_page_url: string;
    /** 后端从现有标签页提取的 1-20 张有限字段岗位卡片。 */
    cards: BossDomJobCard[];
    /** 可选城市提示，用于字段补全。 */
    city?: string;
    /** 导入前 N 个岗位，1-20，默认 3。 */
    top_n?: number;
    /** 用户自定义 API 配置。 */
    api_config?: ApiConfig;
}

/** 一键入库提交的一张待入库卡片；顺序即采集时的匹配度顺序。 */
export interface JobLibraryImportCard {
    company_name: string;
    company_size_text?: string;
    job_title: string;
    salary_text: string;
    city: string;
    title_summary?: string;
    job_description?: string;
    source_url: string;
    preliminary_match_score?: number | null;
}

export interface JobLibraryImportRequest {
    cards: JobLibraryImportCard[];
    city?: string;
}

export interface JobImportFailedItem {
    company_name: string;
    job_title: string;
    reason: string;
    source_url: string;
}

export interface JobImportResponse {
    success: boolean;
    total: number;
    duplicates: number;
    jobs: CapturedJobSummary[];
    failed: JobImportFailedItem[];
    message: string;
}

export interface BossOpenJobResponse {
    success: boolean;
    browser_channel: BossBrowserChannel;
    browser_label: string;
    opened_url: string;
    message: string;
}

// ============================================================================
// API 调用
// ============================================================================

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
 * 把用户确认的待入库卡片确定性写入岗位库。
 * 保存按来源哈希去重，重复岗位复用既有记录；不会调度模型或后台资产任务。
 *
 * POST /api/jobs/import
 */
export async function importCardsToLibrary(req: JobLibraryImportRequest): Promise<JobImportResponse> {
    return apiRequest<JobImportResponse>('/api/jobs/import', { method: 'POST', body: JSON.stringify(req) });
}

/**
 * 删除已采集岗位
 * DELETE /api/jobs/{job_id}
 */
export async function deleteJob(jobId: number): Promise<{ success: boolean; message?: string }> {
    return apiRequest(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

/**
 * 检查现有 Edge/Chrome 中已打开的 BOSS 标签页。
 * 后端不会启动浏览器、创建 profile 或读取 Cookie。
 */
export async function getBossBrowserTabStatus(
    browserChannel: BossBrowserChannel,
): Promise<BossTabStatusResponse> {
    const query = new URLSearchParams({ browser_channel: browserChannel });
    return apiRequest<BossTabStatusResponse>(`/api/jobs/browser-tab/status?${query.toString()}`);
}

/**
 * 复用现有登录标签页完成一次搜索和有限字段采集。
 * 页面检查间隔与单次卡片数由后端强制限制。
 */
export async function searchAndCaptureBossBrowserTab(
    req: BossTabCaptureRequest,
): Promise<BossTabCaptureResponse> {
    return apiRequest<BossTabCaptureResponse>('/api/jobs/browser-tab/search-and-capture', {
        method: 'POST',
        body: JSON.stringify(req),
    });
}

/**
 * 导入现有浏览器标签页提取的岗位卡片并生成投递资产。
 * 请求不包含 Cookie、HTML 或浏览器控制参数。
 *
 * POST /api/agent-runs/job-recommendation-capture
 */
export async function captureRecommendations(
    req: CaptureRecommendationsRequest,
): Promise<AgentRun> {
    return apiRequest<AgentRun>('/api/agent-runs/job-recommendation-capture', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify(req),
    });
}

/** 让宿主机服务复用现有登录 BOSS 标签页打开岗位，不创建新窗口也不执行发送。 */
export async function openJobInExistingBossTab(
    jobId: number,
    browserChannel: BossBrowserChannel,
): Promise<BossOpenJobResponse> {
    return apiRequest<BossOpenJobResponse>(`/api/jobs/${jobId}/browser-tab/open`, {
        method: 'POST',
        body: JSON.stringify({ browser_channel: browserChannel }),
    });
}

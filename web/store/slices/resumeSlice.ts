import { ResumeResultItem, ResumeResultSummary } from '../types';
import {
    getResumeResults,
    getResumeResultDetail,
    deleteResumeResult,
    getCompletedSessionsForResume,
    CompletedSession,
    GeneratedResumeItem,
    getGeneratedResumes,
    deleteGeneratedResume,
    getGeneratedResume,
    getJDMatchHistory,
    getJDMatchDetail,
    deleteJDMatchResult,
    JDMatchHistoryItem,
    CandidateMaterial,
    getMaterials,
    deleteMaterial,
    AssemblyResult,
    getAssemblyResults,
    getAssemblyResult,
    deleteAssemblyResult,
    ProjectRewriteHistoryItem,
    MaterialType,
    ProjectRewriteMode,
    getProjectRewriteHistory,
    deleteProjectRewrite,
} from '@/lib/api/resume';

// ============================================================================
// 类型定义
// ============================================================================

export interface ResumeState {
    resumeResults: ResumeResultSummary[];
    resumeResultsTotal: number;
    currentResumeResult: ResumeResultItem | null;
    resumeResultLoading: boolean;
    // 已完成会话列表（用于简历工具选择）
    completedSessions: CompletedSession[];
    completedSessionsLoading: boolean;
    completedSessionsLastFetched: number;

    // 生成的简历
    generatedResumes: GeneratedResumeItem[];
    currentGeneratedResume: GeneratedResumeItem | null;
    generatedResumesLoading: boolean;

    // JD 匹配分析历史
    jdMatchResults: JDMatchHistoryItem[];
    jdMatchResultsLoading: boolean;
    currentJDMatchDetail: import('@/lib/api/resume').JDMatchResult | null;

    // 候选人素材库
    candidateMaterials: CandidateMaterial[];
    candidateMaterialsLoading: boolean;
    currentMaterial: CandidateMaterial | null;

    // 简历组装结果
    assemblyResults: AssemblyResult[];
    assemblyResultsLoading: boolean;
    currentAssemblyResult: AssemblyResult | null;

    // 项目经历重写
    projectRewriteHistory: ProjectRewriteHistoryItem[];
    projectRewriteHistoryLoading: boolean;
}

export interface ResumeActions {
    fetchResumeResults: (resultType?: 'analyze' | 'optimize', append?: boolean) => Promise<void>;
    selectResumeResult: (resultId: number) => Promise<void>;
    deleteResumeResult: (resultId: number) => Promise<boolean>;
    clearResumeResult: () => void;
    fetchCompletedSessions: (force?: boolean) => Promise<void>;

    // 生成简历 Actions
    fetchGeneratedResumes: () => Promise<void>;
    selectGeneratedResume: (resumeId: number) => Promise<void>;
    deleteGeneratedResume: (resumeId: number) => Promise<boolean>;

    // JD 匹配分析 Actions
    fetchJDMatchResults: () => Promise<void>;
    selectJDMatchResult: (analysisId: number) => Promise<void>;
    deleteJDMatchResult: (analysisId: number) => Promise<boolean>;
    clearJDMatchResult: () => void;

    // 候选人素材库 Actions
    fetchCandidateMaterials: (materialType?: MaterialType, isVerified?: boolean) => Promise<void>;
    selectMaterial: (materialId: number) => void;
    deleteMaterial: (materialId: number) => Promise<boolean>;
    clearMaterial: () => void;

    // 简历组装结果 Actions
    fetchAssemblyResults: () => Promise<void>;
    selectAssemblyResult: (resultId: number) => Promise<void>;
    deleteAssemblyResult: (resultId: number) => Promise<boolean>;
    clearAssemblyResult: () => void;

    // 项目经历重写 Actions
    fetchProjectRewriteHistory: (rewriteMode?: ProjectRewriteMode) => Promise<void>;
    deleteProjectRewriteRecord: (rewriteId: number) => Promise<boolean>;
}

export type ResumeSlice = ResumeState & ResumeActions;

// ============================================================================
// Slice 工厂函数
// ============================================================================

type SetState = (partial: Partial<ResumeSlice> | ((state: ResumeSlice) => Partial<ResumeSlice>)) => void;
type GetState = () => ResumeSlice;

export const createResumeSlice = (set: SetState, get: GetState): ResumeSlice => ({
    // ===== 初始状态 =====
    resumeResults: [],
    resumeResultsTotal: 0,
    currentResumeResult: null,
    resumeResultLoading: false,
    completedSessions: [],
    completedSessionsLoading: false,
    completedSessionsLastFetched: 0,

    generatedResumes: [],
    currentGeneratedResume: null,
    generatedResumesLoading: false,

    // JD 匹配分析
    jdMatchResults: [],
    jdMatchResultsLoading: false,
    currentJDMatchDetail: null,

    // 候选人素材库
    candidateMaterials: [],
    candidateMaterialsLoading: false,
    currentMaterial: null,

    // 简历组装结果
    assemblyResults: [],
    assemblyResultsLoading: false,
    currentAssemblyResult: null,

    // 项目经历重写
    projectRewriteHistory: [],
    projectRewriteHistoryLoading: false,

    // ===== Actions =====
    fetchResumeResults: async (resultType, append = false) => {
        set({ resumeResultLoading: true });
        try {
            const current = get().resumeResults;
            const response = await getResumeResults(resultType, 20, append ? current.length : 0);
            if (response.success) {
                const resumeResults = append
                    ? [...current, ...response.results.filter(item => !current.some(existing => existing.id === item.id))]
                    : response.results;
                set({ resumeResults, resumeResultsTotal: response.total });
            }
        } catch (error) {
            console.error('获取简历历史记录失败:', error);
        } finally {
            set({ resumeResultLoading: false });
        }
    },

    selectResumeResult: async (resultId: number) => {
        set({ resumeResultLoading: true, currentResumeResult: null });
        try {
            const result = await getResumeResultDetail(resultId);
            if (result) set({ currentResumeResult: result as ResumeResultItem });
        } catch (error) {
            console.error('获取简历历史详情失败:', error);
        } finally {
            set({ resumeResultLoading: false });
        }
    },

    deleteResumeResult: async (resultId: number) => {
        try {
            const success = await deleteResumeResult(resultId);
            if (success) {
                const { resumeResults, resumeResultsTotal, currentResumeResult } = get();
                set({
                    resumeResults: resumeResults.filter(r => r.id !== resultId),
                    resumeResultsTotal: Math.max(0, resumeResultsTotal - 1),
                    currentResumeResult: currentResumeResult?.id === resultId ? null : currentResumeResult
                });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除简历记录失败:', error);
            return false;
        }
    },

    clearResumeResult: () => {
        set({ currentResumeResult: null });
    },

    fetchCompletedSessions: async (force = false) => {
        const { completedSessions, completedSessionsLastFetched, completedSessionsLoading } = get();
        const now = Date.now();
        const CACHE_DURATION = 60 * 1000; // 缓存 1 分钟

        // 如果已经在加载中，直接返回
        if (completedSessionsLoading) return;

        // 如果不是强制刷新，且有数据，且在缓存有效期内，直接返回
        if (!force && completedSessions.length > 0 && (now - completedSessionsLastFetched < CACHE_DURATION)) {
            return;
        }

        set({ completedSessionsLoading: true });
        try {
            const sessions = await getCompletedSessionsForResume();
            set({
                completedSessions: sessions,
                completedSessionsLastFetched: Date.now()
            });
        } catch (error) {
            console.error('获取已完成会话列表失败:', error);
        } finally {
            set({ completedSessionsLoading: false });
        }
    },

    fetchGeneratedResumes: async () => {
        set({ generatedResumesLoading: true });
        try {
            const resumes = await getGeneratedResumes();
            set({ generatedResumes: resumes });
        } catch (error) {
            console.error('获取生成简历列表失败:', error);
        } finally {
            set({ generatedResumesLoading: false });
        }
    },

    selectGeneratedResume: async (resumeId: number) => {
        // 先检查本地列表
        const { generatedResumes } = get();
        let resume = generatedResumes.find(r => r.id === resumeId);

        // 如果没有内容（列表项可能不含 content），则获取详情
        if (resume && !resume.content) {
            const detail = await getGeneratedResume(resumeId);
            if (detail) {
                resume = detail;
                // 更新列表中的项目（可选）
            }
        } else if (!resume) {
            const detail = await getGeneratedResume(resumeId);
            if (detail) resume = detail;
        }

        if (resume) {
            set({ currentGeneratedResume: resume });
        }
    },

    deleteGeneratedResume: async (resumeId: number) => {
        try {
            const success = await deleteGeneratedResume(resumeId);
            if (success) {
                const { generatedResumes, currentGeneratedResume } = get();
                set({
                    generatedResumes: generatedResumes.filter(r => r.id !== resumeId),
                    currentGeneratedResume: currentGeneratedResume?.id === resumeId ? null : currentGeneratedResume
                });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除生成简历失败:', error);
            return false;
        }
    },

    // ===== JD 匹配分析 Actions =====
    fetchJDMatchResults: async () => {
        set({ jdMatchResultsLoading: true });
        try {
            const response = await getJDMatchHistory();
            if (response.success) {
                set({ jdMatchResults: response.results });
            }
        } catch (error) {
            console.error('获取 JD 分析历史失败:', error);
        } finally {
            set({ jdMatchResultsLoading: false });
        }
    },

    selectJDMatchResult: async (analysisId: number) => {
        try {
            const response = await getJDMatchDetail(analysisId);
            if (response.success && response.result) {
                set({ currentJDMatchDetail: response.result.analysis_result });
            }
        } catch (error) {
            console.error('获取 JD 分析详情失败:', error);
        }
    },

    clearJDMatchResult: () => {
        set({ currentJDMatchDetail: null });
    },

    deleteJDMatchResult: async (analysisId: number) => {
        try {
            const success = await deleteJDMatchResult(analysisId);
            if (success) {
                const { jdMatchResults } = get();
                set({ jdMatchResults: jdMatchResults.filter(r => r.id !== analysisId) });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除 JD 分析结果失败:', error);
            return false;
        }
    },

    // ===== 候选人素材库 Actions =====
    fetchCandidateMaterials: async (materialType?: MaterialType, isVerified?: boolean) => {
        set({ candidateMaterialsLoading: true });
        try {
            const response = await getMaterials(materialType, isVerified);
            if (response.success) {
                set({ candidateMaterials: response.materials });
            }
        } catch (error) {
            console.error('获取素材列表失败:', error);
        } finally {
            set({ candidateMaterialsLoading: false });
        }
    },

    selectMaterial: (materialId: number) => {
        const { candidateMaterials } = get();
        const material = candidateMaterials.find(m => m.id === materialId);
        if (material) {
            set({ currentMaterial: material });
        }
    },

    deleteMaterial: async (materialId: number) => {
        try {
            const success = await deleteMaterial(materialId);
            if (success) {
                const { candidateMaterials, currentMaterial } = get();
                set({
                    candidateMaterials: candidateMaterials.filter(m => m.id !== materialId),
                    currentMaterial: currentMaterial?.id === materialId ? null : currentMaterial
                });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除素材失败:', error);
            return false;
        }
    },

    clearMaterial: () => {
        set({ currentMaterial: null });
    },

    // ===== 简历组装结果 Actions =====
    fetchAssemblyResults: async () => {
        set({ assemblyResultsLoading: true });
        try {
            const response = await getAssemblyResults();
            if (response.success) {
                set({ assemblyResults: response.results });
            }
        } catch (error) {
            console.error('获取组装结果列表失败:', error);
        } finally {
            set({ assemblyResultsLoading: false });
        }
    },

    selectAssemblyResult: async (resultId: number) => {
        try {
            const response = await getAssemblyResult(resultId);
            if (response.success && response.result) {
                set({ currentAssemblyResult: response.result });
            }
        } catch (error) {
            console.error('获取组装结果详情失败:', error);
        }
    },

    deleteAssemblyResult: async (resultId: number) => {
        try {
            const success = await deleteAssemblyResult(resultId);
            if (success) {
                const { assemblyResults, currentAssemblyResult } = get();
                set({
                    assemblyResults: assemblyResults.filter(r => r.id !== resultId),
                    currentAssemblyResult: currentAssemblyResult?.id === resultId ? null : currentAssemblyResult
                });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除组装结果失败:', error);
            return false;
        }
    },

    clearAssemblyResult: () => {
        set({ currentAssemblyResult: null });
    },

    // ===== 项目经历重写 Actions =====
    fetchProjectRewriteHistory: async (rewriteMode?: ProjectRewriteMode) => {
        set({ projectRewriteHistoryLoading: true });
        try {
            const response = await getProjectRewriteHistory(rewriteMode);
            if (response.success) {
                set({ projectRewriteHistory: response.records });
            }
        } catch (error) {
            console.error('获取项目重写历史失败:', error);
        } finally {
            set({ projectRewriteHistoryLoading: false });
        }
    },

    deleteProjectRewriteRecord: async (rewriteId: number) => {
        try {
            const success = await deleteProjectRewrite(rewriteId);
            if (success) {
                const { projectRewriteHistory } = get();
                set({ projectRewriteHistory: projectRewriteHistory.filter(r => r.id !== rewriteId) });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除项目重写记录失败:', error);
            return false;
        }
    }
});

import {
    JobApplicationListItem,
    JobApplication,
    CreateApplicationRequest,
    UpdateApplicationRequest,
    CreateEventRequest,
    fetchApplications,
    getApplicationDetail,
    createApplication,
    updateApplication,
    deleteApplication,
    addApplicationEvent,
} from '@/lib/api/applications';

// ============================================================================
// 类型定义
// ============================================================================

export interface ApplicationState {
    applications: JobApplicationListItem[];
    applicationsLoading: boolean;
    applicationsTotal: number;
    currentApplication: JobApplication | null;
    applicationDetailLoading: boolean;
}

export interface ApplicationActions {
    fetchApplications: (status?: string, limit?: number) => Promise<void>;
    selectApplication: (applicationId: number) => Promise<void>;
    createApplication: (data: CreateApplicationRequest) => Promise<JobApplication | null>;
    updateApplication: (applicationId: number, data: UpdateApplicationRequest) => Promise<boolean>;
    deleteApplication: (applicationId: number) => Promise<boolean>;
    addApplicationEvent: (applicationId: number, data: CreateEventRequest) => Promise<boolean>;
    clearCurrentApplication: () => void;
}

export type ApplicationSlice = ApplicationState & ApplicationActions;

// ============================================================================
// Slice 工厂函数
// ============================================================================

type SetState = (partial: Partial<ApplicationSlice> | ((state: ApplicationSlice) => Partial<ApplicationSlice>)) => void;
type GetState = () => ApplicationSlice;

export const createApplicationSlice = (set: SetState, get: GetState): ApplicationSlice => ({
    // ===== 初始状态 =====
    applications: [],
    applicationsLoading: false,
    applicationsTotal: 0,
    currentApplication: null,
    applicationDetailLoading: false,

    // ===== Actions =====

    fetchApplications: async (status?: string, limit?: number) => {
        set({ applicationsLoading: true });
        try {
            const result = await fetchApplications(status, limit);
            set({
                applications: result.applications,
                applicationsTotal: result.total,
            });
        } catch (error) {
            console.error('获取投递列表失败:', error);
        } finally {
            set({ applicationsLoading: false });
        }
    },

    selectApplication: async (applicationId: number) => {
        set({ applicationDetailLoading: true, currentApplication: null });
        try {
            const detail = await getApplicationDetail(applicationId);
            if (detail) {
                set({ currentApplication: detail });
            }
        } catch (error) {
            console.error('获取投递详情失败:', error);
        } finally {
            set({ applicationDetailLoading: false });
        }
    },

    createApplication: async (data: CreateApplicationRequest) => {
        try {
            const app = await createApplication(data);
            if (app) {
                // 刷新列表
                await get().fetchApplications();
                return app;
            }
            return null;
        } catch (error) {
            console.error('创建投递记录失败:', error);
            return null;
        }
    },

    updateApplication: async (applicationId: number, data: UpdateApplicationRequest) => {
        try {
            const app = await updateApplication(applicationId, data);
            if (app) {
                // 更新当前详情
                const { currentApplication } = get();
                if (currentApplication?.id === applicationId) {
                    set({ currentApplication: app });
                }
                // 刷新列表
                await get().fetchApplications();
                return true;
            }
            return false;
        } catch (error) {
            console.error('更新投递记录失败:', error);
            return false;
        }
    },

    deleteApplication: async (applicationId: number) => {
        try {
            const success = await deleteApplication(applicationId);
            if (success) {
                const { applications, currentApplication } = get();
                set({
                    applications: applications.filter(a => a.id !== applicationId),
                    currentApplication: currentApplication?.id === applicationId ? null : currentApplication,
                    applicationsTotal: get().applicationsTotal - 1,
                });
                return true;
            }
            return false;
        } catch (error) {
            console.error('删除投递记录失败:', error);
            return false;
        }
    },

    addApplicationEvent: async (applicationId: number, data: CreateEventRequest) => {
        try {
            const event = await addApplicationEvent(applicationId, data);
            if (event) {
                // 重新加载详情以获取最新事件列表
                await get().selectApplication(applicationId);
                // 刷新列表（状态可能已更新）
                await get().fetchApplications();
                return true;
            }
            return false;
        } catch (error) {
            console.error('添加投递事件失败:', error);
            return false;
        }
    },

    clearCurrentApplication: () => {
        set({ currentApplication: null });
    },
});

/**
 * API Config Slice - API 配置管理
 * 
 * 负责 LLM API 模型的配置管理
 */

import { v4 as uuidv4 } from 'uuid';
import type { ModelConfig, ApiConfig } from '../types';
import { DEFAULT_API_CONFIG } from '../types';
import { modelConfigForRequest } from '@/lib/modelCredentialRequest';

type ModelRequestConfig = {
    credential_id: string;
    base_url: string;
    model: string;
    provider?: string;
    integration?: string;
    pricing_key?: string;
};

// ============================================================================
// 类型定义
// ============================================================================

export interface ApiConfigState {
    apiConfig: ApiConfig;
}

export interface ApiConfigActions {
    addModel: (model: Omit<ModelConfig, 'id' | 'createdAt'>) => ModelConfig | null;
    updateModel: (id: string, updates: Partial<ModelConfig>) => boolean;
    deleteModel: (id: string) => boolean;
    setSmartModel: (id: string) => boolean;
    setFastModel: (id: string) => boolean;
    toggleReasoningPoolModel: (id: string) => boolean;
    toggleFastPoolModel: (id: string) => boolean;
    getSmartModel: () => ModelConfig | null;
    getFastModel: () => ModelConfig | null;
    // 简历工具专家模型
    setGeneralModel: (id: string) => boolean;
    setMatchAnalystModel: (id: string) => boolean;
    setContentWriterModel: (id: string) => boolean;
    setHrReviewerModel: (id: string) => boolean;
    setReflectorModel: (id: string) => boolean;
    setMimoModel: (id: string) => boolean;
    setRagEmbeddingModel: (id: string) => boolean;
    setMem0LlmModel: (id: string) => boolean;
    setMem0EmbedderModel: (id: string) => boolean;
    getGeneralModel: () => ModelConfig | null;
    getMatchAnalystModel: () => ModelConfig | null;
    getContentWriterModel: () => ModelConfig | null;
    getHrReviewerModel: () => ModelConfig | null;
    getReflectorModel: () => ModelConfig | null;
    getMimoModel: () => ModelConfig | null;
    getRagEmbeddingModel: () => ModelConfig | null;
    getMem0LlmModel: () => ModelConfig | null;
    getMem0EmbedderModel: () => ModelConfig | null;
    // 通用方法
    isConfigured: () => boolean;
    getApiConfigForRequest: () => {
        smart: ModelRequestConfig;
        fast: ModelRequestConfig;
        general: ModelRequestConfig;
        match_analyst: ModelRequestConfig;
        content_writer: ModelRequestConfig;
        hr_reviewer: ModelRequestConfig;
        reflector: ModelRequestConfig;
        mimo: ModelRequestConfig | null;
        rag_embedding: ModelRequestConfig | null;
        mem0_llm: ModelRequestConfig | null;
        mem0_embedder: ModelRequestConfig | null;
        reasoning_pool: Array<ModelRequestConfig & { name: string; weight: number }>;
        fast_pool: Array<ModelRequestConfig & { name: string; weight: number }>;
    } | null;
}

export type ApiConfigSlice = ApiConfigState & ApiConfigActions;

// ============================================================================
// Slice 工厂函数
// ============================================================================

type SetState = (partial: Partial<ApiConfigSlice> | ((state: ApiConfigSlice) => Partial<ApiConfigSlice>)) => void;
type GetState = () => ApiConfigSlice;

/** Creates the api config Zustand slice; it owns long-lived shared state and leaves server persistence and authorization to the API layer. */
export const createApiConfigSlice = (set: SetState, get: GetState): ApiConfigSlice => ({
    // ===== 初始状态 =====
    apiConfig: DEFAULT_API_CONFIG,

    // ===== Actions =====

    addModel: (modelData) => {
        const { apiConfig } = get();
        const newModel: ModelConfig = {
            ...modelData,
            id: uuidv4(),
            createdAt: new Date().toISOString(),
        };

        const newConfig = {
            ...apiConfig,
            models: [...apiConfig.models, newModel],
        };

        // 只有文本连接可自动成为核心通道；MiMo 语音连接保持独立。
        if (apiConfig.models.length === 0 && newModel.kind !== 'voice') {
            newConfig.smartModelId = newModel.id;
            newConfig.fastModelId = newModel.id;
            newConfig.generalModelId = newModel.id;
            newConfig.matchAnalystModelId = newModel.id;
            newConfig.contentWriterModelId = newModel.id;
            newConfig.hrReviewerModelId = newModel.id;
            newConfig.reflectorModelId = newModel.id;
        }
        if (newModel.provider === 'mimo') {
            newConfig.mimoModelId = newModel.id;
        }

        set({ apiConfig: newConfig });
        return newModel;
    },

    updateModel: (id, updates) => {
        const { apiConfig } = get();
        const modelIndex = apiConfig.models.findIndex(m => m.id === id);
        if (modelIndex === -1) return false;

        const updatedModels = [...apiConfig.models];
        updatedModels[modelIndex] = { ...updatedModels[modelIndex], ...updates };

        set({ apiConfig: { ...apiConfig, models: updatedModels } });
        return true;
    },

    deleteModel: (id) => {
        const { apiConfig } = get();
        const newConfig = {
            ...apiConfig,
            models: apiConfig.models.filter(m => m.id !== id),
            smartModelId: apiConfig.smartModelId === id ? '' : apiConfig.smartModelId,
            fastModelId: apiConfig.fastModelId === id ? '' : apiConfig.fastModelId,
            reasoningPoolModelIds: (apiConfig.reasoningPoolModelIds || []).filter(modelId => modelId !== id),
            fastPoolModelIds: (apiConfig.fastPoolModelIds || []).filter(modelId => modelId !== id),
            generalModelId: apiConfig.generalModelId === id ? '' : apiConfig.generalModelId,
            matchAnalystModelId: apiConfig.matchAnalystModelId === id ? '' : apiConfig.matchAnalystModelId,
            contentWriterModelId: apiConfig.contentWriterModelId === id ? '' : apiConfig.contentWriterModelId,
            hrReviewerModelId: apiConfig.hrReviewerModelId === id ? '' : apiConfig.hrReviewerModelId,
            reflectorModelId: apiConfig.reflectorModelId === id ? '' : apiConfig.reflectorModelId,
            mimoModelId: apiConfig.mimoModelId === id ? '' : apiConfig.mimoModelId,
            ragEmbeddingModelId: apiConfig.ragEmbeddingModelId === id ? '' : apiConfig.ragEmbeddingModelId,
            mem0LlmModelId: apiConfig.mem0LlmModelId === id ? '' : apiConfig.mem0LlmModelId,
            mem0EmbedderModelId: apiConfig.mem0EmbedderModelId === id ? '' : apiConfig.mem0EmbedderModelId,
        };

        set({ apiConfig: newConfig });
        return true;
    },

    setSmartModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, smartModelId: id } });
        return true;
    },

    setFastModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, fastModelId: id } });
        return true;
    },

    toggleReasoningPoolModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        const current = apiConfig.reasoningPoolModelIds || [];
        const reasoningPoolModelIds = current.includes(id)
            ? current.filter(modelId => modelId !== id)
            : [...current, id];
        set({ apiConfig: { ...apiConfig, reasoningPoolModelIds } });
        return true;
    },

    toggleFastPoolModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        const current = apiConfig.fastPoolModelIds || [];
        const fastPoolModelIds = current.includes(id)
            ? current.filter(modelId => modelId !== id)
            : [...current, id];
        set({ apiConfig: { ...apiConfig, fastPoolModelIds } });
        return true;
    },

    // 简历工具专家模型 setters
    setGeneralModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, generalModelId: id } });
        return true;
    },

    setMatchAnalystModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, matchAnalystModelId: id } });
        return true;
    },

    setContentWriterModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, contentWriterModelId: id } });
        return true;
    },

    setHrReviewerModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, hrReviewerModelId: id } });
        return true;
    },

    setReflectorModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, reflectorModelId: id } });
        return true;
    },

    setMimoModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id && m.provider === 'mimo')) return false;
        set({ apiConfig: { ...apiConfig, mimoModelId: id } });
        return true;
    },

    setRagEmbeddingModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, ragEmbeddingModelId: id } });
        return true;
    },

    setMem0LlmModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, mem0LlmModelId: id } });
        return true;
    },

    setMem0EmbedderModel: (id) => {
        const { apiConfig } = get();
        if (id && !apiConfig.models.find(m => m.id === id)) return false;
        set({ apiConfig: { ...apiConfig, mem0EmbedderModelId: id } });
        return true;
    },

    // Getters
    getSmartModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.smartModelId) || null;
    },

    getFastModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.fastModelId) || null;
    },

    getGeneralModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.generalModelId) || null;
    },

    getMatchAnalystModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.matchAnalystModelId) || null;
    },

    getContentWriterModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.contentWriterModelId) || null;
    },

    getHrReviewerModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.hrReviewerModelId) || null;
    },

    getReflectorModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.reflectorModelId) || null;
    },

    getMimoModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.mimoModelId && m.provider === 'mimo') || null;
    },

    getRagEmbeddingModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.ragEmbeddingModelId) || null;
    },

    getMem0LlmModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.mem0LlmModelId) || null;
    },

    getMem0EmbedderModel: () => {
        const { apiConfig } = get();
        return apiConfig.models.find(m => m.id === apiConfig.mem0EmbedderModelId) || null;
    },

    isConfigured: () => {
        const { apiConfig } = get();
        const smartModel = apiConfig.models.find(m => m.id === apiConfig.smartModelId);
        const fastModel = apiConfig.models.find(m => m.id === apiConfig.fastModelId);
        return !!(smartModel?.credentialStored && fastModel?.credentialStored);
    },

    getApiConfigForRequest: () => {
        const smartModel = get().getSmartModel();
        const fastModel = get().getFastModel();
        const generalModel = get().getGeneralModel();
        const matchAnalystModel = get().getMatchAnalystModel();
        const contentWriterModel = get().getContentWriterModel();
        const hrReviewerModel = get().getHrReviewerModel();
        const reflectorModel = get().getReflectorModel();
        const mimoModel = get().getMimoModel();
        const ragEmbeddingModel = get().getRagEmbeddingModel();
        const mem0LlmModel = get().getMem0LlmModel();
        const mem0EmbedderModel = get().getMem0EmbedderModel();

        if (!smartModel || !fastModel) return null;

        // 辅助函数：获取模型配置，如果未设置则回退到 smart
        /** Provides the get model config store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
        const getModelConfig = (model: ModelConfig | null) => {
            const m = model || smartModel;
            return modelConfigForRequest(m);
        };

        /** Provides the get pool config store helper; request-scoped configuration and session state stay centralized in Zustand, while backend persistence remains in the API layer. */
        const getPoolConfig = (ids: string[] | undefined, fallback: ModelConfig) => {
            const selected = (ids || [])
                .map(id => get().apiConfig.models.find(model => model.id === id))
                .filter((model): model is ModelConfig => Boolean(model?.credentialStored));
            const members = selected.length > 0 ? selected : [fallback];
            return members.map(model => ({
                ...getModelConfig(model),
                name: model.name,
                weight: 1,
            }));
        };

        return {
            smart: getModelConfig(smartModel),
            fast: getModelConfig(fastModel),
            general: getModelConfig(generalModel),
            match_analyst: getModelConfig(matchAnalystModel),
            content_writer: getModelConfig(contentWriterModel),
            hr_reviewer: getModelConfig(hrReviewerModel),
            reflector: getModelConfig(reflectorModel),
            mimo: mimoModel ? getModelConfig(mimoModel) : null,
            rag_embedding: ragEmbeddingModel ? getModelConfig(ragEmbeddingModel) : null,
            mem0_llm: mem0LlmModel ? getModelConfig(mem0LlmModel) : null,
            mem0_embedder: mem0EmbedderModel ? getModelConfig(mem0EmbedderModel) : null,
            reasoning_pool: getPoolConfig(get().apiConfig.reasoningPoolModelIds, smartModel),
            fast_pool: getPoolConfig(get().apiConfig.fastPoolModelIds, fastModel),
        };
    },
});

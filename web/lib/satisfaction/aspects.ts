/**
 * 满意度候选方面常量
 * 按 agent_type 提供满意的方面与不满意的方面（中文 chip 选项）。
 */

/** 满意度反馈覆盖的 Agent 类型 */
export type SatisfactionAgentType = 'interview' | 'resume_optimize';

/** 某 agent_type 的候选方面集合 */
export interface SatisfactionAspects {
    /** 满意的候选方面 */
    satisfied: string[];
    /** 不满意的候选方面 */
    dissatisfied: string[];
}

/** 面试：满意的候选方面 */
const INTERVIEW_SATISFIED_ASPECTS = ['问题质量', '追问引导', '反馈专业', '节奏流畅', '难度适中', '其他'];

/** 面试：不满意的候选方面 */
const INTERVIEW_DISSATISFIED_ASPECTS = ['问题跑题', '追问过密', '反馈模糊', '节奏拖沓', '难度不适', '其他'];

/** 简历优化：满意的候选方面 */
const RESUME_SATISFIED_ASPECTS = ['改写建议', 'JD匹配分析', '结果可执行', '响应速度', '其他'];

/** 简历优化：不满意的候选方面 */
const RESUME_DISSATISFIED_ASPECTS = ['改写不贴合', '分析空泛', '操作繁琐', '响应慢', '其他'];

/**
 * 返回指定 agent_type 的候选方面集合。
 * @param agentType 满意度反馈对应的 Agent 类型
 */
export function satisfactionAspects(agentType: SatisfactionAgentType): SatisfactionAspects {
    if (agentType === 'interview') {
        return { satisfied: INTERVIEW_SATISFIED_ASPECTS, dissatisfied: INTERVIEW_DISSATISFIED_ASPECTS };
    }
    return { satisfied: RESUME_SATISFIED_ASPECTS, dissatisfied: RESUME_DISSATISFIED_ASPECTS };
}

/** Chinese labels and functional groups for the backend prompt registry names. */
const promptCatalog: Record<string, { displayName: string; group: string }> = {
    'interview.planner': { displayName: '面试题目规划', group: '模拟面试' },
    'interview.opening': { displayName: '面试开场', group: '模拟面试' },
    'interview.evaluating': { displayName: '面试回答评估与推进', group: '模拟面试' },
    'interview.hints': { displayName: '面试回答提示', group: '模拟面试' },
    'interview.feedback': { displayName: '面试总结反馈', group: '模拟面试' },
    'voice.system': { displayName: '语音面试回复', group: '语音面试' },
    'voice.interview_system': { displayName: '完整语音面试系统提示', group: '语音面试' },
    'voice.tts': { displayName: '语音合成系统提示', group: '语音面试' },
    'analysis.candidate_profile': { displayName: '单场能力画像', group: '能力分析' },
    'analysis.weakness_report': { displayName: '短板报告', group: '能力分析' },
    'analysis.aggregate_profile': { displayName: '跨场综合画像', group: '能力分析' },
    'resume.match_analyst': { displayName: '简历优化：JD 匹配分析', group: '简历处理' },
    'resume.content_writer': { displayName: '简历优化：内容改写建议', group: '简历处理' },
    'resume.hr_reviewer': { displayName: '简历优化：HR 视角审查', group: '简历处理' },
    'resume.moderator': { displayName: '简历优化：多专家汇总', group: '简历处理' },
    'resume.reflect': { displayName: '简历优化：反思', group: '简历处理' },
    'resume.refine': { displayName: '简历优化：最终改写', group: '简历处理' },
    'resume.jd_match.system': { displayName: '岗位匹配：系统提示', group: '岗位匹配' },
    'resume.jd_match.user': { displayName: '岗位匹配：用户提示', group: '岗位匹配' },
    'resume.needs_analysis': { displayName: '简历生成：信息缺口分析', group: '简历生成' },
    'resume.draft_generation': { displayName: '简历生成：初稿', group: '简历生成' },
    'resume.draft_optimization': { displayName: '简历生成：初稿优化', group: '简历生成' },
    'resume.fact_check': { displayName: '简历生成：事实核查', group: '简历生成' },
    'resume.finalize_review': { displayName: '简历生成：最终审查', group: '简历生成' },
    'resume.analysis': { displayName: '简历竞争力分析', group: '简历分析' },
    'resume.assembler.system': { displayName: '简历素材筛选：系统提示', group: '简历素材' },
    'resume.assembler.user': { displayName: '简历素材筛选：用户提示', group: '简历素材' },
    'resume.assembler.assemble': { displayName: '简历素材组装', group: '简历素材' },
    'resume.project_rewriter': { displayName: '项目经历改写', group: '简历处理' },
    'resume.orchestrator_assemble': { displayName: '简历优化最终组装', group: '简历处理' },
    'jobs.greeting': { displayName: '岗位打招呼文案', group: '岗位处理' },
    'jobs.extraction': { displayName: '岗位详情抽取', group: '岗位处理' },
    'jobs.card_extraction': { displayName: '岗位卡片抽取', group: '岗位处理' },
    'jobs.card_scoring': { displayName: '岗位卡片批量匹配评分', group: '岗位处理' },
};

/** Returns the Chinese functional name while preserving unknown custom names as a fallback. */
export function getPromptDisplayName(name: string): string {
    return promptCatalog[name]?.displayName ?? name;
}

/** Returns the fixed backend-function group; this is intentionally not user-editable. */
export function getPromptFunctionalGroup(name: string): string {
    return promptCatalog[name]?.group ?? '自定义 Prompt';
}

/** Maps technical lifecycle labels to concise Chinese labels for the prompt list. */
export function getPromptLabelDisplayName(label: string): string {
    return {
        builtin: '内置',
        draft: '草稿',
        production: '生产',
        staging: '测试',
    }[label] ?? label;
}

/** Chinese labels and functional groups for the backend prompt registry names. */
const promptCatalog: Record<string, { displayName: string; group: string }> = {
    'interview.planner': { displayName: '面试题目规划', group: '模拟面试' },
    'interview.opening': { displayName: '面试开场', group: '模拟面试' },
    'interview.evaluating': { displayName: '面试回答评估与推进', group: '模拟面试' },
    'interview.hints': { displayName: '面试回答提示', group: '模拟面试' },
    'voice.system': { displayName: '语音面试回复', group: '语音面试' },
    'voice.interview_system': { displayName: '完整语音面试系统提示', group: '语音面试' },
    'voice.tts': { displayName: '语音合成系统提示', group: '语音面试' },
    'analysis.candidate_profile': { displayName: '单场能力画像', group: '能力分析' },
    'analysis.weakness_report': { displayName: '短板报告', group: '能力分析' },
    'analysis.session_report': { displayName: '单场能力画像与短板地图', group: '能力分析' },
    'analysis.question_evidence': { displayName: '面试逐题证据块', group: '能力分析' },
    'analysis.evidence_report': { displayName: '逐题证据汇总报告', group: '能力分析' },
    'analysis.aggregate_profile': { displayName: '跨场综合画像（兼容）', group: '能力分析' },
    'analysis.multi_reviewer.technical_depth': { displayName: '面试评审：技术深度', group: '能力分析' },
    'analysis.multi_reviewer.communication': { displayName: '面试评审：沟通表达', group: '能力分析' },
    'analysis.multi_reviewer.job_fit': { displayName: '面试评审：岗位匹配', group: '能力分析' },
    'analysis.multi_reviewer.factual_risk': { displayName: '面试评审：事实风险', group: '能力分析' },
    'analysis.multi_reviewer_consensus.session_report': { displayName: '面试多评审共识汇总', group: '能力分析' },
    'analysis.multi_reviewer_consensus.ability_profile': { displayName: '能力画像多评审共识汇总', group: '能力分析' },
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
    'resume.rewrite_planner': { displayName: '简历改写规划', group: '简历处理' },
    'resume.rewrite_executor': { displayName: '简历改写执行', group: '简历处理' },
    'resume.material_extraction': { displayName: '简历素材抽取', group: '简历素材' },
    'jobs.greeting': { displayName: '岗位打招呼文案', group: '岗位处理' },
    'jobs.greeting_reflection': { displayName: '岗位打招呼文案自审', group: '岗位处理' },
    'jobs.extraction': { displayName: '岗位详情抽取', group: '岗位处理' },
    'jobs.card_extraction': { displayName: '岗位卡片抽取', group: '岗位处理' },
    'jobs.card_scoring': { displayName: '岗位卡片批量匹配评分', group: '岗位处理' },
};

/** Returns backend-owned Chinese text first, with the local catalog as an offline fallback. */
export function getPromptDisplayName(name: string, backendDisplayName?: string): string {
    const backendName = backendDisplayName?.trim();
    if (backendName && backendName !== name) return backendName;
    return promptCatalog[name]?.displayName || backendName || name;
}

/** Returns the backend-owned functional group; this is intentionally not user-editable. */
export function getPromptFunctionalGroup(name: string, backendFunctionalGroup?: string): string {
    const backendGroup = backendFunctionalGroup?.trim();
    if (backendGroup && !['自定义提示词', '自定义 Prompt'].includes(backendGroup)) return backendGroup;
    return promptCatalog[name]?.group || backendGroup || '自定义提示词';
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

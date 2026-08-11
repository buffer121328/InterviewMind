const SKILL_HEADING = /^(?:专业技能|专业能力|技能|核心技能|技术栈|技术能力|skills?|technical skills?)\s*[:：]?\s*$/i;
const SECTION_HEADING = /^(?:#{1,6}\s*)?(?:个人信息|基本信息|教育经历|教育背景|工作经历|实习经历|项目经历|项目经验|自我评价|个人总结|证书|荣誉|语言能力|求职意向|专业技能|专业能力|技能|核心技能|技术栈|技术能力|skills?|technical skills?)\s*[:：]?\s*$/i;

export interface ResumeSkillsExtraction {
    content: string;
    matched: boolean;
}

function normalizeLine(line: string): string {
    return line.replace(/^\s*[-*•▪●]\s*/, '').trim();
}

/** Extracts the first explicit professional-skills section without model calls. */
export function extractProfessionalSkills(resume: string): ResumeSkillsExtraction {
    const lines = String(resume || '').replace(/\r\n?/g, '\n').split('\n');
    const start = lines.findIndex(line => SKILL_HEADING.test(normalizeLine(line).replace(/^#+\s*/, '')));
    if (start < 0) return { content: String(resume || '').trim(), matched: false };

    const skillLines: string[] = [];
    for (const line of lines.slice(start + 1)) {
        const normalized = normalizeLine(line);
        if (normalized && (normalized.startsWith('#') || SECTION_HEADING.test(normalized.replace(/^#+\s*/, '')))) break;
        if (normalized) skillLines.push(normalized);
    }
    const content = skillLines.join('\n').trim();
    return { content: content || String(resume || '').trim(), matched: Boolean(content) };
}

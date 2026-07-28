import type {
    JDMatchResult,
    ResumeAnalyzeResult,
    ResumeChangeItem,
    ResumeOptimizeResult,
    ResumeReviewDecision,
    ResumeReviewItem,
    ResumeReviewState,
    ResumeWorkspaceResult,
} from './api/resumeTypes.ts';

type UnknownRecord = Record<string, unknown>;

interface ResumeHistorySelection {
    id: number;
    result_type: 'analyze' | 'optimize';
    result_data: unknown;
}

export type RestoredResumeWorkspace = Pick<ResumeWorkspaceResult, 'success'>
    & Partial<Omit<ResumeWorkspaceResult, 'success' | 'result_id' | 'review' | 'warnings'>>;

export interface RestoredResumeHistorySelection {
    workspace: RestoredResumeWorkspace | null;
    review: ResumeReviewState | null;
    resultId: number;
}

/** Restores legacy and unified persisted history without treating internal pipeline data as a public optimize result. */
export function restoreResumeHistorySelection(result: ResumeHistorySelection): RestoredResumeHistorySelection {
    const data = asRecord(result.result_data);
    const persistedWorkspace = asRecord(data?.workspace);
    const competitionAnalysis = toAnalyzeResult(persistedWorkspace?.competition_analysis)
        ?? (result.result_type === 'analyze' ? toAnalyzeResult(result.result_data) : null);
    const jdMatching = toJDMatchResult(persistedWorkspace?.jd_matching);
    const contentOptimization = result.result_type === 'optimize' ? toOptimizeResult(result.result_data, jdMatching) : null;
    const workspace = competitionAnalysis || jdMatching || contentOptimization
        ? {
            success: true as const,
            ...(competitionAnalysis ? { competition_analysis: competitionAnalysis } : {}),
            ...(jdMatching ? { jd_matching: jdMatching } : {}),
            ...(contentOptimization ? { content_optimization: contentOptimization } : {}),
        }
        : null;

    return { workspace, review: toReviewState(data), resultId: result.id };
}

/** Narrows an untrusted persisted JSON value before reading its named fields. */
function asRecord(value: unknown): UnknownRecord | null {
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as UnknownRecord : null;
}

/** Keeps only string entries so old malformed payloads cannot break history rendering. */
function strings(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/** Rebuilds the public competition-analysis contract from a persisted payload. */
function toAnalyzeResult(value: unknown): ResumeAnalyzeResult | null {
    const data = asRecord(value);
    if (!data || typeof data.overall_score !== 'number' || !Number.isFinite(data.overall_score)) return null;
    const scores = asRecord(data.dimension_scores);
    if (!scores) return null;
    const dimension_scores: ResumeAnalyzeResult['dimension_scores'] = {};
    for (const [name, rawScore] of Object.entries(scores)) {
        const score = asRecord(rawScore);
        if (!score || typeof score.score !== 'number' || typeof score.comment !== 'string') return null;
        dimension_scores[name] = { score: score.score, comment: score.comment };
    }
    return {
        overall_score: data.overall_score,
        dimension_scores,
        strengths: strings(data.strengths),
        weaknesses: strings(data.weaknesses),
        priority_improvements: strings(data.priority_improvements),
        ...(typeof data.interview_insights === 'string' ? { interview_insights: data.interview_insights } : {}),
    };
}

/** Rebuilds the public JD-match contract from the workspace-only persisted fields. */
function toJDMatchResult(value: unknown): JDMatchResult | null {
    const data = asRecord(value);
    const scores = ['overall_match_score', 'skill_match_score', 'project_match_score', 'experience_match_score', 'education_match_score'] as const;
    if (!data || scores.some(score => typeof data[score] !== 'number' || !Number.isFinite(data[score] as number))) return null;
    return {
        overall_match_score: data.overall_match_score as number,
        skill_match_score: data.skill_match_score as number,
        project_match_score: data.project_match_score as number,
        experience_match_score: data.experience_match_score as number,
        education_match_score: data.education_match_score as number,
        matched_keywords: strings(data.matched_keywords),
        missing_keywords: strings(data.missing_keywords),
        strengths: strings(data.strengths),
        risks: strings(data.risks),
        priority_actions: strings(data.priority_actions),
    };
}

/** Converts either an old public optimize result or top-level pipeline fields into the public optimize contract. */
function toOptimizeResult(value: unknown, workspaceJdMatch: JDMatchResult | null): ResumeOptimizeResult | null {
    const data = asRecord(value);
    if (!data) return null;
    if (isPublicOptimizeResult(value)) return value;

    const jdAnalysis = asRecord(data.jd_analysis);
    if (!jdAnalysis || typeof jdAnalysis.match_score !== 'number') return null;
    // Older unified runs used a tiny keyword vocabulary and persisted 0 even though
    // the richer workspace JD matcher had already produced a valid score.
    const matchScore = jdAnalysis.match_score > 0 || !workspaceJdMatch
        ? jdAnalysis.match_score
        : workspaceJdMatch.overall_match_score;
    const change_items = toChangeItems(data.change_items);
    const groupedChanges = new Map<string, Array<{ original?: string; optimized?: string; reason?: string }>>();
    for (const item of change_items) {
        const section = item.section_name || '综合';
        const changes = groupedChanges.get(section) || [];
        changes.push({ original: item.original_text || undefined, optimized: item.optimized_text, reason: item.reason || undefined });
        groupedChanges.set(section, changes);
    }
    const required = strings(jdAnalysis.keywords_required).length ? strings(jdAnalysis.keywords_required) : strings(jdAnalysis.jd_keywords);
    const materialPool = asRecord(data.material_pool);
    return {
        match_score: matchScore,
        hr_pass_rate: typeof jdAnalysis.hr_pass_rate === 'number' && jdAnalysis.hr_pass_rate > 0
            ? jdAnalysis.hr_pass_rate
            : Math.round(matchScore * 0.85),
        optimized_sections: [...groupedChanges.entries()].map(([section, changes]) => ({ section_name: section, section, changes })),
        key_improvements: change_items.flatMap(item => item.reason ? [item.reason] : []).slice(0, 10),
        ...(required.length ? { keyword_analysis: { jd_keywords: required, required, preferred: strings(jdAnalysis.keywords_preferred), matched: strings(jdAnalysis.matched_keywords), missing: strings(jdAnalysis.missing_keywords), bonus: [] } } : {}),
        ...(typeof materialPool?.summary === 'string' ? { interview_insights: materialPool.summary } : {}),
        change_items,
        ...(typeof data.overall_confidence === 'number' ? { overall_confidence: data.overall_confidence } : {}),
        requires_user_review: data.requires_user_review === true,
    };
}

/** Identifies the stable legacy optimize response before rendering it without remapping its already-public fields. */
function isPublicOptimizeResult(value: unknown): value is ResumeOptimizeResult {
    const data = asRecord(value);
    return Boolean(data && typeof data.match_score === 'number' && typeof data.hr_pass_rate === 'number'
        && Array.isArray(data.optimized_sections) && Array.isArray(data.key_improvements));
}

/** Maps persisted change items to their public fields before displaying or sending them to review UI. */
function toChangeItems(value: unknown): ResumeChangeItem[] {
    if (!Array.isArray(value)) return [];
    return value.flatMap(rawItem => {
        const item = asRecord(rawItem);
        if (!item) return [];
        return [{
            ...(typeof item.change_type === 'string' ? { change_type: item.change_type } : {}),
            ...(typeof item.section_name === 'string' ? { section_name: item.section_name } : {}),
            ...(typeof item.original_text === 'string' || item.original_text === null ? { original_text: item.original_text } : {}),
            ...(typeof item.optimized_text === 'string' ? { optimized_text: item.optimized_text } : {}),
            ...(typeof item.confidence === 'number' ? { confidence: item.confidence } : {}),
            ...(typeof item.requires_user_confirmation === 'boolean' ? { requires_user_confirmation: item.requires_user_confirmation } : {}),
            ...(typeof item.reason === 'string' || item.reason === null ? { reason: item.reason } : {}),
        }];
    });
}

/** Reconstructs the public review state from persisted decisions so selected workspace history is immediately usable. */
function toReviewState(data: UnknownRecord | null): ResumeReviewState | null {
    const review = asRecord(data?.human_review);
    if (!review || !['pending', 'completed', 'not_required'].includes(review.status as string) || typeof review.version !== 'number') return null;
    const decisions = asRecord(review.decisions) || {};
    const items: ResumeReviewItem[] = toChangeItems(data?.confirmation_items).flatMap((item, index) => {
        const rawItem = Array.isArray(data?.confirmation_items) ? asRecord(data?.confirmation_items[index]) : null;
        const itemId = rawItem?.item_id;
        const decision = typeof itemId === 'string' ? decisions[itemId] : undefined;
        if (typeof itemId !== 'string' || (decision !== undefined && decision !== 'approved' && decision !== 'rejected')) return [];
        return [{ ...item, item_id: itemId, status: (decision || 'pending') as 'pending' | ResumeReviewDecision }];
    });
    return {
        status: review.status as ResumeReviewState['status'],
        version: review.version,
        items,
        ...(typeof review.resolved_resume === 'string' || review.resolved_resume === null ? { resolved_resume: review.resolved_resume } : {}),
    };
}

export type ResumeWorkspaceStage = 'queued' | 'competition_analysis' | 'jd_matching' | 'content_optimization' | 'saving_result' | 'complete';

/** Converts server stage names into the finite UI state set used by the processing view. */
export function getResumeWorkspaceStage(stage: string): ResumeWorkspaceStage {
    if (stage === 'competition_analysis' || stage === 'jd_matching' || stage === 'content_optimization' || stage === 'saving_result') return stage;
    if (stage === 'queued' || stage === 'retrying') return 'queued';
    return 'complete';
}

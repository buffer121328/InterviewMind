import type { JobDetail } from './api/jobs.ts';
import { buildJobContextSnapshot, type JobContextSnapshot } from './jobContextHandoff.ts';

export interface ResumeJobSelection {
    snapshot: JobContextSnapshot;
    jobDescription: string;
}

/** Converts an owner-scoped job detail into editable resume-workspace context. */
export function buildResumeJobSelection(job: JobDetail): ResumeJobSelection {
    const snapshot = buildJobContextSnapshot(job);
    return {
        snapshot,
        jobDescription: snapshot.job_description,
    };
}

import type { JobDetail } from './api/jobs.ts';
import { buildJobContextSnapshot, type JobContextSnapshot } from './jobContextHandoff.ts';

export interface InterviewJobSelection {
    snapshot: JobContextSnapshot;
    jobDescription: string;
    companyInfo: string;
}

/** Converts one owner-scoped job detail into editable interview setup fields. */
export function buildInterviewJobSelection(job: JobDetail): InterviewJobSelection {
    const snapshot = buildJobContextSnapshot(job);
    return {
        snapshot,
        jobDescription: snapshot.job_description,
        companyInfo: [
            snapshot.company_name && `公司：${snapshot.company_name}`,
            snapshot.job_title && `目标岗位：${snapshot.job_title}`,
            snapshot.company_size_text && `公司规模：${snapshot.company_size_text}`,
        ].filter(Boolean).join('\n'),
    };
}

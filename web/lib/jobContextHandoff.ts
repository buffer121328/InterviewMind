import type { JobDetail } from './api/jobs.ts';

/** Immutable source metadata plus the editable job context handed to a business workspace. */
export interface JobContextSnapshot {
    source_job_id: number;
    source_platform: string;
    source_url: string;
    company_name: string;
    company_size_text: string;
    job_title: string;
    job_description: string;
    salary_text: string;
    city: string;
    imported_at: string;
}

/** Builds a bounded handoff snapshot only from an owner-scoped job detail returned by the API. */
export function buildJobContextSnapshot(job: JobDetail): JobContextSnapshot {
    return {
        source_job_id: job.id,
        source_platform: job.platform || '',
        source_url: job.source_url || '',
        company_name: job.company_name || '',
        company_size_text: job.company_size_text || '',
        job_title: job.job_title || '',
        job_description: job.job_description || job.source_text || '',
        salary_text: job.salary_text || '',
        city: job.city || '',
        imported_at: job.captured_at || '',
    };
}

/** Applies user edits while preserving the owner-validated source identity fields. */
export function updateJobContextSnapshot(
    snapshot: JobContextSnapshot,
    edits: Partial<Pick<JobContextSnapshot, 'company_name' | 'job_title' | 'job_description'>>,
): JobContextSnapshot {
    return { ...snapshot, ...edits };
}

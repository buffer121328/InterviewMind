import type { ExperienceCollectResponse } from './api/interviewExperience';

/** Formats one direct-import result without exposing model or source payloads. */
export function experienceImportSummary(result: ExperienceCollectResponse): string {
    const failed = result.failed_count > 0 ? ` · 失败 ${result.failed_count}` : '';
    return `${result.document_count} 篇面经 · ${result.candidate_count} 道候选 · 模型筛除 ${result.filtered_count} · 重复 ${result.duplicate_count} · 入库 ${result.imported_count}${failed}`;
}

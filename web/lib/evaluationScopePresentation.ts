import type { EvaluationModeScope } from './api/evaluations';

/** Builds the safe, server-owned scope summary shown before a non-smoke run. */
export function formatEvaluationScopeSummary(scope: EvaluationModeScope): string {
    const toolParts = [
        `无需工具 ${scope.tool_applicability.not_applicable ?? 0} 条`,
        scope.tool_applicability.required ? `必须工具 ${scope.tool_applicability.required} 条` : null,
        scope.tool_applicability.forbidden ? `禁止工具 ${scope.tool_applicability.forbidden} 条` : null,
    ].filter((value): value is string => Boolean(value));
    return `${scope.suite_name} · ${scope.case_count} 条案例 · 覆盖 ${scope.input_categories.join('、')} · ${toolParts.join(' · ')}`;
}

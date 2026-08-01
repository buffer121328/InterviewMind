// 已知超限：职责单一（同域展示组件集合），暂不拆分。

import type { RefObject } from 'react';
import { AlertCircle, BarChart3, CheckCircle, FileText, Loader2, Shield, Target, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { JDMatchResult, ResumeAnalyzeResult, ResumeOptimizeResult, ResumeReviewDecision, ResumeReviewState } from '@/lib/api/resumeTypes';

/** Maps a resume-analysis dimension key to the human-readable label used in the result panel, preserving unknown keys for forward compatibility. */
function getResumeDimensionLabel(key: string): string {
    const labels: Record<string, string> = {
        structure: '结构规范',
        completeness: '内容完整',
        quantification: '量化程度',
        clarity: '表达清晰',
        highlights: '亮点突出',
        job_match: 'JD匹配',
    };
    return labels[key] || key;
}

/** Renders the resume analyze result panel UI and coordinates its typed props, local state, and approved backend interactions. */
export function ResumeAnalyzeResultPanel({ result }: { result: ResumeAnalyzeResult }) {
        const analyzeResult = result;

        // 定义维度颜色映射,与 LandingPage.tsx 保持一致
        const dimensionColors: Record<string, { bar: string; text: string }> = {
            clarity: { bar: "bg-blue-500", text: "text-blue-600" },
            job_match: { bar: "bg-blue-500", text: "text-blue-600" },
            structure: { bar: "bg-teal-500", text: "text-teal-600" },
            highlights: { bar: "bg-teal-500", text: "text-teal-600" },
            completeness: { bar: "bg-purple-500", text: "text-purple-600" },
            quantification: { bar: "bg-purple-500", text: "text-purple-600" },
        };

        const radarData = Object.entries(analyzeResult.dimension_scores).map(([key, value]) => ({
            dimension: key,
            score: value.score / 10,
            label: getResumeDimensionLabel(key),
            colors: dimensionColors[key] || { bar: "bg-teal-500", text: "text-teal-600" },
        }));

        return (
            <div className="space-y-6 mt-6">
                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2">
                            <BarChart3 size={20} />
                            竞争力分析结果
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-4 mb-4">
                            <div className="text-center">
                                <div className="text-4xl font-bold text-teal-600">
                                    {analyzeResult.overall_score.toFixed(0)}
                                </div>
                                <div className="text-sm text-gray-500">综合评分</div>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3 mt-4">
                            {radarData.map((item) => (
                                <div key={item.dimension} className="p-3 bg-gray-50 rounded-lg">
                                    <div className="flex justify-between items-center mb-1">
                                        <span className="text-sm font-medium">{item.label}</span>
                                        <span className={`text-sm font-bold ${item.colors.text}`}>{(item.score * 10).toFixed(0)}</span>
                                    </div>
                                    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                                        <div
                                            className={`h-full ${item.colors.bar} rounded-full transition-all`}
                                            style={{ width: `${item.score * 10}%` }}
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>

                <div className="grid md:grid-cols-2 gap-4">
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center gap-2 text-green-600">
                                <CheckCircle size={16} />
                                优势
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="flex flex-col gap-3">
                                {analyzeResult.strengths.map((item, idx) => (
                                    <div key={idx} className="p-4 bg-green-50/80 text-green-800 rounded-xl text-sm leading-relaxed border border-green-100/50 shadow-sm">
                                        {item}
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center gap-2 text-teal-600">
                                <AlertCircle size={16} />
                                待改进
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="flex flex-col gap-3">
                                {analyzeResult.weaknesses.map((item, idx) => (
                                    <div key={idx} className="p-4 bg-teal-50/80 text-teal-800 rounded-xl text-sm leading-relaxed border border-teal-100/50 shadow-sm">
                                        {item}
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                </div>

                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="text-base font-bold text-gray-900">智能优化建议</CardTitle>
                        <p className="text-xs text-gray-500 mt-1">
                            不只是指出问题，更提供具体可行的修改方案。P1/P2 优先级划分，让优化有的放矢。
                        </p>
                    </CardHeader>
                    <CardContent>
                        <div className="bg-[#0f172a] rounded-xl p-4 space-y-3">
                            {analyzeResult.priority_improvements.map((item, idx) => {
                                // 解析内容: 预期格式 "P1 标题 内容"
                                const match = item.match(/^(P\d+)\s+(.+?)[:：]?\s+(.+)$/);
                                let priority = match ? match[1] : `P${idx + 1}`;
                                let title = match ? match[2] : "优化点";
                                let content = match ? match[3] : item;

                                // 处理 fallback 情况: 如果没匹配上但以 P数字 开头
                                if (!match && /^(P\d+)/.test(item)) {
                                    const parts = item.split(' ');
                                    if (parts.length > 1) {
                                        priority = parts[0];
                                        content = item.substring(parts[0].length).trim();
                                        // 尝试提取标题 (假设第二部分是标题，之后是内容)
                                        if (parts.length > 2) {
                                            title = parts[1];
                                            content = item.substring(parts[0].length + parts[1].length + 2).trim();
                                        }
                                    }
                                }

                                const isP1 = priority === 'P1';

                                return (
                                    <div key={idx} className="bg-[#1e293b] rounded-lg p-3 border border-slate-700">
                                        <div className="flex items-center gap-2 mb-2">
                                            <span className={`
                                                px-1.5 py-0.5 rounded text-xs font-bold
                                                ${isP1
                                                    ? 'bg-red-500/20 text-red-400'
                                                    : 'bg-teal-500/20 text-teal-400'}
                                            `}>
                                                {priority}
                                            </span>
                                            <span className="text-sm font-bold text-white">
                                                {title}
                                            </span>
                                        </div>
                                        <p className="text-xs text-slate-400 leading-relaxed">
                                            {content}
                                        </p>
                                    </div>
                                );
                            })}
                        </div>
                    </CardContent>
                </Card>

                {analyzeResult.interview_insights && (
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm">面试洞察</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-gray-600">{analyzeResult.interview_insights}</p>
                        </CardContent>
                    </Card>
                )}
            </div>
        );
}

/** Renders the resume optimize result panel UI and coordinates its typed props, local state, and approved backend interactions. */
export function ResumeOptimizeResultPanel({
    result,
    review,
    reviewDecisions,
    reviewLoading,
    reviewSubmitting,
    onReviewDecision,
    onSubmitReview,
    onScrollToGenerate,
    onGenerate,
    resultsBottomRef,
}: {
    result: ResumeOptimizeResult;
    review: ResumeReviewState | null;
    reviewDecisions: Record<string, ResumeReviewDecision>;
    reviewLoading: boolean;
    reviewSubmitting: boolean;
    onReviewDecision: (itemId: string, decision: ResumeReviewDecision) => void;
    onSubmitReview: () => void;
    onScrollToGenerate: () => void;
    onGenerate: () => void;
    resultsBottomRef: RefObject<HTMLDivElement | null>;
}) {
        const optimizeResult = result;
        const scrollToBottom = onScrollToGenerate;

        return (
            <div className="space-y-6 mt-6">
                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <FileText size={20} />
                                优化建议
                            </div>
                            <Button
                                size="sm"
                                className="h-9 text-sm font-medium bg-gradient-to-r from-teal-500 to-emerald-500 hover:from-teal-600 hover:to-emerald-600 text-white shadow-md hover:shadow-lg transition-all px-4"
                                onClick={scrollToBottom}
                            >
                                ↓ 确认并生成
                            </Button>
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-8 mb-4">
                            <div className="text-center">
                                <div className="text-3xl font-bold text-teal-600">
                                    {optimizeResult.match_score.toFixed(0)}%
                                </div>
                                <div className="text-sm text-gray-500">JD 匹配度</div>
                            </div>
                            <div className="text-center">
                                <div className="text-3xl font-bold text-green-600">
                                    {optimizeResult.hr_pass_rate.toFixed(0)}%
                                </div>
                                <div className="text-sm text-gray-500">HR 通过率</div>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm">关键改进点</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="space-y-4">
                            {optimizeResult.key_improvements.slice(0, 5).map((rawItem, idx) => {
                                // 兼容新版(string)和旧版(KeyImprovement)两种返回
                                const item = typeof rawItem === 'string'
                                    ? { priority: idx + 1, area: '', issue: rawItem, action: '', example: undefined as string | undefined }
                                    : rawItem;
                                return (
                                    <div key={idx} className="border-l-2 border-teal-500 pl-3">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="text-xs bg-teal-100 text-teal-700 px-2 py-0.5 rounded">
                                                优先级 {item.priority}
                                            </span>
                                            {item.area && <span className="text-sm font-medium">{item.area}</span>}
                                        </div>
                                        <p className="text-sm text-gray-500">{item.issue}</p>
                                        {item.action && <p className="text-sm mt-1">{item.action}</p>}
                                        {item.example && (
                                            <div className="mt-2 p-2 bg-gray-50 rounded text-xs">
                                                <span className="font-medium">示例：</span>{item.example}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </CardContent>
                </Card>

                {optimizeResult.keyword_analysis && (
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm">关键词分析</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-3">
                            {optimizeResult.keyword_analysis.missing.length > 0 && (
                                <div>
                                    <p className="text-xs text-teal-600 mb-1">缺失的关键词</p>
                                    <div className="flex flex-wrap gap-2">
                                        {optimizeResult.keyword_analysis.missing.map((item, idx) => (
                                            <span key={idx} className="px-2 py-1 bg-teal-100 text-teal-700 rounded text-xs">
                                                {item}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {optimizeResult.keyword_analysis.matched.length > 0 && (
                                <div>
                                    <p className="text-xs text-green-600 mb-1">已匹配的关键词</p>
                                    <div className="flex flex-wrap gap-2">
                                        {optimizeResult.keyword_analysis.matched.map((item, idx) => (
                                            <span key={idx} className="px-2 py-1 bg-green-100 text-green-700 rounded text-xs">
                                                {item}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                )}

                {optimizeResult.interview_insights && (
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm">面试洞察</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-gray-600">{optimizeResult.interview_insights}</p>
                        </CardContent>
                    </Card>
                )}

                {optimizeResult.requires_user_review && (
                    <Card className="border-amber-200 bg-amber-50/40">
                        <CardHeader className="pb-3">
                            <CardTitle className="flex items-center gap-2 text-sm text-amber-950">
                                <Shield size={17} />
                                人工确认改写
                            </CardTitle>
                            <p className="text-xs leading-5 text-amber-800">
                                以下内容涉及事实推断或低置信度改写。逐项选择保留优化或恢复原文，全部确认后才会进入简历生成。
                            </p>
                        </CardHeader>
                        <CardContent>
                            {reviewLoading ? (
                                <div className="flex items-center justify-center py-6 text-xs text-amber-800">
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    读取待确认项...
                                </div>
                            ) : review?.status === 'completed' ? (
                                <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-medium text-emerald-800">
                                    <CheckCircle className="h-4 w-4" />
                                    所有改写已确认，生成时将使用审阅后的最终内容。
                                </div>
                            ) : review ? (
                                <div className="space-y-3">
                                    {review.items.map((item, index) => {
                                        const selected = reviewDecisions[item.item_id];
                                        return (
                                            <div key={item.item_id} className="rounded-xl border border-amber-100 bg-white p-3">
                                                <div className="flex flex-wrap items-center justify-between gap-2">
                                                    <span className="text-xs font-semibold text-slate-800">
                                                        {item.section_name || `改写项 ${index + 1}`}
                                                    </span>
                                                    {item.reason && <span className="text-[10px] text-slate-400">{item.reason}</span>}
                                                </div>
                                                {item.original_text && (
                                                    <div className="mt-3 rounded-lg bg-slate-50 p-2.5">
                                                        <div className="text-[10px] font-medium text-slate-400">原文</div>
                                                        <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-slate-600">{item.original_text}</p>
                                                    </div>
                                                )}
                                                <div className="mt-2 rounded-lg bg-teal-50 p-2.5">
                                                    <div className="text-[10px] font-medium text-teal-600">优化后</div>
                                                    <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-teal-900">{item.optimized_text || '未提供优化文本'}</p>
                                                </div>
                                                <div className="mt-3 grid grid-cols-2 gap-2">
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="outline"
                                                        className={selected === 'approved' ? 'border-emerald-400 bg-emerald-50 text-emerald-800' : ''}
                                                        onClick={() => onReviewDecision(item.item_id, 'approved')}
                                                    >
                                                        保留优化
                                                    </Button>
                                                    <Button
                                                        type="button"
                                                        size="sm"
                                                        variant="outline"
                                                        className={selected === 'rejected' ? 'border-slate-400 bg-slate-100 text-slate-800' : ''}
                                                        onClick={() => onReviewDecision(item.item_id, 'rejected')}
                                                    >
                                                        恢复原文
                                                    </Button>
                                                </div>
                                            </div>
                                        );
                                    })}
                                    <Button
                                        type="button"
                                        className="w-full bg-amber-600 text-white hover:bg-amber-700"
                                        onClick={onSubmitReview}
                                        disabled={reviewSubmitting || review.items.some(item => (
                                            item.status === 'pending' && !reviewDecisions[item.item_id]
                                        ))}
                                    >
                                        {reviewSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                        提交全部确认
                                    </Button>
                                </div>
                            ) : (
                                <div className="rounded-xl border border-amber-200 bg-white p-3 text-xs leading-5 text-amber-900">
                                    暂时无法读取待确认项，请重新打开该优化记录后再试。
                                </div>
                            )}
                        </CardContent>
                    </Card>
                )}

                {/* 生成简历按钮 */}
                <div className="pt-4 border-t" ref={resultsBottomRef}>
                    <Button
                        onClick={onGenerate}
                        disabled={Boolean(optimizeResult.requires_user_review && review?.status !== 'completed')}
                        className="w-full bg-gradient-to-r from-teal-500 to-emerald-500 hover:from-teal-600 hover:to-emerald-600 text-white"
                        size="lg"
                    >
                        <FileText className="w-5 h-5 mr-2" />
                        生成优化简历
                    </Button>
                    <p className="text-xs text-gray-500 text-center mt-2">
                        {optimizeResult.requires_user_review && review?.status !== 'completed'
                            ? '完成上方人工确认后才能生成完整简历'
                            : '根据已确认的优化建议，自动生成完整简历'}
                    </p>
                </div>
            </div>
        );
}

/** Renders the resume jdmatch result panel UI and coordinates its typed props, local state, and approved backend interactions. */
export function ResumeJDMatchResultPanel({
    result,
    onToggleOptimize,
    isOptimizeExpanded = false,
}: {
    result: JDMatchResult;
    onToggleOptimize?: () => void;
    isOptimizeExpanded?: boolean;
}) {
    const jdMatchResult = result;

    /** Maps a match score to the panel's color tier so score thresholds remain consistent across each displayed dimension. */
    const getScoreColor = (score: number) => {
        if (score >= 80) return { bar: "bg-green-500", text: "text-green-600" };
        if (score >= 60) return { bar: "bg-blue-500", text: "text-blue-600" };
        return { bar: "bg-teal-500", text: "text-teal-600" };
    };

    const dimensions = [
        { key: "skill", label: "技能匹配", score: jdMatchResult.skill_match_score },
        { key: "project", label: "项目匹配", score: jdMatchResult.project_match_score },
        { key: "experience", label: "经验匹配", score: jdMatchResult.experience_match_score },
        { key: "education", label: "教育匹配", score: jdMatchResult.education_match_score },
    ];

    return (
            <div className="space-y-6 mt-6">
                {/* 总分 */}
                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="flex items-center gap-2">
                            <Target size={20} />
                            JD 匹配分析结果
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-4 mb-4">
                            <div className="text-center">
                                <div className={`text-4xl font-bold ${getScoreColor(jdMatchResult.overall_match_score).text}`}>
                                    {jdMatchResult.overall_match_score.toFixed(0)}
                                </div>
                                <div className="text-sm text-gray-500">综合匹配分</div>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3 mt-4">
                            {dimensions.map((dim) => {
                                const colors = getScoreColor(dim.score);
                                return (
                                    <div key={dim.key} className="p-3 bg-gray-50 rounded-lg">
                                        <div className="flex justify-between items-center mb-1">
                                            <span className="text-sm font-medium">{dim.label}</span>
                                            <span className={`text-sm font-bold ${colors.text}`}>{dim.score.toFixed(0)}</span>
                                        </div>
                                        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                                            <div
                                                className={`h-full ${colors.bar} rounded-full transition-all`}
                                                style={{ width: `${dim.score}%` }}
                                            />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </CardContent>
                </Card>

                {/* 关键词分析 */}
                <div className="grid md:grid-cols-2 gap-4">
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center gap-2 text-green-600">
                                <CheckCircle size={16} />
                                命中关键词
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {jdMatchResult.matched_keywords.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {jdMatchResult.matched_keywords.map((kw, idx) => (
                                        <span key={idx} className="px-2.5 py-1 bg-green-100 text-green-700 rounded-full text-xs font-medium">
                                            {kw}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400">暂无命中关键词</p>
                            )}
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center gap-2 text-teal-600">
                                <AlertCircle size={16} />
                                缺失关键词
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {jdMatchResult.missing_keywords.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {jdMatchResult.missing_keywords.map((kw, idx) => (
                                        <span key={idx} className="px-2.5 py-1 bg-teal-100 text-teal-700 rounded-full text-xs font-medium">
                                            {kw}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-gray-400">无缺失关键词</p>
                            )}
                        </CardContent>
                    </Card>
                </div>

                {/* 优势与风险 */}
                <div className="grid md:grid-cols-2 gap-4">
                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center gap-2 text-green-600">
                                <Shield size={16} />
                                优势
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                {jdMatchResult.strengths.map((item, idx) => (
                                    <div key={idx} className="p-3 bg-green-50/80 text-green-800 rounded-lg text-sm leading-relaxed border border-green-100/50">
                                        {item}
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm flex items-center gap-2 text-red-600">
                                <AlertCircle size={16} />
                                风险
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                {jdMatchResult.risks.map((item, idx) => (
                                    <div key={idx} className="p-3 bg-red-50/80 text-red-800 rounded-lg text-sm leading-relaxed border border-red-100/50">
                                        {item}
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                </div>

                {/* 优先改进建议 */}
                <Card>
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                            <TrendingUp size={16} />
                            优先改进建议
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="bg-[#0f172a] rounded-xl p-4 space-y-3">
                            {jdMatchResult.priority_actions.map((action, idx) => (
                                <div key={idx} className="bg-[#1e293b] rounded-lg p-3 border border-slate-700">
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${idx === 0 ? 'bg-red-500/20 text-red-400' : 'bg-teal-500/20 text-teal-400'}`}>
                                            P{idx + 1}
                                        </span>
                                    </div>
                                    <p className="text-xs text-slate-400 leading-relaxed">
                                        {action}
                                    </p>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>

                {/* A matching-only result has no unified optimization result to navigate to. */}
                {onToggleOptimize && <div className="pt-4 border-t flex gap-3">
                    <Button
                        onClick={onToggleOptimize}
                        aria-expanded={isOptimizeExpanded}
                        className="flex-1 bg-gradient-to-r from-teal-500 to-emerald-500 hover:from-teal-600 hover:to-emerald-600 text-white"
                        size="lg"
                    >
                        <FileText className="w-5 h-5 mr-2" />
                        {isOptimizeExpanded ? '收起完整优化建议' : '查看完整优化建议'}
                    </Button>
                </div>}
            </div>
        );
}

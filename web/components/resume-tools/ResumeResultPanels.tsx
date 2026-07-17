import type { RefObject } from 'react';
import { AlertCircle, BarChart3, CheckCircle, FileText, Shield, Target, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { JDMatchResult, ResumeAnalyzeResult, ResumeOptimizeResult } from '@/lib/api/resume';

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

export function ResumeAnalyzeResultPanel({ result }: { result: ResumeAnalyzeResult }) {
        const analyzeResult = result;

        // 定义维度颜色映射,与 LandingPage.tsx 保持一致
        const dimensionColors: Record<string, { bar: string; text: string }> = {
            clarity: { bar: "bg-blue-500", text: "text-blue-600" },
            job_match: { bar: "bg-blue-500", text: "text-blue-600" },
            structure: { bar: "bg-orange-500", text: "text-orange-600" },
            highlights: { bar: "bg-orange-500", text: "text-orange-600" },
            completeness: { bar: "bg-purple-500", text: "text-purple-600" },
            quantification: { bar: "bg-purple-500", text: "text-purple-600" },
        };

        const radarData = Object.entries(analyzeResult.dimension_scores).map(([key, value]) => ({
            dimension: key,
            score: value.score / 10,
            label: getResumeDimensionLabel(key),
            colors: dimensionColors[key] || { bar: "bg-orange-500", text: "text-orange-600" },
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
                                <div className="text-4xl font-bold text-orange-600">
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
                            <CardTitle className="text-sm flex items-center gap-2 text-orange-600">
                                <AlertCircle size={16} />
                                待改进
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="flex flex-col gap-3">
                                {analyzeResult.weaknesses.map((item, idx) => (
                                    <div key={idx} className="p-4 bg-orange-50/80 text-orange-800 rounded-xl text-sm leading-relaxed border border-orange-100/50 shadow-sm">
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
                                                    : 'bg-orange-500/20 text-orange-400'}
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

export function ResumeOptimizeResultPanel({
    result,
    onScrollToGenerate,
    onGenerate,
    resultsBottomRef,
}: {
    result: ResumeOptimizeResult;
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
                                className="h-9 text-sm font-medium bg-gradient-to-r from-orange-500 to-emerald-500 hover:from-orange-600 hover:to-emerald-600 text-white shadow-md hover:shadow-lg transition-all px-4"
                                onClick={scrollToBottom}
                            >
                                ↓ 下滑直接生成
                            </Button>
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-8 mb-4">
                            <div className="text-center">
                                <div className="text-3xl font-bold text-orange-600">
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
                                    <div key={idx} className="border-l-2 border-orange-500 pl-3">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded">
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
                                    <p className="text-xs text-orange-600 mb-1">缺失的关键词</p>
                                    <div className="flex flex-wrap gap-2">
                                        {optimizeResult.keyword_analysis.missing.map((item, idx) => (
                                            <span key={idx} className="px-2 py-1 bg-orange-100 text-orange-700 rounded text-xs">
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

                {/* 生成简历按钮 */}
                <div className="pt-4 border-t" ref={resultsBottomRef}>
                    <Button
                        onClick={onGenerate}
                        className="w-full bg-gradient-to-r from-orange-500 to-emerald-500 hover:from-orange-600 hover:to-emerald-600 text-white"
                        size="lg"
                    >
                        <FileText className="w-5 h-5 mr-2" />
                        生成优化简历
                    </Button>
                    <p className="text-xs text-gray-500 text-center mt-2">
                        根据优化建议，自动生成完整简历
                    </p>
                </div>
            </div>
        );
}

export function ResumeJDMatchResultPanel({
    result,
    onContinueOptimize,
}: {
    result: JDMatchResult;
    onContinueOptimize: () => void;
}) {
    const jdMatchResult = result;

    const getScoreColor = (score: number) => {
        if (score >= 80) return { bar: "bg-green-500", text: "text-green-600" };
        if (score >= 60) return { bar: "bg-blue-500", text: "text-blue-600" };
        return { bar: "bg-orange-500", text: "text-orange-600" };
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
                            <CardTitle className="text-sm flex items-center gap-2 text-orange-600">
                                <AlertCircle size={16} />
                                缺失关键词
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {jdMatchResult.missing_keywords.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {jdMatchResult.missing_keywords.map((kw, idx) => (
                                        <span key={idx} className="px-2.5 py-1 bg-orange-100 text-orange-700 rounded-full text-xs font-medium">
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
                                        <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${idx === 0 ? 'bg-red-500/20 text-red-400' : 'bg-orange-500/20 text-orange-400'}`}>
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

                {/* 后续操作按钮 */}
                <div className="pt-4 border-t flex gap-3">
                    <Button
                        onClick={onContinueOptimize}
                        className="flex-1 bg-gradient-to-r from-orange-500 to-emerald-500 hover:from-orange-600 hover:to-emerald-600 text-white"
                        size="lg"
                    >
                        <FileText className="w-5 h-5 mr-2" />
                        继续优化简历
                    </Button>
                </div>
            </div>
        );
}

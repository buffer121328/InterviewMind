'use client';

import { useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    BarChart3,
    BriefcaseBusiness,
    CalendarDays,
    CheckCircle2,
    FileText,
    Loader2,
    MessagesSquare,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { DialogueReview } from '@/components/DialogueReview';
import { getSessionDetail, type SessionDetail } from '@/lib/api/sessions';
import { getSessionProfile, type AbilityProfile } from '@/lib/api/profile';
import { getSessionWeaknessReport, type WeaknessReport } from '@/lib/api/weakness';

interface InterviewHistoryDetailDialogProps {
    sessionId: string | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

const PROFILE_DIMENSIONS: Array<{ key: keyof AbilityProfile; label: string }> = [
    { key: 'professional_competence', label: '专业能力' },
    { key: 'execution_results', label: '执行与结果' },
    { key: 'logic_problem_solving', label: '逻辑与解决问题' },
    { key: 'communication', label: '沟通表达' },
    { key: 'growth_potential', label: '成长潜力' },
    { key: 'collaboration', label: '协作能力' },
];

function formatDate(value?: string) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
}

export function InterviewHistoryDetailDialog({
    sessionId,
    open,
    onOpenChange,
}: InterviewHistoryDetailDialogProps) {
    const [session, setSession] = useState<SessionDetail | null>(null);
    const [profile, setProfile] = useState<AbilityProfile | null>(null);
    const [weakness, setWeakness] = useState<WeaknessReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!open || !sessionId) return;
        let cancelled = false;

        void Promise.all([
            getSessionDetail(sessionId),
            getSessionProfile(sessionId),
            getSessionWeaknessReport(sessionId),
        ]).then(([sessionResult, profileResult, weaknessResult]) => {
            if (cancelled) return;
            if (!sessionResult) {
                setError('无法读取该场面试记录，请稍后重试');
                return;
            }
            setSession(sessionResult);
            setProfile(profileResult.success && profileResult.profile ? profileResult.profile : null);
            setWeakness(weaknessResult.success && weaknessResult.report ? weaknessResult.report : null);
        }).finally(() => {
            if (!cancelled) setLoading(false);
        });

        return () => {
            cancelled = true;
        };
    }, [open, sessionId]);

    const dialogueMessages = useMemo(() => (
        (session?.messages || [])
            .filter(message => message.role === 'user' || message.role === 'assistant')
            .map(message => ({
                role: message.role as 'user' | 'assistant',
                content: message.content,
                timestamp: message.timestamp,
                audio_url: message.audio_url,
            }))
    ), [session]);

    const answeredCount = useMemo(
        () => dialogueMessages.filter(message => message.role === 'user').length,
        [dialogueMessages],
    );

    const interviewSummary = useMemo(() => {
        if (session?.metadata.status !== 'completed') return null;
        return [...(session.messages || [])].reverse().find(message => message.role === 'assistant')?.content || null;
    }, [session]);

    const reportAvailable = Boolean(interviewSummary || profile || weakness);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[88vh] max-w-5xl flex-col overflow-hidden p-0">
                <DialogHeader className="border-b border-gray-100 px-6 py-5 pr-12">
                    <DialogTitle className="text-xl">{session?.title || '历史面试详情'}</DialogTitle>
                    <DialogDescription>
                        查看本场面试的基本信息、完整问答和已生成报告。
                    </DialogDescription>
                </DialogHeader>

                {loading ? (
                    <div className="flex flex-1 items-center justify-center gap-2 text-sm text-gray-500">
                        <Loader2 className="h-5 w-5 animate-spin text-orange-500" />
                        正在加载历史面试详情...
                    </div>
                ) : error || !session ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                        <AlertTriangle className="h-8 w-8 text-amber-500" />
                        <p className="text-sm text-gray-600">{error || '面试记录不存在或无权访问'}</p>
                    </div>
                ) : (
                    <Tabs defaultValue="overview" className="min-h-0 flex-1 gap-0">
                        <div className="border-b border-gray-100 px-6 py-3">
                            <TabsList className="grid w-full max-w-md grid-cols-3">
                                <TabsTrigger value="overview"><FileText />概览</TabsTrigger>
                                <TabsTrigger value="dialogue"><MessagesSquare />面试问答</TabsTrigger>
                                <TabsTrigger value="report"><BarChart3 />面试报告</TabsTrigger>
                            </TabsList>
                        </div>

                        <TabsContent value="overview" className="min-h-0 flex-1 overflow-hidden">
                            <ScrollArea className="h-full">
                                <div className="space-y-6 p-6">
                                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                                        <InfoCard label="状态" value={session.metadata.status === 'completed' ? '已完成' : session.metadata.status === 'active' ? '进行中' : '已归档'} />
                                        <InfoCard label="面试形式" value={session.metadata.mode === 'voice' ? '语音面试' : '文字面试'} />
                                        <InfoCard label="轮次" value={`第 ${session.metadata.round_index || 1} 轮`} />
                                        <InfoCard label="已回答" value={`${answeredCount} 题`} />
                                    </div>

                                    <div className="grid gap-4 lg:grid-cols-2">
                                        <section className="rounded-xl border border-gray-200 bg-white p-5">
                                            <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900">
                                                <CalendarDays className="h-4 w-4 text-orange-500" />
                                                会话信息
                                            </h3>
                                            <dl className="space-y-3 text-sm">
                                                <InfoRow label="创建时间" value={formatDate(session.created_at)} />
                                                <InfoRow label="最后更新" value={formatDate(session.updated_at)} />
                                                <InfoRow label="消息数量" value={`${dialogueMessages.length} 条`} />
                                                <InfoRow label="目标题数" value={`${session.metadata.max_questions} 题`} />
                                                <InfoRow label="简历" value={session.metadata.resume_filename || '未记录'} />
                                                <InfoRow label="公司" value={session.metadata.company_info || '未记录'} />
                                            </dl>
                                        </section>

                                        <section className="rounded-xl border border-gray-200 bg-white p-5">
                                            <h3 className="mb-4 flex items-center gap-2 font-semibold text-gray-900">
                                                <BriefcaseBusiness className="h-4 w-4 text-orange-500" />
                                                目标岗位
                                            </h3>
                                            <p className="max-h-56 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-gray-600">
                                                {session.metadata.job_description || '本场面试未保存岗位描述。'}
                                            </p>
                                        </section>
                                    </div>

                                    {profile?.overall_assessment && (
                                        <section className="rounded-xl border border-orange-200 bg-orange-50/60 p-5">
                                            <h3 className="mb-2 font-semibold text-gray-900">面试结论摘要</h3>
                                            <p className="whitespace-pre-wrap text-sm leading-6 text-gray-700">{profile.overall_assessment}</p>
                                            {profile.recommendation && (
                                                <p className="mt-3 text-sm font-medium text-orange-700">建议：{profile.recommendation}</p>
                                            )}
                                        </section>
                                    )}
                                </div>
                            </ScrollArea>
                        </TabsContent>

                        <TabsContent value="dialogue" className="min-h-0 flex-1 overflow-hidden">
                            <ScrollArea className="h-full">
                                <div className="p-6">
                                    <DialogueReview messages={dialogueMessages} />
                                </div>
                            </ScrollArea>
                        </TabsContent>

                        <TabsContent value="report" className="min-h-0 flex-1 overflow-hidden">
                            <ScrollArea className="h-full">
                                <div className="space-y-6 p-6">
                                    {!reportAvailable && (
                                        <div className="rounded-xl border border-dashed border-gray-300 p-10 text-center">
                                            <BarChart3 className="mx-auto mb-3 h-8 w-8 text-gray-300" />
                                            <h3 className="font-medium text-gray-800">本场面试尚未生成报告</h3>
                                            <p className="mt-1 text-sm text-gray-500">进入该会话后，可通过“本轮能力画像”或“短板地图”生成报告。</p>
                                        </div>
                                    )}

                                    {interviewSummary && (
                                        <section className="rounded-xl border border-orange-200 bg-orange-50/60 p-5">
                                            <h3 className="mb-3 text-base font-semibold text-gray-900">面试总结</h3>
                                            <p className="whitespace-pre-wrap text-sm leading-7 text-gray-700">{interviewSummary}</p>
                                        </section>
                                    )}

                                    {profile && (
                                        <section className="space-y-4">
                                            <div>
                                                <h3 className="text-base font-semibold text-gray-900">能力画像</h3>
                                                <p className="text-xs text-gray-500">更新时间：{formatDate(profile.last_updated)}</p>
                                            </div>
                                            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                                                {PROFILE_DIMENSIONS.map(({ key, label }) => {
                                                    const dimension = profile[key];
                                                    if (!dimension || typeof dimension !== 'object' || !('score' in dimension)) return null;
                                                    return (
                                                        <div key={key} className="rounded-xl border border-gray-200 bg-white p-4">
                                                            <div className="flex items-center justify-between">
                                                                <span className="text-sm font-medium text-gray-700">{label}</span>
                                                                <span className="text-lg font-bold text-orange-600">{dimension.score}/10</span>
                                                            </div>
                                                            {(dimension.reason || dimension.evidence) && (
                                                                <p className="mt-2 text-xs leading-5 text-gray-500">{dimension.reason || dimension.evidence}</p>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                            <div className="grid gap-4 md:grid-cols-2">
                                                <ListCard title="主要优势" items={profile.key_strengths || []} tone="success" />
                                                <ListCard title="待提升项" items={profile.key_weaknesses || []} tone="warning" />
                                            </div>
                                            {profile.overall_assessment && (
                                                <div className="rounded-xl bg-gray-50 p-5 text-sm leading-6 text-gray-700">
                                                    <div className="mb-2 font-semibold text-gray-900">综合评价</div>
                                                    {profile.overall_assessment}
                                                    {profile.recommendation && <div className="mt-3 font-medium text-orange-700">建议：{profile.recommendation}</div>}
                                                </div>
                                            )}
                                        </section>
                                    )}

                                    {weakness && (
                                        <section className="space-y-4 border-t border-gray-100 pt-6">
                                            <div>
                                                <h3 className="text-base font-semibold text-gray-900">短板与改进报告</h3>
                                                <p className="text-xs text-gray-500">生成时间：{formatDate(weakness.created_at)}</p>
                                            </div>
                                            <div className="grid gap-3 md:grid-cols-2">
                                                {weakness.report_data.weakness_categories.map((item, index) => (
                                                    <div key={`${item.category}-${index}`} className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                                                        <div className="flex items-center justify-between gap-3">
                                                            <span className="font-medium text-gray-900">{item.category}</span>
                                                            <span className="rounded-full bg-white px-2 py-0.5 text-xs text-amber-700">{item.severity}</span>
                                                        </div>
                                                        <p className="mt-2 text-sm leading-5 text-gray-600">{item.description}</p>
                                                    </div>
                                                ))}
                                            </div>

                                            {weakness.report_data.question_failures.length > 0 && (
                                                <div className="space-y-3">
                                                    <h4 className="font-medium text-gray-900">典型问答问题</h4>
                                                    {weakness.report_data.question_failures.map((failure, index) => (
                                                        <div key={index} className="rounded-xl border border-gray-200 p-4 text-sm">
                                                            <div className="font-medium text-gray-900">Q：{failure.question}</div>
                                                            <div className="mt-2 text-gray-600">原回答：{failure.user_answer}</div>
                                                            <div className="mt-2 text-amber-700">问题：{failure.issue}</div>
                                                            <div className="mt-2 rounded-lg bg-emerald-50 p-3 text-emerald-800">改进示例：{failure.better_example}</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}

                                            <div className="space-y-2">
                                                <h4 className="font-medium text-gray-900">改进行动</h4>
                                                {weakness.report_data.improvement_actions
                                                    .slice()
                                                    .sort((a, b) => a.priority - b.priority)
                                                    .map((action, index) => (
                                                        <div key={index} className="flex items-start gap-3 rounded-lg bg-gray-50 p-3 text-sm">
                                                            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                                                            <div>
                                                                <div className="text-gray-800">{action.action}</div>
                                                                <div className="mt-1 text-xs text-gray-400">优先级 {action.priority} · {action.estimated_effort}</div>
                                                            </div>
                                                        </div>
                                                    ))}
                                            </div>
                                        </section>
                                    )}
                                </div>
                            </ScrollArea>
                        </TabsContent>
                    </Tabs>
                )}
            </DialogContent>
        </Dialog>
    );
}

function InfoCard({ label, value }: { label: string; value: string }) {
    return (
        <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-4">
            <div className="text-xs text-gray-400">{label}</div>
            <div className="mt-1 font-semibold text-gray-900">{value}</div>
        </div>
    );
}

function InfoRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex items-start justify-between gap-4">
            <dt className="shrink-0 text-gray-400">{label}</dt>
            <dd className="text-right text-gray-700">{value}</dd>
        </div>
    );
}

function ListCard({ title, items, tone }: { title: string; items: string[]; tone: 'success' | 'warning' }) {
    if (items.length === 0) return null;
    return (
        <div className={tone === 'success' ? 'rounded-xl bg-emerald-50 p-5' : 'rounded-xl bg-amber-50 p-5'}>
            <h4 className="mb-3 font-semibold text-gray-900">{title}</h4>
            <ul className="space-y-2 text-sm text-gray-700">
                {items.map((item, index) => (
                    <li key={index} className="flex items-start gap-2">
                        <span className={tone === 'success' ? 'text-emerald-600' : 'text-amber-600'}>•</span>
                        <span>{item}</span>
                    </li>
                ))}
            </ul>
        </div>
    );
}

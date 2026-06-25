'use client';

import { useEffect, useMemo, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    AlertCircle,
    CheckCircle2,
    ChevronDown,
    FileText,
    HeartHandshake,
    Loader2,
    MessageSquare,
    PencilLine,
    PhoneCall,
    Plus,
    Save,
    Scale,
    Sparkles,
    Trash2,
    X,
} from 'lucide-react';
import { useInterviewStore } from '@/store/useInterviewStore';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Skeleton } from '@/components/ui/skeleton';
import type {
    ApplicationEvent,
    UpdateApplicationRequest,
} from '@/lib/api/applications';

interface Props {
    applicationId: number | null;
    onClose: () => void;
}

type Priority = 'high' | 'medium' | 'low';

const eventMeta: Record<string, { label: string; color: string; icon: LucideIcon }> = {
    saved: { label: '已收藏', color: 'bg-slate-100 text-slate-700 border-slate-200', icon: Sparkles },
    applied: { label: '已投递', color: 'bg-orange-100 text-orange-700 border-orange-200', icon: CheckCircle2 },
    phone_screen: { label: '电话面试', color: 'bg-cyan-100 text-cyan-700 border-cyan-200', icon: PhoneCall },
    technical: { label: '技术面', color: 'bg-emerald-100 text-emerald-700 border-emerald-200', icon: FileText },
    behavioral: { label: '行为面', color: 'bg-blue-100 text-blue-700 border-blue-200', icon: MessageSquare },
    final: { label: '终面', color: 'bg-violet-100 text-violet-700 border-violet-200', icon: Scale },
    offer: { label: 'Offer', color: 'bg-amber-100 text-amber-700 border-amber-200', icon: HeartHandshake },
    rejected: { label: '已拒绝', color: 'bg-rose-100 text-rose-700 border-rose-200', icon: X },
    accepted: { label: '已接受', color: 'bg-green-100 text-green-700 border-green-200', icon: CheckCircle2 },
    note: { label: '复盘笔记', color: 'bg-orange-100 text-orange-700 border-orange-200', icon: PencilLine },
};

const statusColorMap: Record<string, string> = {
    applied: 'bg-orange-100 text-orange-700 ring-orange-200',
    interviewing: 'bg-cyan-100 text-cyan-700 ring-cyan-200',
    offer: 'bg-amber-100 text-amber-700 ring-amber-200',
    rejected: 'bg-rose-100 text-rose-700 ring-rose-200',
    accepted: 'bg-green-100 text-green-700 ring-green-200',
};

function formatTime(value: string) {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN', { hour12: false });
}

function getEventNotes(event: ApplicationEvent) {
    const data = event.event_data || {};
    const values = Object.entries(data)
        .filter(([key, value]) => value != null && key !== 'type')
        .map(([key, value]) => `${key}: ${String(value)}`);
    return values.length ? values.join(' · ') : '暂无备注';
}

function priorityLabel(priority?: string) {
    if (priority === 'high') return '高';
    if (priority === 'low') return '低';
    return '中';
}

export function ApplicationDetailDrawer({ applicationId, onClose }: Props) {
    const currentApplication = useInterviewStore((s) => s.currentApplication);
    const loading = useInterviewStore((s) => s.applicationDetailLoading);
    const selectApplication = useInterviewStore((s) => s.selectApplication);
    const updateApplication = useInterviewStore((s) => s.updateApplication);
    const deleteApplication = useInterviewStore((s) => s.deleteApplication);
    const addApplicationEvent = useInterviewStore((s) => s.addApplicationEvent);
    const clearCurrentApplication = useInterviewStore((s) => s.clearCurrentApplication);

    const [draft, setDraft] = useState<UpdateApplicationRequest>({});
    const [saving, setSaving] = useState(false);
    const [openDelete, setOpenDelete] = useState(false);
    const [showNoteComposer, setShowNoteComposer] = useState(false);
    const [noteText, setNoteText] = useState('');

    useEffect(() => {
        if (applicationId != null) {
            void selectApplication(applicationId);
        } else {
            clearCurrentApplication();
        }
    }, [applicationId, selectApplication, clearCurrentApplication]);

    useEffect(() => {
        if (currentApplication?.id === applicationId) {
            queueMicrotask(() => {
                setDraft({
                    company_name: currentApplication.company_name,
                    job_title: currentApplication.job_title,
                    job_description: currentApplication.job_description ?? '',
                    channel: currentApplication.channel ?? '',
                    generated_resume_id:
                        currentApplication.generated_resume_id == null ? undefined : currentApplication.generated_resume_id,
                    latest_status: currentApplication.latest_status,
                    priority: currentApplication.priority,
                    notes: currentApplication.notes ?? '',
                });
            });
        }
    }, [currentApplication, applicationId]);

    const hasApplication = !!currentApplication && currentApplication.id === applicationId;
    const sortedEvents = useMemo(
        () => (hasApplication ? [...currentApplication.events].sort((a, b) => +new Date(a.event_time) - +new Date(b.event_time)) : []),
        [hasApplication, currentApplication]
    );

    async function handleSave() {
        if (!hasApplication || !applicationId) return;
        const changes: UpdateApplicationRequest = {};
        if (draft.company_name !== currentApplication.company_name) changes.company_name = draft.company_name?.trim();
        if (draft.job_title !== currentApplication.job_title) changes.job_title = draft.job_title?.trim();
        if ((draft.job_description ?? '') !== (currentApplication.job_description ?? '')) changes.job_description = draft.job_description?.trim();
        if ((draft.channel ?? '') !== (currentApplication.channel ?? '')) changes.channel = draft.channel?.trim();
        if ((draft.generated_resume_id ?? null) !== currentApplication.generated_resume_id) changes.generated_resume_id = draft.generated_resume_id;
        if ((draft.latest_status ?? '') !== currentApplication.latest_status) changes.latest_status = draft.latest_status;
        if ((draft.priority ?? '') !== currentApplication.priority) changes.priority = draft.priority;
        if ((draft.notes ?? '') !== (currentApplication.notes ?? '')) changes.notes = draft.notes?.trim();

        if (Object.keys(changes).length === 0) return;
        setSaving(true);
        await updateApplication(applicationId, changes);
        await selectApplication(applicationId);
        setSaving(false);
    }

    async function handleQuickEvent(event_type: string, event_data?: Record<string, unknown>) {
        if (!applicationId) return;
        await addApplicationEvent(applicationId, {
            event_type,
            event_data,
            event_time: new Date().toISOString(),
        });
        await selectApplication(applicationId);
    }

    async function handleAddNoteEvent() {
        if (!applicationId || !noteText.trim()) return;
        await handleQuickEvent('note', { note: noteText.trim() });
        setNoteText('');
        setShowNoteComposer(false);
    }

    async function handleDelete() {
        if (!applicationId) return;
        const ok = await deleteApplication(applicationId);
        if (ok) {
            setOpenDelete(false);
            onClose();
        }
    }

    if (applicationId == null) return null;

    return (
        <>
            <div className="fixed inset-0 z-40">
                <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={onClose} />
                <aside
                    className={cn(
                        'absolute right-0 top-0 h-full w-full max-w-[480px] bg-white shadow-2xl ring-1 ring-black/5 transition-transform duration-300 ease-out',
                        'translate-x-0'
                    )}
                    role="dialog"
                    aria-modal="true"
                >
                    <div className="flex h-full flex-col">
                        <div className="border-b border-slate-200 px-5 py-4">
                            {loading && !hasApplication ? (
                                <div className="space-y-3">
                                    <Skeleton className="h-6 w-40" />
                                    <Skeleton className="h-4 w-56" />
                                    <Skeleton className="h-24 w-full" />
                                </div>
                            ) : (
                                <>
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0 flex-1 space-y-3">
                                            <Input
                                                value={draft.company_name ?? ''}
                                                onChange={(e) => setDraft((p) => ({ ...p, company_name: e.target.value }))}
                                                className="h-10 border-orange-100 bg-orange-50/40 text-lg font-semibold"
                                                placeholder="公司名称"
                                            />
                                            <Input
                                                value={draft.job_title ?? ''}
                                                onChange={(e) => setDraft((p) => ({ ...p, job_title: e.target.value }))}
                                                className="h-9 text-sm text-slate-600"
                                                placeholder="岗位名称"
                                            />
                                            <div className="flex flex-wrap items-center gap-2">
                                                <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium ring-1', statusColorMap[currentApplication?.latest_status || ''] || 'bg-slate-100 text-slate-700 ring-slate-200')}>
                                                    {currentApplication?.latest_status || 'unknown'}
                                                </span>
                                                <span className="rounded-full bg-orange-50 px-2.5 py-1 text-xs font-medium text-orange-700 ring-1 ring-orange-100">
                                                    优先级 {priorityLabel(currentApplication?.priority)}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-1">
                                            <Button variant="ghost" size="icon-sm" onClick={onClose}>
                                                <X className="h-4 w-4" />
                                            </Button>
                                        </div>
                                    </div>

                                    <div className="mt-4 flex items-center gap-2">
                                        <Button onClick={handleSave} className="bg-orange-600 hover:bg-orange-700" disabled={saving || loading}>
                                            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                            保存
                                        </Button>
                                        <Button variant="outline" onClick={() => setOpenDelete(true)} className="text-rose-600 hover:text-rose-700">
                                            <Trash2 className="h-4 w-4" />
                                            删除
                                        </Button>
                                    </div>
                                </>
                            )}
                        </div>

                        <ScrollArea className="flex-1">
                            <div className="space-y-6 px-5 py-5">
                                {loading && !hasApplication ? (
                                    <div className="space-y-4">
                                        <Skeleton className="h-40 w-full" />
                                        <Skeleton className="h-40 w-full" />
                                        <Skeleton className="h-56 w-full" />
                                    </div>
                                ) : (
                                    <>
                                        <section className="space-y-3">
                                            <h3 className="text-sm font-semibold text-slate-900">基础信息</h3>
                                            <div className="grid gap-3">
                                                <div className="grid gap-1.5">
                                                    <Label>投递渠道</Label>
                                                    <Input value={draft.channel ?? ''} onChange={(e) => setDraft((p) => ({ ...p, channel: e.target.value }))} placeholder="如：Boss 直聘 / 内推" />
                                                </div>
                                                <div className="grid gap-1.5">
                                                    <Label>优先级</Label>
                                                    <select
                                                        value={draft.priority ?? 'medium'}
                                                        onChange={(e) => setDraft((p) => ({ ...p, priority: e.target.value as Priority }))}
                                                        className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-orange-500/20"
                                                    >
                                                        <option value="high">high</option>
                                                        <option value="medium">medium</option>
                                                        <option value="low">low</option>
                                                    </select>
                                                </div>
                                                <div className="grid gap-1.5">
                                                    <Label>关联简历 ID</Label>
                                                    <Input type="number" value={draft.generated_resume_id ?? ''} onChange={(e) => setDraft((p) => ({ ...p, generated_resume_id: e.target.value === '' ? undefined : Number(e.target.value) }))} placeholder="简历编号" />
                                                </div>
                                                <div className="grid gap-1.5">
                                                    <Label>备注</Label>
                                                    <Textarea value={draft.notes ?? ''} onChange={(e) => setDraft((p) => ({ ...p, notes: e.target.value }))} rows={4} placeholder="投递备注、跟进信息等" />
                                                </div>
                                            </div>
                                        </section>

                                        <Separator />

                                        <details open className="group rounded-xl border border-slate-200 bg-slate-50/60 p-4">
                                            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold text-slate-900">
                                                <span className="flex items-center gap-2"><FileText className="h-4 w-4 text-orange-600" /> JD 详情</span>
                                                <ChevronDown className="h-4 w-4 text-slate-500 transition-transform group-open:rotate-180" />
                                            </summary>
                                            <div className="mt-3 space-y-3">
                                                <Textarea
                                                    value={draft.job_description ?? ''}
                                                    onChange={(e) => setDraft((p) => ({ ...p, job_description: e.target.value }))}
                                                    rows={8}
                                                    placeholder="岗位描述"
                                                />
                                            </div>
                                        </details>

                                        <section className="space-y-3">
                                            <h3 className="text-sm font-semibold text-slate-900">事件时间线</h3>
                                            <div className="space-y-3">
                                                {sortedEvents.length === 0 ? (
                                                    <div className="rounded-xl border border-dashed border-slate-200 p-6 text-sm text-slate-500">暂无事件</div>
                                                ) : (
                                                    sortedEvents.map((event) => {
                                                        const meta = eventMeta[event.event_type] || { label: event.event_type, color: 'bg-slate-100 text-slate-700 border-slate-200', icon: AlertCircle };
                                                        const Icon = meta.icon;
                                                        return (
                                                            <div key={event.id} className="rounded-xl border border-slate-200 p-4">
                                                                <div className="flex items-start gap-3">
                                                                    <div className={cn('mt-0.5 inline-flex h-9 w-9 items-center justify-center rounded-full border', meta.color)}>
                                                                        <Icon className="h-4 w-4" />
                                                                    </div>
                                                                    <div className="min-w-0 flex-1">
                                                                        <div className="flex flex-wrap items-center gap-2">
                                                                            <span className="font-medium text-slate-900">{meta.label}</span>
                                                                            <span className="text-xs text-slate-500">{formatTime(event.event_time)}</span>
                                                                        </div>
                                                                        <p className="mt-1 text-sm text-slate-600 break-words">{getEventNotes(event)}</p>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        );
                                                    })
                                                )}
                                            </div>
                                        </section>

                                        <Separator />

                                        <section className="space-y-3 pb-4">
                                            <div className="flex items-center justify-between">
                                                <h3 className="text-sm font-semibold text-slate-900">添加事件</h3>
                                                <Button variant="ghost" size="sm" onClick={() => setShowNoteComposer((v) => !v)}>
                                                    <Plus className="h-4 w-4" /> 添加复盘笔记
                                                </Button>
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                {[
                                                    ['applied', '已投递'],
                                                    ['phone_screen', '约面'],
                                                    ['behavioral', '一面'],
                                                    ['technical', '二面'],
                                                    ['final', '终面'],
                                                    ['offer', 'Offer'],
                                                    ['rejected', '已拒绝'],
                                                ].map(([type, label]) => (
                                                    <Button key={type} variant="outline" size="sm" onClick={() => void handleQuickEvent(type)} className="border-orange-100 text-orange-700 hover:bg-orange-50">
                                                        {label}
                                                    </Button>
                                                ))}
                                            </div>

                                            {showNoteComposer && (
                                                <div className="rounded-xl border border-orange-200 bg-orange-50/50 p-4 space-y-3">
                                                    <Textarea value={noteText} onChange={(e) => setNoteText(e.target.value)} rows={4} placeholder="输入复盘笔记..." />
                                                    <div className="flex justify-end gap-2">
                                                        <Button variant="outline" onClick={() => setShowNoteComposer(false)}>取消</Button>
                                                        <Button onClick={() => void handleAddNoteEvent()} className="bg-orange-600 hover:bg-orange-700">保存笔记</Button>
                                                    </div>
                                                </div>
                                            )}
                                        </section>
                                    </>
                                )}
                            </div>
                        </ScrollArea>
                    </div>
                </aside>
            </div>

            <AlertDialog open={openDelete} onOpenChange={setOpenDelete}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>删除投递记录？</AlertDialogTitle>
                        <AlertDialogDescription>此操作不可撤销，记录和事件将被永久删除。</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction onClick={() => void handleDelete()} className="bg-rose-600 hover:bg-rose-700">删除</AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}

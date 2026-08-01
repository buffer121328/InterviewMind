'use client';

import { BriefcaseBusiness, Loader2, Save } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { GreetingItem } from '@/lib/api/jobs';
import { TONE_LABELS } from '@/lib/bossCenter';

interface BossGreetingEditorListProps {
    jobId: number;
    greetings: GreetingItem[];
    actionKey: string | null;
    onChange: (index: number, value: string) => void;
    onSave: (jobId: number, greetingIndex: number, messageText: string) => void;
    onExport: (jobId: number, greetingIndex: number, messageText: string) => void;
}

/** Renders three editable greeting schemes and exposes only save/export actions, never automatic sending. */
export function BossGreetingEditorList({
    jobId,
    greetings,
    actionKey,
    onChange,
    onSave,
    onExport,
}: BossGreetingEditorListProps) {
    return (
        <div className="space-y-3">
            {greetings.map((greeting, index) => (
                <div key={`${jobId}-${greeting.tone}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-semibold text-teal-700">
                            {TONE_LABELS[greeting.tone] || greeting.tone}
                        </div>
                        <div className="text-[10px] text-slate-400">{greeting.message_text.length} 字符</div>
                    </div>
                    <Textarea
                        className="mt-2 min-h-28 bg-white text-sm leading-6"
                        value={greeting.message_text}
                        onChange={event => onChange(index, event.target.value)}
                        maxLength={500}
                    />
                    {greeting.highlights_used && greeting.highlights_used.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                            {greeting.highlights_used.map(item => <Badge key={item} variant="outline">证据：{item}</Badge>)}
                        </div>
                    )}
                    {greeting.risk_notes && <p className="mt-2 text-xs text-amber-700">{greeting.risk_notes}</p>}
                    <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={actionKey !== null}
                            onClick={() => void onSave(jobId, index, greeting.message_text)}
                        >
                            {actionKey === `save:${jobId}:${index}` ? <Loader2 className="animate-spin" /> : <Save />}
                            保存文案
                        </Button>
                        <Button
                            size="sm"
                            className="bg-teal-700 hover:bg-teal-800"
                            disabled={actionKey !== null}
                            onClick={() => void onExport(jobId, index, greeting.message_text)}
                        >
                            {actionKey === `export:${jobId}:${index}` ? <Loader2 className="animate-spin" /> : <BriefcaseBusiness />}
                            加入投递管理
                        </Button>
                    </div>
                </div>
            ))}
            {greetings.length === 0 && (
                <div className="rounded-xl border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500">
                    资产文案尚未生成，请等待后台任务完成或在任务运行中重试。
                </div>
            )}
        </div>
    );
}

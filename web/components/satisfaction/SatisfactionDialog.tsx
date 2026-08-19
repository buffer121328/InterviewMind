'use client';

import { useEffect, useState } from 'react';
import { Loader2, Star } from 'lucide-react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { submitSatisfaction, type SatisfactionSubmission } from '@/lib/api/satisfaction';
import { satisfactionAspects, type SatisfactionAgentType } from '@/lib/satisfaction/aspects';

interface SatisfactionDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    agentType: SatisfactionAgentType;
    refKey: string;
    title?: string;
    /** 提交成功并关闭弹窗后触发（由调用方负责 markSatisfactionAsked 等收尾） */
    onSubmitted?: () => void;
}

/**
 * 用户满意度反馈弹窗（受控组件）。
 * 星级可不选、方面可多选、说明可选填；"稍后再说"/右上角 X 仅关闭、不提交，是否标记已询问由调用方决定。
 */
export function SatisfactionDialog({ open, onOpenChange, agentType, refKey, title, onSubmitted }: SatisfactionDialogProps) {
    const [rating, setRating] = useState<number | null>(null);
    const [satisfied, setSatisfied] = useState<string[]>([]);
    const [dissatisfied, setDissatisfied] = useState<string[]>([]);
    const [comment, setComment] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const aspects = satisfactionAspects(agentType);

    // 每次打开时重置表单，避免上次选择残留
    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (open) {
            setRating(null);
            setSatisfied([]);
            setDissatisfied([]);
            setComment('');
        }
    }, [open]);
    /* eslint-enable react-hooks/set-state-in-effect */

    /** 切换某个 chip 方面的选中态 */
    function toggleAspect(list: string[], value: string): string[] {
        return list.includes(value) ? list.filter(item => item !== value) : [...list, value];
    }

    /** 提交当前选择（允许空星级/空方面），成功后关闭并由调用方标记已询问 */
    async function handleSubmit() {
        if (submitting) return;
        setSubmitting(true);
        try {
            const payload: SatisfactionSubmission = {
                agent_type: agentType,
                ref_key: refKey,
                rating,
                satisfied_aspects: satisfied,
                dissatisfied_aspects: dissatisfied,
                comment: comment.trim() ? comment.trim() : null,
            };
            await submitSatisfaction(payload);
            toast.success('感谢您的反馈');
            onOpenChange(false);
            onSubmitted?.();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : '反馈提交失败');
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{title ?? '这次体验怎么样?'}</DialogTitle>
                    <DialogDescription>您的反馈会匿名计入评测统计，可选填，随时可关闭。</DialogDescription>
                </DialogHeader>

                <div className="space-y-5">
                    {/* 1-5 星评分：不选星级时提交即留空 */}
                    <div className="flex items-center justify-center gap-1">
                        {[1, 2, 3, 4, 5].map(star => (
                            <button
                                key={star}
                                type="button"
                                aria-label={`${star} 星`}
                                onClick={() => setRating(rating === star ? null : star)}
                                className="p-1 transition-transform hover:scale-110 focus:outline-none"
                            >
                                <Star
                                    className={cn(
                                        'h-8 w-8 transition-colors',
                                        (rating ?? 0) >= star ? 'fill-amber-400 text-amber-400' : 'text-slate-300'
                                    )}
                                />
                            </button>
                        ))}
                    </div>

                    {/* 满意的方面 / 不满意的方面：chip 多选 */}
                    <div className="space-y-3">
                        <div>
                            <p className="mb-2 text-sm font-medium text-slate-700">满意的方面</p>
                            <div className="flex flex-wrap gap-2">
                                {aspects.satisfied.map(aspect => (
                                    <button
                                        key={aspect}
                                        type="button"
                                        onClick={() => setSatisfied(current => toggleAspect(current, aspect))}
                                        className={cn(
                                            'rounded-full border px-3 py-1.5 text-sm transition-colors',
                                            satisfied.includes(aspect)
                                                ? 'border-teal-500 bg-teal-50 text-teal-700'
                                                : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                                        )}
                                    >
                                        {aspect}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div>
                            <p className="mb-2 text-sm font-medium text-slate-700">不满意的方面</p>
                            <div className="flex flex-wrap gap-2">
                                {aspects.dissatisfied.map(aspect => (
                                    <button
                                        key={aspect}
                                        type="button"
                                        onClick={() => setDissatisfied(current => toggleAspect(current, aspect))}
                                        className={cn(
                                            'rounded-full border px-3 py-1.5 text-sm transition-colors',
                                            dissatisfied.includes(aspect)
                                                ? 'border-teal-500 bg-teal-50 text-teal-700'
                                                : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                                        )}
                                    >
                                        {aspect}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* 可选文字说明 */}
                    <div>
                        <p className="mb-2 text-sm font-medium text-slate-700">补充说明（选填）</p>
                        <Textarea
                            value={comment}
                            onChange={event => setComment(event.target.value)}
                            placeholder="写点想说的，帮助我们改进"
                            rows={3}
                            disabled={submitting}
                        />
                    </div>
                </div>

                <DialogFooter className="gap-2">
                    <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
                        稍后再说
                    </Button>
                    <Button onClick={() => void handleSubmit()} disabled={submitting}>
                        {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                        提交反馈
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

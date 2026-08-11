'use client';

import { useRef, type ChangeEvent } from 'react';
import { Loader2, Search, Sparkles, Upload } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { BOSS_HOT_CITIES } from '@/lib/bossCenter';

interface BossSearchCapturePanelProps {
    query: string;
    onQueryChange: (value: string) => void;
    city: string;
    onCityChange: (value: string) => void;
    topN: number;
    onTopNChange: (value: number) => void;
    resumeContent: string;
    onResumeContentChange: (value: string) => void;
    resumeUploading: boolean;
    onResumeUpload: (event: ChangeEvent<HTMLInputElement>) => void;
    captureBusy: boolean;
    checkingTab: boolean;
    onCapture: () => void;
}

/** Renders the search keyword, city, top-N and base-resume controls used to start a capture run. */
export function BossSearchCapturePanel({
    query,
    onQueryChange,
    city,
    onCityChange,
    topN,
    onTopNChange,
    resumeContent,
    onResumeContentChange,
    resumeUploading,
    onResumeUpload,
    captureBusy,
    checkingTab,
    onCapture,
}: BossSearchCapturePanelProps) {
    const resumeFileInputRef = useRef<HTMLInputElement>(null);

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base"><Search className="h-4 w-4" />搜索与简历匹配</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <label className="grid gap-2 text-xs text-slate-600">搜索关键词
                    <Input value={query} onChange={event => onQueryChange(event.target.value)} maxLength={200} placeholder="例如 Agent 后端工程师" />
                </label>
                <div className="grid gap-3 sm:grid-cols-[1fr_130px] xl:grid-cols-1">
                    <label className="grid gap-2 text-xs text-slate-600">热门城市（中文选择）
                        <Select value={city || "reuse-current"} onValueChange={value => onCityChange(value === "reuse-current" ? "" : value)}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                            <SelectContent>
                                <SelectItem value="reuse-current">复用当前页城市</SelectItem>
                                {BOSS_HOT_CITIES.map(item => (
                                    <SelectItem key={item.code} value={item.code}>{item.name}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </label>
                    <label className="grid gap-2 text-xs text-slate-600">已选城市代码
                        <Input value={city} readOnly placeholder="复用当前页" className="font-mono" />
                    </label>
                </div>
                <label className="grid gap-2 text-xs text-slate-600">结果数量（最多 20）
                    <Input
                        type="number"
                        min={1}
                        max={20}
                        value={topN}
                        onChange={event => onTopNChange(Math.min(20, Math.max(1, Number(event.target.value) || 1)))}
                    />
                </label>
                <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-900">
                    基础简历只提取专业技能参与筛选：先计算透明关键词重合分，再由 Fast 模型做语义匹配，默认按 20% 关键词分 + 80% 语义分排序；模型解析失败时自动回退本地关键词分。
                </div>
                <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-xs text-slate-600">基础简历</span>
                        <input ref={resumeFileInputRef} type="file" className="hidden" accept=".pdf,.doc,.docx,.txt,.md" onChange={event => onResumeUpload(event)} />
                        <Button type="button" variant="outline" size="sm" disabled={resumeUploading} onClick={() => resumeFileInputRef.current?.click()}>
                            {resumeUploading ? <Loader2 className="animate-spin" /> : <Upload />}
                            {resumeUploading ? "解析中" : "上传并解析"}
                        </Button>
                    </div>
                    <Textarea
                        className="min-h-56 text-xs leading-5"
                        value={resumeContent}
                        onChange={event => onResumeContentChange(event.target.value)}
                        placeholder="粘贴简历；采集时只使用专业技能段落，用于岗位排序与打招呼文案。"
                    />
                </div>
                <Button className="w-full bg-teal-700 hover:bg-teal-800" onClick={() => void onCapture()} disabled={captureBusy || checkingTab}>
                    {captureBusy ? <Loader2 className="animate-spin" /> : <Sparkles />}
                    接管页面并采集
                </Button>
            </CardContent>
        </Card>
    );
}

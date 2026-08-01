'use client';

import { Loader2, Monitor, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import type { BossBrowserChannel, BossTabStatusResponse } from '@/lib/api/jobs';

interface BossTabStatusCardProps {
    browserChannel: BossBrowserChannel;
    onBrowserChannelChange: (channel: BossBrowserChannel) => void;
    checkingTab: boolean;
    onCheckTab: () => void;
    tabStatus: BossTabStatusResponse | null;
    tabError: string | null;
}

/** Renders the existing BOSS browser-tab status card; it never starts or closes a browser. */
export function BossTabStatusCard({
    browserChannel,
    onBrowserChannelChange,
    checkingTab,
    onCheckTab,
    tabStatus,
    tabError,
}: BossTabStatusCardProps) {
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base"><Monitor className="h-4 w-4" />现有 BOSS 标签页</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <label className="grid gap-2 text-xs text-slate-600">浏览器
                    <Select value={browserChannel} onValueChange={value => onBrowserChannelChange(value as BossBrowserChannel)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                            <SelectItem value="msedge">Microsoft Edge</SelectItem>
                            <SelectItem value="chrome">Google Chrome</SelectItem>
                        </SelectContent>
                    </Select>
                </label>
                <Button variant="outline" className="w-full" disabled={checkingTab} onClick={() => onCheckTab()}>
                    {checkingTab ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                    检查已打开页面
                </Button>
                {tabStatus && (
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-800">
                        <div className="font-semibold">{tabStatus.browser_label} · {tabStatus.page_status}</div>
                        <div>{tabStatus.message}</div>
                        {tabStatus.visible_card_count > 0 && <div>当前识别 {tabStatus.visible_card_count} 张岗位卡片</div>}
                    </div>
                )}
                {tabError && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">{tabError}</div>}
            </CardContent>
        </Card>
    );
}

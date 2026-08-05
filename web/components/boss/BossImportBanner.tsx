'use client';

import { Database, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';

interface BossImportBannerProps {
    pendingCardCount: number;
    actionKey: string | null;
    onImportAll: () => void;
}

/** Prompts one-click import of every pending capture card into the job library; the user confirms the action. */
export function BossImportBanner({ pendingCardCount, actionKey, onImportAll }: BossImportBannerProps) {
    return (
        <div className="surface-panel flex flex-wrap items-center justify-between gap-3 border-amber-200 p-4">
            <div className="text-sm text-slate-700">
                已采集 <span className="font-semibold text-amber-700">{pendingCardCount}</span> 个岗位，确认后一键入库（只写入岗位库，不会自动调用模型）。
            </div>
            <Button className="bg-teal-700 hover:bg-teal-800" disabled={actionKey !== null} onClick={() => void onImportAll()}>
                {actionKey === "import:all" ? <Loader2 className="animate-spin" /> : <Database />}
                一键入库
            </Button>
        </div>
    );
}

'use client';

import { Home, PanelLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SessionSidebar } from '@/components/SessionSidebar';
import type { WorkspaceView } from '@/lib/navigation';

interface WorkspaceShellProps {
    sidebarOpen: boolean;
    onSidebarOpenChange: (open: boolean) => void;
    currentView: WorkspaceView;
    onViewChange: (view: WorkspaceView) => void;
    onOpenSettings: () => void;
    onGoHome: () => void;
    onViewSessionDetail?: (sessionId: string) => void;
    icon: React.ReactNode;
    title: string;
    description: string;
    actions?: React.ReactNode;
    children: React.ReactNode;
    contentClassName?: string;
}

/** Renders the workspace shell UI and coordinates its typed props, local state, and approved backend interactions. */
export function WorkspaceShell({
    sidebarOpen,
    onSidebarOpenChange,
    currentView,
    onViewChange,
    onOpenSettings,
    onGoHome,
    onViewSessionDetail,
    icon,
    title,
    description,
    actions,
    children,
    contentClassName = '',
}: WorkspaceShellProps) {
    return (
        <div className="flex h-[100dvh] w-full overflow-hidden bg-[#f7faf9] text-slate-950">
            <SessionSidebar
                isOpen={sidebarOpen}
                onClose={() => onSidebarOpenChange(false)}
                onOpenSettings={onOpenSettings}
                onGoHome={onGoHome}
                currentView={currentView}
                onViewChange={onViewChange}
                onViewSessionDetail={onViewSessionDetail}
            />
            <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
                <header className="z-20 flex min-h-16 items-center justify-between gap-4 border-b border-slate-200 bg-white/90 px-4 backdrop-blur-xl sm:px-6">
                    <div className="flex min-w-0 items-center gap-3">
                        {!sidebarOpen && (
                            <Button variant="ghost" size="icon" onClick={() => onSidebarOpenChange(true)} aria-label="打开侧边栏">
                                <PanelLeft className="h-5 w-5" />
                            </Button>
                        )}
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-950 text-teal-100">
                            {icon}
                        </div>
                        <div className="min-w-0">
                            <h1 className="truncate text-sm font-semibold text-slate-950 sm:text-base">{title}</h1>
                            <p className="hidden truncate text-xs text-slate-500 sm:block">{description}</p>
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        {actions}
                        <Button
                            variant="ghost"
                            size="sm"
                            className="text-slate-500"
                            onClick={onGoHome}
                            aria-label="返回产品首页"
                        >
                            <Home className="h-4 w-4" />
                            <span className="hidden sm:inline">首页</span>
                        </Button>
                    </div>
                </header>
                <div className={`flex min-h-0 flex-1 flex-col overflow-hidden ${contentClassName}`}>
                    {children}
                </div>
            </main>
        </div>
    );
}

'use client';

import { useEffect } from 'react';
import Image from 'next/image';
import { AnimatePresence, motion } from 'framer-motion';
import {
    Activity,
    Award,
    BookOpenCheck,
    BriefcaseBusiness,
    Database,
    FileText,
    Home,
    MessageCircle,
    PanelLeftClose,
    Plus,
    Settings,
    ShieldCheck,
    Sparkles,
    Target,
    UserRound,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SessionList } from './SessionList';
import { ResumeHistoryList } from './ResumeHistoryList';
import { cn } from '@/lib/utils';
import { Avatar } from '@/components/ui/avatar';
import { useInterviewStore } from '@/store/useInterviewStore';
import type { WorkspaceView } from '@/lib/navigation';
import { PRODUCT_NAME } from '@/lib/product';
import { toast } from 'sonner';

interface SessionSidebarProps {
    isOpen: boolean;
    onClose: () => void;
    onOpenSettings: () => void;
    onGoHome: () => void;
    currentView: WorkspaceView;
    onViewChange: (view: WorkspaceView) => void;
    onViewSessionDetail?: (sessionId: string) => void;
}

const NAV_SECTIONS: Array<{
    label: string;
    items: Array<{ view: WorkspaceView; label: string; icon: typeof MessageCircle }>;
}> = [
    {
        label: '求职准备',
        items: [
            { view: 'interview', label: '模拟面试', icon: MessageCircle },
            { view: 'resume', label: '简历工作台', icon: FileText },
            { view: 'questionbank', label: '题库与面经', icon: BookOpenCheck },
        ],
    },
    {
        label: '机会管理',
        items: [
            { view: 'boss', label: '岗位中心', icon: Target },
            { view: 'applications', label: '投递管理', icon: BriefcaseBusiness },
        ],
    },
    {
        label: 'Agent 系统',
        items: [
            { view: 'memory', label: '长期记忆', icon: Database },
            { view: 'runs', label: '任务运行', icon: Activity },
            { view: 'prompts', label: 'Prompt 管理', icon: Sparkles },
            { view: 'evaluations', label: 'Agent 评测', icon: ShieldCheck },
        ],
    },
];

const VIEW_CONTEXT: Record<WorkspaceView, { title: string; description: string }> = {
    interview: { title: '面试会话', description: '继续历史面试或创建新一轮。' },
    resume: { title: '简历记录', description: '分析、JD 匹配与生成版本。' },
    questionbank: { title: '题库与面经', description: '维护个人题目、导入文件并沉淀历史追问。' },
    boss: { title: '岗位中心', description: '采集岗位、生成投递资产并保留人工确认。' },
    applications: { title: '投递管理', description: '跟踪岗位状态、简历版本和面试事件。' },
    memory: { title: '长期记忆', description: '搜索、审计和删除用于个性化的 mem0 记忆。' },
    runs: { title: '任务运行', description: '查看 AgentRun 阶段、失败原因、取消与重试。' },
    prompts: { title: 'Prompt 管理', description: '查看、预览和安全发布不可变的 Prompt 版本。' },
    evaluations: { title: 'Agent 评测', description: '运行评测、人工标注、校准 Judge 并检查发布门禁。' },
};

/** Encapsulates session sidebar; returns typed data or state and keeps side effects within the owning module boundary. */
export function SessionSidebar({
    isOpen,
    onClose,
    onOpenSettings,
    onGoHome,
    currentView,
    onViewChange,
    onViewSessionDetail,
}: SessionSidebarProps) {
    const {
        sessions,
        sessionsTotal,
        currentSession,
        sessionLoading,
        fetchSessions,
        selectSession,
        createNewSession,
        deleteSession,
        updateSessionTitle,
        togglePinSession,
        resumeResults,
        currentResumeResult,
        resumeResultLoading,
        fetchResumeResults,
        resumeResultsTotal,
        selectResumeResult,
        deleteResumeResult,
        clearResumeResult,
        setShowAbilityProfile,
        apiConfig,
    } = useInterviewStore();

    useEffect(() => {
        if (currentView !== 'resume') return;
        if (resumeResults.length === 0) void fetchResumeResults();
    }, [currentView, fetchResumeResults, resumeResults.length]);

    /** Encapsulates close on mobile; returns typed data or state and keeps side effects within the owning module boundary. */
    const closeOnMobile = () => {
        if (window.innerWidth < 768) onClose();
    };

    /** Handles session select; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSessionSelect = (sessionId: string) => {
        void selectSession(sessionId);
        closeOnMobile();
    };

    /** Handles session detail; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleSessionDetail = (sessionId: string) => {
        onViewSessionDetail?.(sessionId);
        closeOnMobile();
    };

    /** Handles resume select; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleResumeSelect = async (resultId: number) => {
        if (await selectResumeResult(resultId)) closeOnMobile();
        else toast.error('加载简历记录失败，请重试');
    };

    /** Handles new; updates local UI state first and delegates server mutations through the approved API boundary. */
    const handleNew = () => {
        if (currentView === 'interview') createNewSession();
        if (currentView === 'resume') {
            clearResumeResult();
        }
        closeOnMobile();
    };

    /** Renders the switch view UI and coordinates its typed props, local state, and approved backend interactions. */
    const switchView = (view: WorkspaceView) => {
        onViewChange(view);
        closeOnMobile();
    };

    const assignedModels = new Set([
        apiConfig.smartModelId,
        apiConfig.fastModelId,
        apiConfig.technicalDepthModelId,
        apiConfig.communicationModelId,
        apiConfig.generalModelId,
        apiConfig.matchAnalystModelId,
        apiConfig.contentWriterModelId,
        apiConfig.hrReviewerModelId,
        apiConfig.reflectorModelId,
        apiConfig.mimoModelId,
        apiConfig.ragEmbeddingModelId,
        apiConfig.mem0LlmModelId,
        apiConfig.mem0EmbedderModelId,
    ].filter(Boolean)).size;
    const coreReady = Boolean(
        apiConfig.models.find(model => model.id === apiConfig.smartModelId)?.credentialStored
        && apiConfig.models.find(model => model.id === apiConfig.fastModelId)?.credentialStored,
    );
    const showsHistory = currentView === 'interview' || currentView === 'resume';

    return (
        <>
            <AnimatePresence>
                {isOpen && (
                    <>
                        <motion.button
                            type="button"
                            aria-label="关闭侧边栏"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="fixed inset-0 z-30 bg-slate-950/25 backdrop-blur-[1px] md:hidden"
                            onClick={onClose}
                        />
                        <motion.aside
                            initial={{ x: -24, opacity: 0 }}
                            animate={{ x: 0, opacity: 1 }}
                            exit={{ x: -24, opacity: 0 }}
                            transition={{ duration: 0.18, ease: 'easeOut' }}
                            className="fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col overflow-y-auto border-r border-slate-200 bg-[#f4f8f7] shadow-xl md:relative md:z-20 md:shadow-none"
                        >
                            <div className="shrink-0 border-b border-slate-200 bg-[#102724] px-4 py-3 text-white">
                                <div className="flex items-center justify-between gap-3">
                                    <button type="button" className="flex min-w-0 items-center gap-3 text-left" onClick={onGoHome}>
                                        <Image src="/logo.png" alt="" width={38} height={38} className="rounded-xl ring-1 ring-white/10" />
                                        <div className="min-w-0">
                                            <div className="truncate text-sm font-semibold">{PRODUCT_NAME}</div>
                                            <div className="mt-0.5 text-[9px] uppercase tracking-[0.2em] text-teal-200/70">Career workspace</div>
                                        </div>
                                    </button>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={onClose}
                                        className="h-9 w-9 text-teal-50 hover:bg-white/10 hover:text-white"
                                        aria-label="收起侧边栏"
                                    >
                                        <PanelLeftClose className="h-5 w-5" />
                                    </Button>
                                </div>
                            </div>

                            <div className="shrink-0 border-b border-slate-200 px-3 py-2">
                                <button type="button" onClick={onGoHome} className="mb-1 flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-white hover:text-slate-950">
                                    <Home className="h-4 w-4" />产品首页
                                </button>
                                <div className={cn(showsHistory ? 'space-y-1' : 'space-y-2')}>
                                    {NAV_SECTIONS.map(section => (
                                        <div key={section.label}>
                                            <div className="mb-0.5 px-3 text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">{section.label}</div>
                                            <div className={cn(showsHistory ? 'grid grid-cols-2 gap-0.5' : 'space-y-0.5')}>
                                                {section.items.map(item => (
                                                    <button
                                                        type="button"
                                                        key={item.view}
                                                        onClick={() => switchView(item.view)}
                                                        className={cn(
                                                            'flex w-full items-center rounded-lg text-left transition',
                                                            showsHistory ? 'gap-2 px-2 py-1 text-xs' : 'gap-3 px-3 py-1.5 text-sm',
                                                            currentView === item.view
                                                                ? 'bg-teal-950 font-medium text-white shadow-sm'
                                                                : 'text-slate-600 hover:bg-white hover:text-slate-950',
                                                        )}
                                                    >
                                                        <item.icon className={cn('h-4 w-4', currentView === item.view ? 'text-teal-200' : 'text-slate-400')} />
                                                        {item.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {showsHistory ? (
                                <div className="flex min-h-52 shrink-0 flex-1 flex-col">
                                    <div className="px-4 pb-2 pt-4">
                                        <div className="flex items-end justify-between gap-3">
                                            <div>
                                                <div className="text-xs font-semibold text-slate-900">{VIEW_CONTEXT[currentView].title}</div>
                                                <div className="mt-0.5 text-[10px] text-slate-500">{VIEW_CONTEXT[currentView].description}</div>
                                            </div>
                                            <Button size="icon" className="h-8 w-8 shrink-0 bg-teal-700 hover:bg-teal-800" onClick={handleNew} aria-label={currentView === 'interview' ? '新建面试' : '新建简历任务'}>
                                                <Plus className="h-4 w-4" />
                                            </Button>
                                        </div>
                                    </div>

                                    <div className="min-h-0 flex-1 overflow-hidden px-3 pb-3">
                                        {currentView === 'interview' ? (
                                            <SessionList
                                                sessions={sessions}
                                                onSessionSelect={handleSessionSelect}
                                                onDeleteSession={deleteSession}
                                                onEditSession={updateSessionTitle}
                                                onTogglePin={togglePinSession}
                                                onViewDetails={onViewSessionDetail ? handleSessionDetail : undefined}
                                                currentSessionId={currentSession?.session_id}
                                                loading={sessionLoading}
                                                hasMore={sessions.length < sessionsTotal}
                                                onLoadMore={() => void fetchSessions(undefined, undefined, true)}
                                            />
                                        ) : (
                                            <ResumeHistoryList
                                                results={resumeResults}
                                                onSelect={handleResumeSelect}
                                                onDelete={deleteResumeResult}
                                                currentResultId={currentResumeResult?.id}
                                                loading={resumeResultLoading}
                                                hasMore={resumeResults.length < resumeResultsTotal}
                                                onLoadMore={() => void fetchResumeResults(undefined, true)}
                                            />
                                        )}
                                    </div>
                                </div>
                            ) : (
                                <div className="min-h-40 shrink-0 flex-1 p-4">
                                    <div className="rounded-2xl border border-slate-200 bg-white p-4">
                                        <div className="text-xs font-semibold text-slate-900">{VIEW_CONTEXT[currentView].title}</div>
                                        <p className="mt-2 text-xs leading-5 text-slate-500">{VIEW_CONTEXT[currentView].description}</p>
                                    </div>
                                </div>
                            )}

                            <div className="shrink-0 space-y-2 border-t border-slate-200 bg-white/70 p-3">
                                {currentView === 'interview' && (
                                    <Button
                                        variant="ghost"
                                        className="w-full justify-start gap-3 text-slate-600 hover:bg-white hover:text-slate-950"
                                        onClick={() => {
                                            setShowAbilityProfile(true);
                                            closeOnMobile();
                                        }}
                                    >
                                        <Award className="h-4 w-4 text-teal-700" />综合能力画像
                                    </Button>
                                )}
                                <Button variant="ghost" className="w-full justify-start gap-3 text-slate-600 hover:bg-white hover:text-slate-950" onClick={onOpenSettings}>
                                    <Settings className="h-4 w-4" />模型设置
                                </Button>
                                <div className="flex items-center gap-3 rounded-xl bg-slate-100/80 px-3 py-2.5">
                                    <Avatar className="flex h-8 w-8 items-center justify-center bg-teal-950 text-white">
                                        <UserRound className="h-4 w-4" />
                                    </Avatar>
                                    <div className="min-w-0 flex-1">
                                        <div className="text-xs font-medium text-slate-800">本地候选人工作区</div>
                                        <div className={`mt-0.5 flex items-center gap-1 text-[10px] ${coreReady ? 'text-emerald-700' : 'text-amber-700'}`}>
                                            <ShieldCheck className="h-3 w-3" />
                                            {coreReady ? `${assignedModels} 个模型连接已分配` : 'Smart / Fast 尚未就绪'}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </motion.aside>
                    </>
                )}
            </AnimatePresence>
        </>
    );
}

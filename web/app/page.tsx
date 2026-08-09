"use client";

// 已知超限:职责单一(页面编排聚合器),暂不拆分
import { useState, useEffect, useRef, useMemo, useSyncExternalStore } from "react";
import { Activity, BookOpenCheck, BriefcaseBusiness, Database, Loader2, MessageCircle, FileText, Target, Sparkles, ShieldCheck } from "lucide-react";
import { SettingsDialog } from "@/components/SettingsDialog";
import { useInterviewStore } from "@/store/useInterviewStore";
import { useSpeechToText } from "@/hooks/useSpeechToText";
import { getUserId } from "@/hooks/useUserIdentity";
import { API_BASE_URL } from "@/lib/api/config";
import { parseSavedMainView, requiresApiConfig, type MainView } from "@/lib/navigation";
import { isInterviewFinished } from "@/lib/interviewSeries";
import type { JobContextSnapshot } from "@/lib/jobContextHandoff";
import type { TargetedInterviewHandoff } from "@/lib/interviewReportStructured";
import { toast } from "sonner";
import { ResumeTools } from "@/components/ResumeTools";
import { LandingPage } from "@/components/LandingPage";
import { InterviewSetup } from "@/components/interview/InterviewSetup";
import { InterviewProgressBar } from "@/components/interview/InterviewProgressBar";
import { InterviewChatArea } from "@/components/interview/InterviewChatArea";
import { InterviewInputPanel } from "@/components/interview/InterviewInputPanel";
import { InterviewNextRoundBanner } from "@/components/interview/InterviewNextRoundBanner";
import { InterviewAbilityProfileView } from "@/components/interview/InterviewAbilityProfileView";
import { GuidePage } from "@/components/GuidePage";
import { InterviewArea } from "@/components/InterviewArea";
import { InterviewHistoryDetailDialog } from "@/components/InterviewHistoryDetailDialog";
import { ApplicationBoard } from "@/components/ApplicationBoard";
import { ApplicationDetailDrawer } from "@/components/ApplicationDetailDrawer";
import QuestionBankPage from "@/components/QuestionBankPage";
import { BossCenter } from "@/components/boss/BossCenter";
import { MemoryCenter } from "@/components/MemoryCenter";
import { RunCenter } from "@/components/RunCenter";
import { PromptManagementPage } from "@/components/PromptManagementPage";
import { EvaluationCenter } from "@/components/evaluations/EvaluationCenter";
import { WorkspaceShell } from "@/components/WorkspaceShell";

// 定义视图类型，包含 'landing'
type ViewType = MainView;

/** Supplies the stable external-store subscription required by hydration-aware rendering; this store has no runtime subscribers. */
const subscribeToHydration = () => () => {};

/** Restores the last main view from browser storage while returning the landing view during SSR or when the saved value is invalid. */
function getSavedMainTab(): ViewType {
  if (typeof window === "undefined") return "landing";

  return parseSavedMainView(localStorage.getItem("activeMainTab"));
}

/** Renders the interview page UI and coordinates its typed props, local state, and approved backend interactions. */
export default function InterviewPage() {
  // ===== 局部 UI 状态 =====
  const [showSidebar, setShowSidebar] = useState(true);
  const [showSettingsDialog, setShowSettingsDialog] = useState(false);
  const [input, setInput] = useState("");
  const isMounted = useSyncExternalStore(subscribeToHydration, () => true, () => false);
  // const [isJobDialogOpen, setIsJobDialogOpen] = useState(false); // Moved to InterviewSetup
  // const [tempJobDescription, setTempJobDescription] = useState(""); // Moved to InterviewSetup

  const [showScrollButton, setShowScrollButton] = useState(false);
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true);
  const [isAnswerComposerExpanded, setIsAnswerComposerExpanded] = useState(false);
  const [activeMainTab, setActiveMainTab] = useState<ViewType>(getSavedMainTab);
  const [hintContent, setHintContent] = useState<string | null>(null);
  const [isLoadingHint, setIsLoadingHint] = useState(false);
  const [selectedApplicationId, setSelectedApplicationId] = useState<number | null>(null);
  const [historyDetailSessionId, setHistoryDetailSessionId] = useState<string | null>(null);
  const [historyDetailInitialTab, setHistoryDetailInitialTab] = useState<'overview' | 'dialogue' | 'report'>('overview');
  const [resumeJobContext, setResumeJobContext] = useState<JobContextSnapshot | null>(null);
  const [resumeGenerationSessionId, setResumeGenerationSessionId] = useState<string | null>(null);
  const [initialBossJobId, setInitialBossJobId] = useState<number | null>(null);

  useEffect(() => {
    localStorage.setItem("activeMainTab", activeMainTab);
  }, [activeMainTab]);

  // Refs
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollViewportRef = useRef<HTMLDivElement>(null);

  // ===== Store 状态与方法 =====
  const {
    // 状态
    messages,
    isStreaming,
    isLoading,
    resume,
    jobDescription,
    companyInfo,
    jobContextSnapshot,
    interviewProgress,
    maxQuestions,
    interviewType,
    questionBankCount,
    experienceQuestions,
    currentSession,
    showAbilityProfile,
    apiConfig, // 订阅 apiConfig 以便配置更新时自动刷新
    threadId,
    isInitializing,
    initializationStage,
    executionPlan,

    // 方法
    fetchSessions,
    selectSession,
    setJobDescription,
    setCompanyInfo,
    setJobContextSnapshot,
    setMaxQuestions,
    setInterviewType,
    setQuestionBankCount,
    setExperienceQuestions,
    uploadResume,
    startInterview,
    sendMessage,
    stopStreaming,
    rollbackChat,
    setShowAbilityProfile: setStoreShowAbilityProfile,
    apiError,
    clearApiError,
    setVoiceMode,
    getMimoModel,
  } = useInterviewStore();

  const completedQuestionCount = interviewProgress?.current ?? currentSession?.metadata.question_count ?? 0;
  const completedQuestionLimit = interviewProgress?.total ?? currentSession?.metadata.max_questions ?? maxQuestions;
  const isInterviewCompleted = isInterviewFinished(
    currentSession?.metadata.status,
    completedQuestionCount,
    completedQuestionLimit,
  );

  // ===== 初始化 =====
  useEffect(() => {
    if (activeMainTab === 'interview') {
      void fetchSessions(undefined);
    }
  }, [activeMainTab, fetchSessions]);

  useEffect(() => {
    const timer = window.setTimeout(() => setIsAnswerComposerExpanded(false), 0);
    return () => window.clearTimeout(timer);
  }, [currentSession?.session_id]);

  // ===== API 错误 Toast 提示 =====
  useEffect(() => {
    if (apiError) {
      toast.error(apiError, {
        description: '请检查 API 配置后重试',
        duration: 5000,
        action: {
          label: '去配置',
          onClick: () => setShowSettingsDialog(true),
        },
      });
      clearApiError();
    }
  }, [apiError, clearApiError]);

  // ===== 语音输入 =====
  const { isListening, toggleListening } = useSpeechToText({
    onTranscript: (text) => {
      setInput((prev) => prev + text);
    }
  });

  // ===== 事件处理 =====

  // Resume upload handler for InterviewSetup
  /** Handles upload resume; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleUploadResume = async (file: File) => {
    await uploadResume(file);
  };

  // 检查是否配置了语音模型
  const hasVoiceConfig = useMemo(() => {
    return !!getMimoModel?.();
  }, [getMimoModel]);

  /** Handles start interview; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleStartInterview = async (mode: 'text' | 'voice' = 'text', options?: { interviewType: 'tech_initial' | 'tech_deep' | 'hr_comprehensive'; maxQuestions: number }) => {
    try {
      if (options) {
        useInterviewStore.setState({ interviewType: options.interviewType, maxQuestions: options.maxQuestions });
      }
      if (mode === 'voice') {
        // 语音模式：仅进行本地状态初始化，不触发文字版后端
        await startInterview('voice');
        setVoiceMode(true);
      } else {
        // 文字模式：正常开始面试
        await startInterview('mock');
      }
    } catch (error) {
      console.error('启动面试失败:', error);
      // apiError 已在 store 中设置，useEffect 会自动显示 toast
    }
  };

  /** Handles send; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleSend = async () => {
    if (isInterviewCompleted || !input.trim() || isStreaming) return;
    const content = input;
    setInput("");
    await sendMessage(content);
  };

  /** Handles key down; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ===== 消息编辑和重新生成 =====
  /** Handles edit message; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleEditMessage = async (index: number, newContent: string) => {
    if (isInterviewCompleted || isStreaming) return;
    // 回退到该消息之前的状态
    await rollbackChat(index);
    // 直接发送编辑后的消息
    await sendMessage(newContent);
  };

  /** Handles regenerate message; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleRegenerateMessage = async (aiMessageIndex: number) => {
    if (isInterviewCompleted || isStreaming) return;

    // 特殊处理：如果是第一条消息（AI开场白），则重新开始面试流程
    if (aiMessageIndex === 0) {
      await rollbackChat(0);
      if (resume) {
        await startInterview();
      }
      return;
    }

    // 找到对应的用户消息（AI消息的前一条应该是用户消息）
    const userMessageIndex = aiMessageIndex - 1;
    if (userMessageIndex < 0 || messages[userMessageIndex].role !== 'user') {
      console.error('无法找到对应的用户消息');
      return;
    }

    const userMessage = messages[userMessageIndex];
    // 回退到用户消息之前的状态
    await rollbackChat(userMessageIndex);
    // 重新发送原有的用户消息
    await sendMessage(userMessage.content);
  };

  /** Encapsulates scroll to bottom; returns typed data or state and keeps side effects within the owning module boundary. */
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    setShowScrollButton(false);
    setAutoScrollEnabled(true);
  };

  // 获取回答提示
  /** Handles get hint; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleGetHint = async () => {
    if (!threadId || isLoadingHint) return;

    setIsLoadingHint(true);
    setHintContent(null);

    try {
      // 计算当前问题索引：基于 AI 消息数量 - 1（第一条 AI 消息是问题0）
      const aiMessageCount = messages.filter(m => m.role === 'assistant').length;
      const questionIndex = Math.max(0, aiMessageCount - 1);

      const response = await fetch(
        `${API_BASE_URL}/api/chat/hint/${threadId}/${questionIndex}`,
        { headers: { 'X-User-ID': getUserId() } }
      );

      if (!response.ok) {
        throw new Error('获取提示失败');
      }

      const data = await response.json();

      if (data.generating) {
        // 提示还在生成中，显示生成中状态
        toast.info('提示正在生成中，请稍后再试', {
          duration: 2000,
        });
      } else {
        setHintContent(data.hint);
      }

    } catch (error) {
      console.error('获取提示失败:', error);
      toast.error('获取提示失败，请稍后重试');
    } finally {
      setIsLoadingHint(false);
    }
  };

  /** Handles switch to voice; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleSwitchToVoice = async () => {
    if (!threadId) return;

    // 1. 克隆会话
    try {
      const response = await fetch(`${API_BASE_URL}/api/voice/clone`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-User-ID': getUserId()
        },
        body: JSON.stringify({ source_session_id: threadId })
      });

      if (!response.ok) throw new Error('切换失败');
      const data = await response.json();
      const newSessionId = data.new_session_id;

      // 2. 刷新 Session List 并切换
      await fetchSessions(undefined);
      await selectSession(newSessionId);
      setVoiceMode(true);

      toast.success('已切换到语音面试');

    } catch (error) {
      console.error(error);
      toast.error('无法切换到语音面试');
    }
  };

  /** Handles scroll; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    // 距离底部 100px 以内视为在底部
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;

    if (isAtBottom) {
      setShowScrollButton(false);
      setAutoScrollEnabled(true);
    } else {
      setShowScrollButton(true);
      // 如果用户主动向上滚动，暂停自动滚动
      if (autoScrollEnabled && scrollHeight - scrollTop - clientHeight > 100) {
        setAutoScrollEnabled(false);
      }
    }
  };

  // 自动滚动效果
  useEffect(() => {
    if (autoScrollEnabled) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, autoScrollEnabled]);

  // API 配置状态 - 使用 useMemo 确保 apiConfig 变化时重新计算
  const hasApiConfig = useMemo(() => {
    const smartModel = apiConfig.models.find(m => m.id === apiConfig.smartModelId);
    const fastModel = apiConfig.models.find(m => m.id === apiConfig.fastModelId);
    return !!(smartModel?.credentialStored && fastModel?.credentialStored);
  }, [apiConfig]);

  // 防止 Hydration 错误
  // 导航处理函数
  /** Handles navigate; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleNavigate = (page: ViewType) => {
    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setShowSidebar(false);
    }

    // 只有直接调用模型的业务入口需要先完成 API 配置；
    // 首页、指南、题库、投递、记忆与任务运行仍可先查看已有数据。
    if (!requiresApiConfig(page)) {
      setActiveMainTab(page);
      return;
    }

    // 检查 API 配置
    const isConfigured = useInterviewStore.getState().isConfigured();
    if (!isConfigured) {
      toast.error("请先配置 API 参数", {
        description: "使用此功能需要先设置 API Key 和模型参数",
        action: {
          label: "去配置",
          onClick: () => setShowSettingsDialog(true),
        },
      });
      setShowSettingsDialog(true);
      return;
    }

    setActiveMainTab(page);
  };

  /** Selects a persisted interview and navigates to its real conversation workspace. */
  const handleOpenInterviewSession = async (sessionId: string) => {
    setHistoryDetailSessionId(null);
    setStoreShowAbilityProfile(false);
    setActiveMainTab('interview');
    await selectSession(sessionId);
  };

  /** Opens the unified session dialog on the requested view without changing the active conversation. */
  const handleOpenSessionDetail = (
    sessionId: string,
    initialTab: 'overview' | 'dialogue' | 'report' = 'overview',
  ) => {
    setHistoryDetailInitialTab(initialTab);
    setHistoryDetailSessionId(sessionId);
  };


  /** Keeps the imported interview snapshot and the model-facing company context synchronized while editing. */
  const handleInterviewJobContextChange = (snapshot: JobContextSnapshot | null) => {
    setJobContextSnapshot(snapshot);
    if (snapshot) {
      setCompanyInfo([
        snapshot.company_name && `公司：${snapshot.company_name}`,
        snapshot.job_title && `目标岗位：${snapshot.job_title}`,
        snapshot.company_size_text && `公司规模：${snapshot.company_size_text}`,
      ].filter(Boolean).join("\n"));
    }
  };

  /** Opens an editable专项面试 setup from persisted report recommendations without creating a run. */
  const handleStartTargetedInterview = (handoff: TargetedInterviewHandoff) => {
    useInterviewStore.getState().createNewSession();
    setJobContextSnapshot(null);
    setJobDescription(handoff.trainingGoal);
    setCompanyInfo('来源：面试复盘专项训练');
    setExperienceQuestions(handoff.questions);
    setStoreShowAbilityProfile(false);
    setHistoryDetailSessionId(null);
    setActiveMainTab('interview');
    toast.success(`已导入 ${handoff.questions.length} 道专项练习题，请确认后开始面试`);
  };

  /** Prefills the editable interview setup from one owner-scoped job snapshot without starting a run. */
  const handleUseJobInInterview = (snapshot: JobContextSnapshot) => {
    handleInterviewJobContextChange(snapshot);
    setJobDescription(snapshot.job_description);
    setCompanyInfo([
      snapshot.company_name && `公司：${snapshot.company_name}`,
      snapshot.job_title && `目标岗位：${snapshot.job_title}`,
      snapshot.company_size_text && `公司规模：${snapshot.company_size_text}`,
    ].filter(Boolean).join("\n"));
    setStoreShowAbilityProfile(false);
    setActiveMainTab('interview');
    toast.success('岗位上下文已导入模拟面试，可继续编辑');
  };

  /** Prefills the resume workspace and clears any selected historical result without starting model work. */
  const handleImportJobToResume = (snapshot: JobContextSnapshot) => {
    useInterviewStore.getState().clearResumeResult();
    setResumeJobContext(snapshot);
    setActiveMainTab('resume');
    toast.success('岗位上下文已导入简历工作台');
  };

  /** Opens the resume workspace and optionally restores one owner-scoped needs-input session. */
  const handleOpenResumeWorkspace = (generationSessionId?: string) => {
    setResumeGenerationSessionId(generationSessionId || null);
    setActiveMainTab('resume');
  };

  /** Opens one persisted job detail from an AgentRun business reference. */
  const handleOpenJobFromRun = (jobId: number) => {
    setInitialBossJobId(jobId);
    setActiveMainTab('boss');
  };

  /** Opens the persisted growth record inside the interview workspace. */
  const handleOpenGrowthRecord = () => {
    setHistoryDetailSessionId(null);
    setStoreShowAbilityProfile(true);
    setActiveMainTab('interview');
  };

  if (!isMounted) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-white">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  // 判断是否显示面试配置页
  // 逻辑：没有消息且没有当前会话，且不在流式传输中，且不在初始化中
  const showSetup = messages.length === 0 && !currentSession && !isStreaming && !isInitializing;

  // 根据 activeMainTab 渲染不同视图
  if (activeMainTab === 'landing') {
    return (
      <>
        <LandingPage onNavigate={handleNavigate} onOpenSettings={() => setShowSettingsDialog(true)} />
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'guide') {
    return (
      <>
        <GuidePage
          onBack={() => setActiveMainTab('landing')}
          onNavigate={handleNavigate}
          onOpenSettings={() => setShowSettingsDialog(true)}
        />
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'questionbank') {
    return (
      <>
        <WorkspaceShell
          sidebarOpen={showSidebar}
          onSidebarOpenChange={setShowSidebar}
          currentView="questionbank"
          onViewChange={handleNavigate}
          onOpenSettings={() => setShowSettingsDialog(true)}
          onGoHome={() => setActiveMainTab('landing')}
          icon={<BookOpenCheck className="h-4 w-4" />}
          title="题库与面经"
          description="管理题目、文件导入、面经采集和历史追问沉淀"
        >
          <QuestionBankPage
            embedded
            onOpenSession={(sessionId) => void handleOpenInterviewSession(sessionId)}
          />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'boss') {
    return (
      <>
        <WorkspaceShell
          sidebarOpen={showSidebar}
          onSidebarOpenChange={setShowSidebar}
          currentView="boss"
          onViewChange={handleNavigate}
          onOpenSettings={() => setShowSettingsDialog(true)}
          onGoHome={() => setActiveMainTab('landing')}
          icon={<Target className="h-4 w-4" />}
          title="岗位中心"
          description="岗位采集、匹配排序、资料维护与业务工作台交接"
        >
          <div className="h-full overflow-y-auto">
            <BossCenter initialJobId={initialBossJobId} onInitialJobConsumed={() => setInitialBossJobId(null)} onUseInInterview={handleUseJobInInterview} onImportToResume={handleImportJobToResume} />
          </div>
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'applications') {
    return (
      <>
        <WorkspaceShell
          sidebarOpen={showSidebar}
          onSidebarOpenChange={setShowSidebar}
          currentView="applications"
          onViewChange={handleNavigate}
          onOpenSettings={() => setShowSettingsDialog(true)}
          onGoHome={() => setActiveMainTab('landing')}
          icon={<BriefcaseBusiness className="h-4 w-4" />}
          title="投递管理"
          description="跟踪岗位状态、简历版本和面试事件流水"
        >
          <div className="h-full overflow-hidden p-5 sm:p-6">
            <ApplicationBoard onOpenDetail={setSelectedApplicationId} />
          </div>
          <ApplicationDetailDrawer
            applicationId={selectedApplicationId}
            onClose={() => setSelectedApplicationId(null)}
          />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'memory') {
    return (
      <>
        <WorkspaceShell
          sidebarOpen={showSidebar}
          onSidebarOpenChange={setShowSidebar}
          currentView="memory"
          onViewChange={handleNavigate}
          onOpenSettings={() => setShowSettingsDialog(true)}
          onGoHome={() => setActiveMainTab('landing')}
          icon={<Database className="h-4 w-4" />}
          title="长期记忆"
          description="查看、搜索和治理用于个性化的 mem0 记忆"
        >
          <MemoryCenter />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'runs') {
    return (
      <>
        <WorkspaceShell
          sidebarOpen={showSidebar}
          onSidebarOpenChange={setShowSidebar}
          currentView="runs"
          onViewChange={handleNavigate}
          onOpenSettings={() => setShowSettingsDialog(true)}
          onGoHome={() => setActiveMainTab('landing')}
          icon={<Activity className="h-4 w-4" />}
          title="任务运行"
          description="查看 AgentRun 阶段、实时事件、失败原因、取消与重试"
        >
          <RunCenter
            onOpenResumeWorkspace={handleOpenResumeWorkspace}
            onOpenSession={(sessionId) => void handleOpenInterviewSession(sessionId)}
            onOpenReport={(sessionId) => handleOpenSessionDetail(sessionId, 'report')}
            onOpenJob={handleOpenJobFromRun}
            onOpenGrowthRecord={handleOpenGrowthRecord}
          />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
        {historyDetailSessionId && (
          <InterviewHistoryDetailDialog
            key={`${historyDetailSessionId}-${historyDetailInitialTab}`}
            sessionId={historyDetailSessionId}
            initialTab={historyDetailInitialTab}
            onStartTargetedInterview={handleStartTargetedInterview}
            open={true}
            onOpenChange={(open) => {
              if (!open) setHistoryDetailSessionId(null);
            }}
          />
        )}
      </>
    );
  }

  if (activeMainTab === 'prompts') {
    return (
      <>
        <WorkspaceShell sidebarOpen={showSidebar} onSidebarOpenChange={setShowSidebar} currentView="prompts" onViewChange={handleNavigate} onOpenSettings={() => setShowSettingsDialog(true)} onGoHome={() => setActiveMainTab('landing')} icon={<Sparkles className="h-4 w-4" />} title="Prompt 管理" description="安全地查看、预览和发布 Langfuse Prompt 版本">
          <PromptManagementPage />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'evaluations') {
    return (
      <>
        <WorkspaceShell sidebarOpen={showSidebar} onSidebarOpenChange={setShowSidebar} currentView="evaluations" onViewChange={handleNavigate} onOpenSettings={() => setShowSettingsDialog(true)} onGoHome={() => setActiveMainTab('landing')} icon={<ShieldCheck className="h-4 w-4" />} title="Agent 评测中心" description="运行评测、观察质量、人工标注并校准 Agent 与 Judge">
          <EvaluationCenter />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  return (
    <WorkspaceShell
      sidebarOpen={showSidebar}
      onSidebarOpenChange={setShowSidebar}
      currentView={activeMainTab}
      onViewChange={handleNavigate}
      onOpenSettings={() => setShowSettingsDialog(true)}
      onGoHome={() => setActiveMainTab('landing')}
      onViewSessionDetail={(sessionId) => handleOpenSessionDetail(sessionId)}
      icon={activeMainTab === 'interview' ? <MessageCircle className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
      title={activeMainTab === 'interview' ? '模拟面试' : '简历工作台'}
      description={activeMainTab === 'interview' ? '文字与语音、多轮面试、能力报告和短板复盘' : '分析、优化、JD 匹配、素材组装、改写与生成'}
    >
        {/* 视图切换逻辑 */}
        {activeMainTab === "resume" ? (
          /* 简历工具视图 */
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain scroll-smooth [scrollbar-gutter:stable]">
            <div className="mx-auto min-h-full w-full max-w-[1600px] p-4 sm:p-6 lg:p-8">
              <ResumeTools
                apiConfig={hasApiConfig ? useInterviewStore.getState().getApiConfigForRequest() : null}
                resumeContent={resume?.content || ""}
                jobContext={resumeJobContext}
                generationSessionId={resumeGenerationSessionId}
                onGenerationSessionConsumed={() => setResumeGenerationSessionId(null)}
                onResumeChange={() => undefined}
                onOpenSession={(sessionId) => handleOpenSessionDetail(sessionId)}
              />
            </div>
          </div>
        ) : showAbilityProfile ? (
          // 能力画像视图
          <InterviewAbilityProfileView onBack={() => setStoreShowAbilityProfile(false)} />
        ) : showSetup ? (
          // 面试配置页 (New Session / Setup)
          <div className="flex-1 flex flex-col items-center justify-start sm:justify-center p-6 animate-in fade-in duration-500 relative bg-gray-50/30 overflow-y-auto min-h-0">
            {/* 背景装饰 */}
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-teal-50/50 via-white to-white pointer-events-none" />

            <div className="w-full max-w-3xl mx-auto relative z-10">
              <div className="mb-8 text-center">
                <h1 className="text-2xl font-bold text-gray-900 mb-2">开启新的模拟面试</h1>
                <p className="text-gray-500">配置您的简历和目标岗位，AI 面试官将为您量身定制面试问题</p>
              </div>

              <InterviewSetup
                resume={resume}
                onUploadResume={handleUploadResume}
                jobDescription={jobDescription}
                onJobDescriptionChange={setJobDescription}
                companyInfo={companyInfo}
                onCompanyInfoChange={setCompanyInfo}
                jobContextSnapshot={jobContextSnapshot}
                onJobContextSnapshotChange={handleInterviewJobContextChange}
                maxQuestions={maxQuestions}
                onMaxQuestionsChange={setMaxQuestions}
                interviewType={interviewType}
                onInterviewTypeChange={setInterviewType}
                questionBankCount={questionBankCount}
                onQuestionBankCountChange={setQuestionBankCount}
                experienceQuestionCount={experienceQuestions.length}
                isLoading={isLoading}
                hasApiConfig={hasApiConfig}
                onStartInterview={handleStartInterview}
                onConfigureApi={() => setShowSettingsDialog(true)}
                onOpenJobLibrary={() => setActiveMainTab('boss')}
                hasVoiceConfig={hasVoiceConfig}
              />
            </div>
          </div>
        ) : (
          // 聊天界面
          <InterviewArea>
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
              <InterviewProgressBar
                progress={interviewProgress}
                messageCount={messages.length}
                onSwitchToVoice={handleSwitchToVoice}
              />

              {/* 聊天区域 */}
              <InterviewChatArea
                messages={messages}
                isLoading={isLoading}
                isStreaming={isStreaming}
                initializationStage={initializationStage}
                executionPlan={executionPlan}
                viewportRef={scrollViewportRef}
                messagesEndRef={messagesEndRef}
                onScroll={handleScroll}
                onEditMessage={handleEditMessage}
                onRegenerateMessage={handleRegenerateMessage}
              >
                {/* 输入区域 */}
                <InterviewInputPanel
                  showScrollButton={showScrollButton}
                  onScrollToBottom={scrollToBottom}
                  onKeyDown={handleKeyDown}
                  input={input}
                  onInputChange={setInput}
                  isStreaming={isStreaming}
                  isListening={isListening}
                  isExpanded={isAnswerComposerExpanded}
                  isInterviewCompleted={isInterviewCompleted}
                  isLoadingHint={isLoadingHint}
                  canRequestHint={Boolean(threadId)}
                  hintContent={hintContent}
                  onExpandedChange={setIsAnswerComposerExpanded}
                  onRequestHint={handleGetHint}
                  onDismissHint={() => setHintContent(null)}
                  onToggleListening={toggleListening}
                  onSend={handleSend}
                  onStopStreaming={stopStreaming}
                >
                    {/* 开启下一轮面试按钮 - 仅在面试完成时显示 */}
                    {isInterviewCompleted &&
                      currentSession?.metadata.status === 'completed' && (
                        <InterviewNextRoundBanner
                          roundIndex={currentSession.metadata.round_index ?? 1}
                          sessionId={currentSession.session_id}
                          isLoading={isLoading}
                          isStreaming={isStreaming}
                          onOpenReport={() => currentSession && handleOpenSessionDetail(currentSession.session_id, 'report')}
                        />
                      )}
                </InterviewInputPanel>
              </InterviewChatArea>
            </div>
          </InterviewArea>
        )}

        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
        {historyDetailSessionId && (
          <InterviewHistoryDetailDialog
            key={historyDetailSessionId}
            sessionId={historyDetailSessionId}
            initialTab={historyDetailInitialTab}
            onStartTargetedInterview={handleStartTargetedInterview}
            open={true}
            onOpenChange={(open) => {
              if (!open) setHistoryDetailSessionId(null);
            }}
          />
        )}
    </WorkspaceShell>
  );
}

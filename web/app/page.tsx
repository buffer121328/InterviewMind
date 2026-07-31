"use client";

import { useState, useEffect, useRef, useMemo, useSyncExternalStore } from "react";
import { Activity, BookOpenCheck, BriefcaseBusiness, Database, Loader2, Award, Plus, MessageCircle, FileText, ArrowDown, Target, Sparkles, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AbilityProfileView } from "@/components/AbilityProfileView";
import { SettingsDialog } from "@/components/SettingsDialog";
import { SessionProfileDialog } from "@/components/SessionProfileDialog";
import { useInterviewStore } from "@/store/useInterviewStore";
import { useSpeechToText } from "@/hooks/useSpeechToText";
import { getUserId } from "@/hooks/useUserIdentity";
import { API_BASE_URL } from "@/lib/api/config";
import { parseSavedMainView, requiresApiConfig, type MainView } from "@/lib/navigation";
import { toast } from "sonner";
import { ResumeTools } from "@/components/ResumeTools";
import { LandingPage } from "@/components/LandingPage";
import { InterviewSetup } from "@/components/interview/InterviewSetup";
import { InterviewAnswerComposer } from "@/components/interview/InterviewAnswerComposer";
import { InterviewChatStream } from "@/components/interview/InterviewChatStream";
import { InterviewProgressBar } from "@/components/interview/InterviewProgressBar";
import { GuidePage } from "@/components/GuidePage";
import { InterviewArea } from "@/components/InterviewArea";
import { InterviewHistoryDetailDialog } from "@/components/InterviewHistoryDetailDialog";
import { ApplicationBoard } from "@/components/ApplicationBoard";
import { ApplicationDetailDrawer } from "@/components/ApplicationDetailDrawer";
import QuestionBankPage from "@/components/QuestionBankPage";
import { BossCenter } from "@/components/BossCenter";
import { MemoryCenter } from "@/components/MemoryCenter";
import { RunCenter } from "@/components/RunCenter";
import { PromptManagementPage } from "@/components/PromptManagementPage";
import { EvaluationCenter } from "@/components/evaluations/EvaluationCenter";
import { WorkspaceShell } from "@/components/WorkspaceShell";
import { QUESTION_COUNT_OPTIONS, defaultQuestionsForRoundIndex } from "@/lib/interview/questionDefaults";

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
  const [showSessionProfileDialog, setShowSessionProfileDialog] = useState(false);
  const [sessionProfileDefaultTab, setSessionProfileDefaultTab] = useState<'profile' | 'weakness'>('profile');
  const [activeMainTab, setActiveMainTab] = useState<ViewType>(getSavedMainTab);
  const [hintContent, setHintContent] = useState<string | null>(null);
  const [isLoadingHint, setIsLoadingHint] = useState(false);
  const [selectedApplicationId, setSelectedApplicationId] = useState<number | null>(null);
  const [historyDetailSessionId, setHistoryDetailSessionId] = useState<string | null>(null);
  const [nextRoundQuestionOverride, setNextRoundQuestionOverride] = useState<number | null>(null);

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
    setMaxQuestions,
    setInterviewType,
    setQuestionBankCount,
    uploadResume,
    startInterview,
    sendMessage,
    stopStreaming,
    rollbackChat,
    setShowAbilityProfile: setStoreShowAbilityProfile,
    apiError,
    clearApiError,
    setVoiceMode,
    getVoiceModel,
  } = useInterviewStore();

  // ===== 初始化 =====
  useEffect(() => {
    if (activeMainTab === 'interview') {
      void fetchSessions(undefined);
    }
  }, [activeMainTab, fetchSessions]);

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
    return !!getVoiceModel?.();
  }, [getVoiceModel]);

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
    if (!input.trim() || isStreaming) return;
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
    if (isStreaming) return;
    // 回退到该消息之前的状态
    await rollbackChat(index);
    // 直接发送编辑后的消息
    await sendMessage(newContent);
  };

  /** Handles regenerate message; updates local UI state first and delegates server mutations through the approved API boundary. */
  const handleRegenerateMessage = async (aiMessageIndex: number) => {
    if (isStreaming) return;

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
    return !!(smartModel?.apiKey && fastModel?.apiKey);
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

    setShowSessionProfileDialog(false);
    setActiveMainTab(page);
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
          <QuestionBankPage embedded onStartInterview={() => handleNavigate('interview')} />
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
          description="岗位采集、匹配排序、投递资产生成与人工确认"
        >
          <div className="h-full overflow-y-auto">
            <BossCenter />
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
            onOpenResumeWorkspace={() => setActiveMainTab('resume')}
            onOpenSession={setHistoryDetailSessionId}
          />
        </WorkspaceShell>
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
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
      onViewSessionDetail={setHistoryDetailSessionId}
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
                onResumeChange={() => undefined}
                onOpenSession={setHistoryDetailSessionId}
              />
            </div>
          </div>
        ) : showAbilityProfile ? (
          // 能力画像视图
          <div className="flex-1 flex flex-col min-h-0 relative overflow-y-auto">
            <div className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
              <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-4">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setStoreShowAbilityProfile(false)}
                  className="gap-2"
                >
                  <Award className="w-4 h-4" />
                  返回对话
                </Button>
                <div className="flex-1">
                  <h2 className="text-lg font-semibold text-gray-900">综合能力画像</h2>
                  <p className="text-xs text-gray-500">基于最近5次面试的综合分析</p>
                </div>
              </div>
            </div>
            <AbilityProfileView />
          </div>
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
              <div className="flex-1 overflow-hidden relative flex flex-col">
                <InterviewChatStream
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
                />



                {/* 输入区域 */}
                <div className="relative w-full bg-white border-t border-gray-100 px-6 py-4 z-20">
                  <div className="max-w-3xl mx-auto relative">
                    {/* 滚动到底部按钮 - 移动到输入框上方，确保不被遮挡 */}
                    {showScrollButton && (
                      <div className="absolute -top-12 left-0 right-0 flex justify-center z-20 pointer-events-none">
                        <Button
                          size="sm"
                          variant="secondary"
                          className="rounded-full shadow-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 gap-2 pointer-events-auto animate-in fade-in zoom-in duration-300"
                          onClick={scrollToBottom}
                        >
                          <ArrowDown className="w-4 h-4" />
                          <span>回到底部</span>
                        </Button>
                      </div>
                    )}
                    {/* 开启下一轮面试按钮 - 仅在面试完成时显示 */}
                    {interviewProgress &&
                      interviewProgress.current >= interviewProgress.total &&
                      currentSession?.metadata.status === 'completed' && (
                        <div className="mb-4 p-4 rounded-xl bg-gradient-to-r from-teal-50 to-amber-50 border border-teal-200">
                          <div className="flex items-center justify-between gap-4">
                            <div className="flex-1">
                              {/* 判断是否为最后一轮（第3轮） */}
                              {(currentSession.metadata.round_index ?? 1) >= 3 ? (
                                <>
                                  <h4 className="font-semibold text-gray-900 mb-1">🎉 所有面试已结束！</h4>
                                  <p className="text-sm text-gray-600">
                                    恭喜您完成了全部 3 轮面试，点击查看本轮能力画像
                                  </p>
                                </>
                              ) : (
                                <>
                                  <h4 className="font-semibold text-gray-900 mb-1">面试已完成！</h4>
                                  <p className="text-sm text-gray-600">
                                    继续进行下一轮面试，深入考察您的专业能力
                                  </p>
                                </>
                              )}
                            </div>
                            <div className="flex items-center gap-3">
                              <Button
                                variant="outline"
                                onClick={() => {
                                  setSessionProfileDefaultTab('profile');
                                  setShowSessionProfileDialog(true);
                                }}
                                className="gap-2"
                              >
                                <Award className="w-4 h-4 text-pink-500" />
                                本轮能力画像
                              </Button>
                              <Button
                                variant="outline"
                                onClick={() => {
                                  setSessionProfileDefaultTab('weakness');
                                  setShowSessionProfileDialog(true);
                                }}
                                className="gap-2"
                              >
                                <Target className="w-4 h-4 text-teal-500" />
                                短板地图
                              </Button>
                              {/* 仅在非最后一轮时显示下一轮选项 */}
                              {(currentSession.metadata.round_index ?? 1) < 3 && (
                                <div className="flex items-center gap-2 bg-white p-1 rounded-lg border border-teal-100 shadow-sm">
                                  <select
                                    id="next-round-questions"
                                    className="h-8 px-2 rounded-md bg-transparent text-sm focus:outline-none text-teal-900"
                                    defaultValue={defaultQuestionsForRoundIndex((currentSession.metadata.round_index ?? 1) + 1)}
                                    onChange={(e) => {
                                      // 更新全局状态中的 maxQuestions
                                      setNextRoundQuestionOverride(parseInt(e.target.value));
                                      useInterviewStore.setState({ maxQuestions: parseInt(e.target.value) });
                                    }}
                                  >
                                    {QUESTION_COUNT_OPTIONS.map((n) => (
                                      <option key={n} value={n}>{n} 道题</option>
                                    ))}
                                  </select>
                                  <Button
                                    onClick={async () => {
                                      try {
                                        // 从 store 获取最新的题目数量
                                        const nextRoundQuestions = nextRoundQuestionOverride ?? defaultQuestionsForRoundIndex((currentSession.metadata.round_index ?? 1) + 1);

                                        // 设置加载状态，清空消息以显示加载动画
                                        useInterviewStore.setState({
                                          isLoading: true,
                                          isStreaming: true,
                                          messages: [],
                                          interviewProgress: { current: 0, total: nextRoundQuestions }
                                        });

                                        // 1. 创建下一轮会话
                                        const response = await fetch(`${API_BASE_URL}/api/sessions/${currentSession.session_id}/next-round`, {
                                          method: 'POST',
                                          headers: {
                                            'Content-Type': 'application/json',
                                            'X-User-ID': getUserId()
                                          },
                                          body: JSON.stringify({
                                            max_questions: nextRoundQuestions,
                                          })
                                        });

                                        if (!response.ok) {
                                          const error = await response.json();
                                          throw new Error(error.message || '创建下一轮失败');
                                        }

                                        const data = await response.json();
                                        const newSessionId = data.session.session_id;

                                        // 2. 刷新会话列表并选择新会话
                                        await fetchSessions(undefined);
                                        await selectSession(newSessionId);

                                        // 3. 直接调用 /chat/start，后端会从数据库加载继承的简历/JD
                                        const apiConfig = useInterviewStore.getState().getApiConfigForRequest();
                                        if (!apiConfig) {
                                          throw new Error('请先配置 API');
                                        }

                                        const startResponse = await fetch(`${API_BASE_URL}/api/chat/start`, {
                                          method: 'POST',
                                          headers: {
                                            'Content-Type': 'application/json',
                                            'X-User-ID': getUserId()
                                          },
                                          body: JSON.stringify({
                                            thread_id: newSessionId,
                                            mode: 'mock',
                                            max_questions: nextRoundQuestions,
                                            api_config: apiConfig,
                                          })
                                        });

                                        if (!startResponse.ok) {
                                          throw new Error('启动面试失败');
                                        }

                                        // 4. 处理流式响应
                                        const reader = startResponse.body?.getReader();
                                        if (reader) {
                                          const decoder = new TextDecoder();
                                          let buffer = '';

                                          while (true) {
                                            const { done, value } = await reader.read();
                                            if (done) {
                                              if (buffer.trim()) {
                                                try {
                                                  const jsonData = JSON.parse(buffer);
                                                  if (jsonData.first_question) {
                                                    useInterviewStore.setState({
                                                      messages: [{
                                                        role: 'assistant',
                                                        content: jsonData.first_question,
                                                        timestamp: new Date().toISOString(),
                                                      }],
                                                      isLoading: false,
                                                      isStreaming: false,
                                                    });
                                                  }
                                                } catch { }
                                              }
                                              break;
                                            }
                                            buffer += decoder.decode(value, { stream: true });
                                          }
                                        }

                                      } catch (error) {
                                        console.error('创建下一轮失败:', error);
                                        toast.error((error as Error).message || '创建下一轮失败');
                                        useInterviewStore.setState({ isLoading: false, isStreaming: false });
                                      }
                                    }}
                                    disabled={isLoading || isStreaming}
                                    className="bg-teal-600 hover:bg-teal-700 text-white gap-2 disabled:opacity-50 h-8 px-3 text-xs font-bold"
                                  >
                                    {isLoading ? (
                                      <Loader2 className="w-3 h-3 animate-spin" />
                                    ) : (
                                      <Plus className="w-3 h-3" />
                                    )}
                                    {isLoading ? '准备中...' : '开启下一轮'}
                                  </Button>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                    <InterviewAnswerComposer
                      input={input}
                      onInputChange={setInput}
                      onKeyDown={handleKeyDown}
                      isStreaming={isStreaming}
                      isListening={isListening}
                      isInterviewCompleted={Boolean(interviewProgress && interviewProgress.current >= interviewProgress.total)}
                      isLoadingHint={isLoadingHint}
                      canRequestHint={Boolean(threadId)}
                      hintContent={hintContent}
                      onRequestHint={handleGetHint}
                      onDismissHint={() => setHintContent(null)}
                      onToggleListening={toggleListening}
                      onSend={handleSend}
                      onStopStreaming={stopStreaming}
                    />
                  </div>
                </div>
              </div>
            </div>
          </InterviewArea>
        )}

        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
        {historyDetailSessionId && (
          <InterviewHistoryDetailDialog
            key={historyDetailSessionId}
            sessionId={historyDetailSessionId}
            open={true}
            onOpenChange={(open) => {
              if (!open) setHistoryDetailSessionId(null);
            }}
          />
        )}
        {showSessionProfileDialog && (
          <SessionProfileDialog
            open={showSessionProfileDialog}
            onOpenChange={setShowSessionProfileDialog}
            sessionId={currentSession?.session_id || ""}
            defaultTab={sessionProfileDefaultTab}
          />
        )}
    </WorkspaceShell>
  );
}

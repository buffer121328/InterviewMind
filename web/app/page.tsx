"use client";

import { useState, useEffect, useRef, useMemo, useSyncExternalStore } from "react";
import { PanelLeft, Bot, Loader2, Award, Plus, MessageCircle, FileText, ArrowDown, Square, Lightbulb, X, Mic, Target, Briefcase } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatMessage } from "@/components/ChatMessage";
import { SessionSidebar } from "@/components/SessionSidebar";
import { AbilityProfileView } from "@/components/AbilityProfileView";
import { SettingsDialog } from "@/components/SettingsDialog";
import { SessionProfileDialog } from "@/components/SessionProfileDialog";
import { useInterviewStore } from "@/store/useInterviewStore";
import { useSpeechToText } from "@/hooks/useSpeechToText";
import { getUserId } from "@/hooks/useUserIdentity";
import { API_BASE_URL } from "@/lib/api/config";
import { cn } from "@/lib/utils";
import { parseSavedMainView, requiresApiConfig, type MainView } from "@/lib/navigation";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { ResumeTools } from "@/components/ResumeTools";
import { LandingPage } from "@/components/LandingPage";
import { InterviewSetup } from "@/components/interview/InterviewSetup";
import { GuidePage } from "@/components/GuidePage";
import { InterviewArea } from "@/components/InterviewArea";
import { PreparingInterview } from "@/components/interview/PreparingInterview";
import { ExecutionPlanPanel } from "@/components/interview/ExecutionPlanPanel";
import { InterviewHistoryDetailDialog } from "@/components/InterviewHistoryDetailDialog";
import { ApplicationBoard } from "@/components/ApplicationBoard";
import { ApplicationDetailDrawer } from "@/components/ApplicationDetailDrawer";
import QuestionBankPage from "@/components/QuestionBankPage";
import { BossCenter } from "@/components/BossCenter";
import { QUESTION_COUNT_OPTIONS, defaultQuestionsForRoundIndex } from "@/lib/interview/questionDefaults";

// 定义视图类型，包含 'landing'
type ViewType = MainView;

const subscribeToHydration = () => () => {};

function getSavedMainTab(): ViewType {
  if (typeof window === "undefined") return "landing";

  return parseSavedMainView(localStorage.getItem("activeMainTab"));
}

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
    fetchSessions(undefined);
  }, [fetchSessions]);

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
  const handleUploadResume = async (file: File) => {
    await uploadResume(file);
  };

  // 检查是否配置了语音模型
  const hasVoiceConfig = useMemo(() => {
    return !!getVoiceModel?.();
  }, [getVoiceModel]);

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

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;
    const content = input;
    setInput("");
    await sendMessage(content);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ===== 消息编辑和重新生成 =====
  const handleEditMessage = async (index: number, newContent: string) => {
    if (isStreaming) return;
    // 回退到该消息之前的状态
    await rollbackChat(index);
    // 直接发送编辑后的消息
    await sendMessage(newContent);
  };

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

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    setShowScrollButton(false);
    setAutoScrollEnabled(true);
  };

  // 获取回答提示
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
  const handleNavigate = (page: ViewType) => {
    // 首页/指南/投递追踪/题库属于公共主视图，不需要 API 配置。
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
        <LandingPage onNavigate={(page) => handleNavigate(page as ViewType)} />
        <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
      </>
    );
  }

  if (activeMainTab === 'guide') {
    return <GuidePage onBack={() => setActiveMainTab('landing')} />;
  }

  if (activeMainTab === 'questionbank') {
    return (
      <QuestionBankPage
        onBack={() => setActiveMainTab('landing')}
        onStartInterview={() => setActiveMainTab('interview')}
      />
    );
  }

  // BOSS 半自动化视图
  if (activeMainTab === 'boss') {
    return (
      <div className="flex h-[100dvh] w-full overflow-hidden bg-white text-[#1d1d1f] font-sans antialiased">
        <SessionSidebar
          isOpen={showSidebar}
          onClose={() => setShowSidebar(false)}
          onOpenSettings={() => setShowSettingsDialog(true)}
          currentView="boss"
          onViewChange={(view) => setActiveMainTab(view)}
        />
        <main className="flex-1 flex flex-col min-h-0 relative bg-white overflow-hidden">
          <div className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-20">
            <div className="mx-auto px-6 py-2 flex items-center justify-between">
              <div className="flex items-center gap-4">
                {!showSidebar && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setShowSidebar(true)}
                    className="hover:bg-gray-100 text-gray-500"
                  >
                    <PanelLeft className="w-5 h-5" />
                  </Button>
                )}
                <div className="flex items-center gap-2 font-medium text-gray-700">
                  <Briefcase size={18} className="text-orange-600" />
                  <span>BOSS 半自动化</span>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setActiveMainTab('landing')} className="text-gray-500 text-xs">
                返回首页
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            <BossCenter />
          </div>
          <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
        </main>
      </div>
    );
  }

  // 投递追踪视图
  if (activeMainTab === 'applications') {
    return (
      <div className="flex h-[100dvh] w-full overflow-hidden bg-white text-[#1d1d1f] font-sans antialiased">
        <SessionSidebar
          isOpen={showSidebar}
          onClose={() => setShowSidebar(false)}
          onOpenSettings={() => setShowSettingsDialog(true)}
          currentView="applications"
          onViewChange={(view) => setActiveMainTab(view)}
        />
        <main className="flex-1 flex flex-col min-h-0 relative bg-white overflow-hidden">
          <div className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-20">
            <div className="mx-auto px-6 py-2 flex items-center justify-between">
              <div className="flex items-center gap-4">
                {!showSidebar && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setShowSidebar(true)}
                    className="hover:bg-gray-100 text-gray-500"
                  >
                    <PanelLeft className="w-5 h-5" />
                  </Button>
                )}
                <div className="flex items-center gap-2 font-medium text-gray-700">
                  <Briefcase size={18} className="text-orange-600" />
                  <span>投递追踪</span>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setActiveMainTab('landing')} className="text-gray-500 text-xs">
                返回首页
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            <ApplicationBoard onOpenDetail={(id) => setSelectedApplicationId(id)} />
          </div>
          <ApplicationDetailDrawer
            applicationId={selectedApplicationId}
            onClose={() => setSelectedApplicationId(null)}
          />
          <SettingsDialog open={showSettingsDialog} onOpenChange={setShowSettingsDialog} />
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-white text-[#1d1d1f] font-sans antialiased">

      {/* 侧边栏 */}
      <SessionSidebar
        isOpen={showSidebar}
        onClose={() => setShowSidebar(false)}
        onOpenSettings={() => setShowSettingsDialog(true)}
        currentView={activeMainTab as "interview" | "resume" | "applications"}
        onViewChange={(view) => setActiveMainTab(view)}
        onViewSessionDetail={setHistoryDetailSessionId}
      />

      {/* 主内容区域 */}
      <main className="flex-1 flex flex-col min-h-0 relative bg-white overflow-hidden">

        {/* 顶部导航栏 */}
        <div className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-20">
          <div className="mx-auto px-6 py-2 flex items-center justify-between">
            <div className="flex items-center gap-4">
              {!showSidebar && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setShowSidebar(true)}
                  className="hover:bg-gray-100 text-gray-500"
                >
                  <PanelLeft className="w-5 h-5" />
                </Button>
              )}

              {/* 标题 */}
              <div className="flex items-center gap-2 font-medium text-gray-700">
                {activeMainTab === "interview" ? (
                  <>
                    <MessageCircle size={18} className="text-orange-600" />
                    <span>模拟面试</span>
                  </>
                ) : (
                  <>
                    <FileText size={18} className="text-orange-600" />
                    <span>简历工具</span>
                  </>
                )}
              </div>
            </div>
            {/* Back to Home Button? Optional, maybe user can just use sidebar to navigate types, but Landing is outside sidebar */}
            <Button variant="ghost" size="sm" onClick={() => setActiveMainTab('landing')} className="text-gray-500 text-xs">
              返回首页
            </Button>
          </div>
        </div>

        {/* 视图切换逻辑 */}
        {activeMainTab === "resume" ? (
          /* 简历工具视图 */
          <div className="flex-1 overflow-y-auto p-6 min-h-0">
            <div className="max-w-6xl mx-auto h-full">
              <ResumeTools
                apiConfig={hasApiConfig ? useInterviewStore.getState().getApiConfigForRequest() : null}
                resumeContent={resume?.content || ""}
                onResumeChange={() => undefined}
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
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-orange-50/50 via-white to-white pointer-events-none" />

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
              {/* 面试进度条 - 仅在有消息时显示 */}
              {interviewProgress && interviewProgress.total > 0 && messages.length > 0 && (
                <div className="border-b border-gray-100 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
                  <div className="max-w-3xl mx-auto px-6 py-3">
                    <div className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1.5">
                          <div className={cn(
                            "w-2 h-2 rounded-full",
                            interviewProgress.current >= interviewProgress.total ? "bg-gray-400" : "bg-orange-500 animate-pulse"
                          )}></div>
                          <span className="font-medium text-gray-700">
                            {interviewProgress.current >= interviewProgress.total ? "面试已完成" : "面试进行中"}
                          </span>
                        </div>
                        <span className="text-gray-300">|</span>
                        <span className="text-gray-500">
                          问题 {Math.min(interviewProgress.current + 1, interviewProgress.total)} / {interviewProgress.total}
                        </span>
                      </div>

                      {/* 切换语音面试按钮 */}
                      {interviewProgress.current < interviewProgress.total && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-purple-700 hover:text-purple-800 hover:bg-purple-50 gap-1.5 h-7 px-2"
                          onClick={handleSwitchToVoice}
                        >
                          <Mic className="w-3.5 h-3.5" />
                          <span>切换语音面试</span>
                        </Button>
                      )}
                    </div>
                    {/* 进度条 */}
                    <div className="mt-3 h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-orange-500 rounded-full transition-all duration-500 ease-out"
                        style={{ width: `${(interviewProgress.current / interviewProgress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* 聊天区域 */}
              <div className="flex-1 overflow-hidden relative flex flex-col">
                <ScrollArea className="flex-1 px-4 overflow-hidden" viewportRef={scrollViewportRef} onScroll={handleScroll}>
                  <div className="max-w-3xl mx-auto pt-6 pb-2 space-y-6">
                    {/* 初始加载状态：当正在加载或流式传输且没有消息时显示 */}
                    {(isLoading || isStreaming) && messages.length === 0 && (
                      <PreparingInterview stage={initializationStage} plan={executionPlan} />
                    )}

                    {messages.map((msg, index) => (
                      <ChatMessage
                        key={index}
                        role={msg.role}
                        content={msg.content}
                        timestamp={msg.timestamp}
                        onEdit={msg.role === 'user' ? (content) => handleEditMessage(index, content) : undefined}
                        onRegenerate={msg.role === 'assistant' && index !== 0 ? () => handleRegenerateMessage(index) : undefined}
                      />
                    ))}

                    {/* 后续对话的思考状态：仅在流式传输中且最后一条消息是用户消息时显示 */}
                    {isStreaming && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
                      <div className="space-y-3 px-4">
                        <div className="flex items-center gap-2 text-gray-400 text-sm animate-pulse">
                          <Bot className="w-4 h-4" />
                          <span>面试官正在思考...</span>
                        </div>
                        <ExecutionPlanPanel steps={executionPlan} />
                      </div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                </ScrollArea>



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
                        <div className="mb-4 p-4 rounded-xl bg-gradient-to-r from-orange-50 to-amber-50 border border-orange-200">
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
                                <Target className="w-4 h-4 text-orange-500" />
                                短板地图
                              </Button>
                              {/* 仅在非最后一轮时显示下一轮选项 */}
                              {(currentSession.metadata.round_index ?? 1) < 3 && (
                                <div className="flex items-center gap-2 bg-white p-1 rounded-lg border border-orange-100 shadow-sm">
                                  <select
                                    id="next-round-questions"
                                    className="h-8 px-2 rounded-md bg-transparent text-sm focus:outline-none text-orange-900"
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
                                    className="bg-orange-600 hover:bg-orange-700 text-white gap-2 disabled:opacity-50 h-8 px-3 text-xs font-bold"
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

                    {/* 回答提示显示区域 */}
                    {hintContent && (
                      <div className="mb-4 p-4 rounded-xl bg-gradient-to-r from-amber-50 to-yellow-50 border border-amber-200 animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="flex items-start gap-3">
                          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center">
                            <Lightbulb className="w-4 h-4 text-amber-600" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between mb-1">
                              <h4 className="font-medium text-amber-800 text-sm">回答提示</h4>
                              <button
                                onClick={() => setHintContent(null)}
                                className="p-1 hover:bg-amber-100 rounded-full transition-colors"
                              >
                                <X className="w-4 h-4 text-amber-600" />
                              </button>
                            </div>
                            <p className="text-sm text-amber-700 leading-relaxed whitespace-pre-wrap">
                              {hintContent}
                            </p>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* 判断面试是否已完成 */}
                    {(() => {
                      const isInterviewCompleted = !!(interviewProgress && interviewProgress.current >= interviewProgress.total);
                      return (
                        <div className="flex gap-2 items-end">
                          <div className="flex-1 relative flex">
                            {/* 输入框 Textarea */}
                            <textarea
                              value={input}
                              onChange={(e) => setInput(e.target.value)}
                              onKeyDown={handleKeyDown}
                              placeholder={isInterviewCompleted ? "本轮面试已结束" : "输入您的回答..."}
                              disabled={isStreaming || isInterviewCompleted}
                              className={cn(
                                "w-full resize-none rounded-2xl border border-gray-200 py-3 pl-4 pr-24 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-50 min-h-[120px] max-h-[200px]",
                                isInterviewCompleted && "bg-gray-50 cursor-not-allowed opacity-60"
                              )}
                              rows={4}
                            />
                            {/* 获取提示按钮 */}
                            <button
                              onClick={handleGetHint}
                              disabled={isInterviewCompleted || isLoadingHint || !threadId}
                              title="获取回答提示"
                              className={cn(
                                "absolute right-12 bottom-3 p-2 rounded-full transition-colors",
                                isLoadingHint ? "bg-amber-100 text-amber-500" : "hover:bg-amber-50 text-amber-400 hover:text-amber-500",
                                (isInterviewCompleted || !threadId) && "opacity-50 cursor-not-allowed"
                              )}
                            >
                              {isLoadingHint ? (
                                <Loader2 className="w-5 h-5 animate-spin" />
                              ) : (
                                <Lightbulb className="w-5 h-5" />
                              )}
                            </button>
                            {/* 语音按钮 */}
                            <button
                              onClick={toggleListening}
                              disabled={isInterviewCompleted}
                              className={cn(
                                "absolute right-3 bottom-3 p-2 rounded-full transition-colors",
                                isListening ? "bg-red-100 text-red-500 animate-pulse" : "hover:bg-gray-100 text-gray-400",
                                isInterviewCompleted && "opacity-50 cursor-not-allowed"
                              )}
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" x2="12" y1="19" y2="22" /></svg>
                            </button>
                          </div>

                          <Button
                            onClick={isStreaming ? stopStreaming : handleSend}
                            disabled={!isStreaming && (!input.trim() || isInterviewCompleted)}
                            className={cn(
                              "h-[52px] w-[52px] rounded-2xl transition-all",
                              isStreaming
                                ? "bg-red-500 hover:bg-red-600 shadow-lg shadow-red-200"
                                : input.trim() && !isInterviewCompleted
                                  ? "bg-orange-600 hover:bg-orange-700 shadow-lg shadow-orange-200"
                                  : "bg-gray-100 text-gray-400"
                            )}
                          >
                            {isStreaming ? (
                              <Square className="w-5 h-5" fill="currentColor" />
                            ) : (
                              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>
                            )}
                          </Button>
                        </div>
                      );
                    })()}
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
      </main>
    </div>
  );
}

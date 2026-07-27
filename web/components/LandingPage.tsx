"use client";

import Image from "next/image";
import {
  ArrowRight,
  BookOpenCheck,
  Bot,
  BrainCircuit,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  ClipboardList,
  Database,
  FileSearch,
  FileText,
  Gauge,
  KeyRound,
  Layers3,
  Mic2,
  Settings2,
  ShieldCheck,
  Sparkles,
  Target,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { MainView } from "@/lib/navigation";
import { PRODUCT_DESCRIPTION, PRODUCT_NAME } from "@/lib/product";

interface LandingPageProps {
  onNavigate: (page: MainView) => void;
  onOpenSettings: () => void;
}

const modules: Array<{
  view: MainView;
  title: string;
  description: string;
  icon: typeof Bot;
  eyebrow: string;
  accent: string;
}> = [
  {
    view: "interview",
    title: "模拟面试",
    description: "文字与语音、多轮面试、实时执行计划、回答提示与能力复盘。",
    icon: Mic2,
    eyebrow: "Interview",
    accent: "bg-teal-50 text-teal-700",
  },
  {
    view: "resume",
    title: "简历工作台",
    description: "竞争力分析、JD 定向优化、素材组装、项目改写与简历生成。",
    icon: FileText,
    eyebrow: "Resume",
    accent: "bg-cyan-50 text-cyan-700",
  },
  {
    view: "questionbank",
    title: "题库与面经",
    description: "手动维护、文件导入、面经采集、历史追问沉淀并带入面试。",
    icon: BookOpenCheck,
    eyebrow: "Knowledge",
    accent: "bg-indigo-50 text-indigo-700",
  },
  {
    view: "boss",
    title: "岗位中心",
    description: "采集 JD、匹配排序、生成投递资产，并保留预览与确认边界。",
    icon: Target,
    eyebrow: "Jobs",
    accent: "bg-amber-50 text-amber-700",
  },
  {
    view: "applications",
    title: "投递管理",
    description: "按状态管理岗位、简历版本和面试事件，形成完整求职流水。",
    icon: BriefcaseBusiness,
    eyebrow: "Pipeline",
    accent: "bg-emerald-50 text-emerald-700",
  },
  {
    view: "memory",
    title: "长期记忆",
    description: "查看、搜索和治理 mem0 记忆，掌控被用于个性化建议的内容。",
    icon: Database,
    eyebrow: "Memory",
    accent: "bg-violet-50 text-violet-700",
  },
  {
    view: "runs",
    title: "任务运行",
    description: "查看 AgentRun 阶段、版本和失败原因，支持取消与受控重试。",
    icon: Workflow,
    eyebrow: "Runtime",
    accent: "bg-slate-100 text-slate-700",
  },
];

const workflow = [
  { title: "建立候选人上下文", text: "导入简历、目标 JD、题库与历史面试。", icon: Layers3 },
  { title: "让 Agent 执行任务", text: "按模型通道完成分析、检索、生成和复盘。", icon: BrainCircuit },
  { title: "审核后进入求职流水", text: "查看结果、保留版本，并由你确认外部动作。", icon: ShieldCheck },
];

/** Renders the landing page UI and coordinates its typed props, local state, and approved backend interactions. */
export function LandingPage({ onNavigate, onOpenSettings }: LandingPageProps) {
  return (
    <div className="min-h-screen bg-[#f7faf9] text-slate-950">
      <header className="sticky top-0 z-50 border-b border-slate-200/80 bg-[#f7faf9]/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8">
          <button className="flex items-center gap-3 text-left" onClick={() => onNavigate("landing")}>
            <Image
              src="/logo.png"
              alt=""
              width={36}
              height={36}
              className="rounded-xl shadow-sm ring-1 ring-teal-950/10"
              priority
            />
            <div>
              <div className="text-sm font-semibold tracking-tight text-slate-950 sm:text-base">{PRODUCT_NAME}</div>
              <div className="hidden text-[10px] uppercase tracking-[0.22em] text-teal-700 sm:block">Career agent workspace</div>
            </div>
          </button>

          <nav className="hidden items-center gap-1 lg:flex">
            <button className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-white hover:text-slate-950" onClick={() => onNavigate("interview")}>面试</button>
            <button className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-white hover:text-slate-950" onClick={() => onNavigate("resume")}>简历</button>
            <button className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-white hover:text-slate-950" onClick={() => onNavigate("questionbank")}>题库</button>
            <button className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-white hover:text-slate-950" onClick={() => onNavigate("applications")}>投递</button>
            <button className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-white hover:text-slate-950" onClick={() => onNavigate("guide")}>使用指南</button>
          </nav>

          <Button variant="outline" className="border-slate-300 bg-white" onClick={onOpenSettings} aria-label="模型设置">
            <Settings2 className="h-4 w-4" />
            <span className="hidden sm:inline">模型设置</span>
          </Button>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-b border-slate-200/80">
          <div className="workspace-grid absolute inset-0 opacity-80" />
          <div className="absolute left-1/2 top-10 h-[34rem] w-[34rem] -translate-x-1/2 rounded-full bg-teal-200/25 blur-3xl" />
          <div className="relative mx-auto grid max-w-7xl items-center gap-14 px-5 py-20 sm:px-8 lg:grid-cols-[1.08fr_0.92fr] lg:py-28">
            <div>
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-teal-200 bg-white/85 px-3 py-1.5 text-xs font-medium text-teal-800 shadow-sm">
                <Sparkles className="h-3.5 w-3.5" />
                从求职准备到投递复盘的完整 Agent 工作台
              </div>
              <h1 className="max-w-3xl text-4xl font-semibold leading-[1.08] tracking-[-0.045em] text-slate-950 sm:text-6xl">
                把每一次准备，
                <span className="block text-teal-700">沉淀成下一次面试的胜率。</span>
              </h1>
              <p className="mt-6 max-w-2xl text-base leading-8 text-slate-600 sm:text-lg">
                {PRODUCT_DESCRIPTION}。不是一次性问答，而是一套能够持续恢复、检索、生成、评估与追踪的个人求职系统。
              </p>

              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                <Button size="lg" className="h-12 bg-teal-700 px-6 text-white shadow-lg shadow-teal-900/10 hover:bg-teal-800" onClick={() => onNavigate("interview")}>
                  开始模拟面试 <ArrowRight className="h-4 w-4" />
                </Button>
                <Button size="lg" variant="outline" className="h-12 border-slate-300 bg-white/80 px-6" onClick={() => onNavigate("resume")}>
                  打开简历工作台
                </Button>
              </div>

              <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-600">
                {["模型通道由你配置", "外部投递必须确认", "长任务可恢复与重试"].map((item) => (
                  <span key={item} className="inline-flex items-center gap-1.5">
                    <Check className="h-3.5 w-3.5 text-teal-700" />
                    {item}
                  </span>
                ))}
              </div>
            </div>

            <div className="relative mx-auto w-full max-w-xl">
              <div className="overflow-hidden rounded-2xl border border-teal-900 bg-[#102724] text-white shadow-[0_28px_70px_-34px_rgba(15,23,42,0.7)]">
                <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
                  <div>
                    <div className="text-sm font-medium">当前求职工作流</div>
                    <div className="mt-1 text-xs text-teal-100/65">AgentRun · 可恢复执行</div>
                  </div>
                  <div className="flex items-center gap-2 rounded-full bg-emerald-400/10 px-2.5 py-1 text-xs text-emerald-200">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                    运行正常
                  </div>
                </div>
                <div className="space-y-4 p-5">
                  {[
                    { icon: FileSearch, title: "JD 与简历匹配", state: "已完成", color: "text-emerald-300" },
                    { icon: Bot, title: "生成定向面试计划", state: "执行中", color: "text-teal-200" },
                    { icon: ClipboardList, title: "能力报告与补强题库", state: "等待中", color: "text-slate-400" },
                  ].map((item, index) => (
                    <div key={item.title} className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/[0.045] p-4">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10">
                        <item.icon className="h-4 w-4 text-teal-100" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{item.title}</div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
                          <div className="h-full rounded-full bg-teal-300" style={{ width: `${index === 0 ? 100 : index === 1 ? 62 : 8}%` }} />
                        </div>
                      </div>
                      <span className={`text-xs ${item.color}`}>{item.state}</span>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-3 border-t border-white/10 bg-black/10">
                  {[
                    ["7", "正式模块"],
                    ["SSE", "实时事件"],
                    ["Human", "外部确认"],
                  ].map(([value, label]) => (
                    <div key={label} className="border-r border-white/10 px-4 py-4 last:border-r-0">
                      <div className="text-sm font-semibold text-teal-200">{value}</div>
                      <div className="mt-1 text-[10px] text-slate-400">{label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
          <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">求职闭环</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">从准备到投递，把每一步真正串起来</h2>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600">简历、JD、题库、面试记录和任务进度在同一处持续流转；你随时知道下一步做什么，也始终保留对外投递的最终决定权。</p>
            </div>
            <Button variant="ghost" className="justify-start text-teal-700" onClick={() => onNavigate("guide")}>
              查看完整使用指南 <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {modules.map((module, index) => (
              <button
                key={module.view}
                onClick={() => onNavigate(module.view)}
                className={`group surface-panel p-5 text-left transition duration-200 hover:-translate-y-0.5 hover:border-teal-300 hover:shadow-lg ${index === modules.length - 1 ? "lg:col-span-3" : ""}`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${module.accent}`}>
                    <module.icon className="h-5 w-5" />
                  </div>
                  <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">{module.eyebrow}</span>
                </div>
                <h3 className="mt-5 text-base font-semibold text-slate-950">{module.title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">{module.description}</p>
                <span className="mt-5 inline-flex items-center gap-1 text-xs font-medium text-teal-700">
                  进入模块 <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
            <div className="grid gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:items-center">
              <div>
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-950 text-teal-100">
                  <Gauge className="h-5 w-5" />
                </div>
                <h2 className="mt-6 text-3xl font-semibold tracking-tight">一条连续的求职闭环</h2>
                <p className="mt-4 text-sm leading-7 text-slate-600">
                  简历、JD、面试回答、短板报告、题库与投递事件不再是孤立工具。它们在后端通过会话、素材、记忆和 AgentRun 串成可追踪流程。
                </p>
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                {workflow.map((item, index) => (
                  <div key={item.title} className="relative rounded-2xl border border-slate-200 bg-slate-50 p-5">
                    <div className="text-xs font-semibold text-teal-700">0{index + 1}</div>
                    <item.icon className="mt-5 h-5 w-5 text-slate-700" />
                    <h3 className="mt-4 text-sm font-semibold">{item.title}</h3>
                    <p className="mt-2 text-xs leading-6 text-slate-600">{item.text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
          <div className="overflow-hidden rounded-3xl bg-teal-950 px-6 py-10 text-white sm:px-10 lg:flex lg:items-center lg:justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs font-medium text-teal-200">
                <KeyRound className="h-4 w-4" />
                先连接你的模型通道
              </div>
              <h2 className="mt-4 text-2xl font-semibold">准备好后，从一场定向面试开始。</h2>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-teal-50/70">API Key 明文保存在当前浏览器，并会在执行任务时发送给后端。请勿截图或共享设置，公网部署请使用 HTTPS。</p>
            </div>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row lg:mt-0">
              <Button variant="outline" className="border-white/20 bg-white/5 text-white hover:bg-white/10 hover:text-white" onClick={onOpenSettings}>
                <Settings2 className="h-4 w-4" /> 配置模型
              </Button>
              <Button className="bg-teal-300 text-teal-950 hover:bg-teal-200" onClick={() => onNavigate("interview")}>
                进入工作台 <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-5 py-8 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <div className="flex items-center gap-2">
            <Image src="/logo.png" alt="" width={24} height={24} className="rounded-lg" />
            <span>{PRODUCT_NAME}</span>
          </div>
          <span>本地优先 · 模型可配置 · 外部动作保留人工确认</span>
        </div>
      </footer>
    </div>
  );
}

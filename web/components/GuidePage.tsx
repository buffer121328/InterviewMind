"use client";

import {
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  Bot,
  BriefcaseBusiness,
  Database,
  FileText,
  KeyRound,
  ListChecks,
  ShieldCheck,
  Target,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { MainView } from "@/lib/navigation";
import { PRODUCT_NAME } from "@/lib/product";

interface GuidePageProps {
  onBack: () => void;
  onNavigate: (view: MainView) => void;
  onOpenSettings: () => void;
}

const sections: Array<{
  view: MainView;
  title: string;
  summary: string;
  icon: typeof Bot;
  steps: string[];
}> = [
  {
    view: "interview",
    title: "模拟面试",
    summary: "根据简历、JD、公司信息、个人题库和面经候选题生成定向面试。",
    icon: Bot,
    steps: ["配置 Smart / Fast 通道", "上传简历并填写目标 JD", "选择轮次、题数与文字/语音模式", "完成后生成能力画像和短板报告"],
  },
  {
    view: "resume",
    title: "简历工作台",
    summary: "把简历分析、优化、JD 匹配、素材库、项目改写与成品生成串成一条流程。",
    icon: FileText,
    steps: ["导入或粘贴原始简历", "关联目标 JD 与历史面试", "选择分析、优化或匹配任务", "审核建议后生成并保存简历版本"],
  },
  {
    view: "questionbank",
    title: "题库与面经",
    summary: "沉淀手工题目、文件题库、面经页面和历史面试追问。",
    icon: BookOpenCheck,
    steps: ["新增题目或解析文件预览", "确认后写入个人题库", "按类型、难度和关键词检索", "在面试设置中选择抽题数量"],
  },
  {
    view: "boss",
    title: "岗位中心",
    summary: "支持单个 JD 采集和 BOSS 推荐页半自动化，并通过后台任务生成投递资产。",
    icon: Target,
    steps: ["确认宿主机自动化服务和登录状态", "采集岗位或搜索推荐页", "等待 JD 分析、定制简历和招呼语生成", "先预览，再对真实发送作二次确认"],
  },
  {
    view: "applications",
    title: "投递管理",
    summary: "管理收藏、已投递、面试、Offer 与终止状态，并记录完整事件流水。",
    icon: BriefcaseBusiness,
    steps: ["创建或补录投递", "绑定所用简历版本", "更新岗位状态和优先级", "在详情中记录电话面、技术面与结果"],
  },
  {
    view: "memory",
    title: "长期记忆",
    summary: "查看系统从面试中提取的偏好与经历，必要时搜索、审计或删除。",
    icon: Database,
    steps: ["配置 mem0 LLM 与 Embedding 通道", "在面试中形成可复用记忆", "按关键词或语义搜索", "删除错误记忆，清空全部记忆需再次确认"],
  },
  {
    view: "runs",
    title: "任务运行",
    summary: "追踪异步 AgentRun 的执行阶段、版本、尝试次数和错误原因。",
    icon: Workflow,
    steps: ["查看活跃与历史任务", "展开执行计划和当前阶段", "取消仍可取消的任务", "仅对后端允许的失败任务发起重试"],
  },
];

export function GuidePage({ onBack, onNavigate, onOpenSettings }: GuidePageProps) {
  return (
    <div className="min-h-screen bg-[#f7faf9]">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={onBack} aria-label="返回首页">
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <div className="text-sm font-semibold">{PRODUCT_NAME}使用指南</div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-teal-700">Workflow guide</div>
            </div>
          </div>
          <Button variant="outline" onClick={onOpenSettings}>
            <KeyRound className="h-4 w-4" /> 模型设置
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-14 sm:px-8">
        <section className="grid gap-8 lg:grid-cols-[1fr_0.72fr] lg:items-end">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-teal-700">Getting started</div>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.035em] text-slate-950 sm:text-5xl">先建立上下文，再让 Agent 工作。</h1>
            <p className="mt-5 max-w-3xl text-base leading-8 text-slate-600">最佳使用方式不是逐个尝试功能，而是先配置模型、导入简历与 JD，再沿着面试、复盘、补强、投递的顺序持续沉淀数据。</p>
          </div>
          <div className="rounded-2xl border border-teal-200 bg-teal-50 p-5 text-sm leading-7 text-teal-950">
            <div className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4" /> 安全边界</div>
            <p className="mt-2 text-teal-900/75">API Key 保存在浏览器本地并随任务请求传给后端；BOSS 真实发送必须经过预览、短期许可和显式确认。</p>
          </div>
        </section>

        <section className="mt-12 grid gap-4 md:grid-cols-3">
          {[
            ["1", "连接模型", "至少配置 Smart 与 Fast；其余通道可按能力独立分配。"],
            ["2", "建立资料", "导入简历、JD、题库和面试经历，形成候选人上下文。"],
            ["3", "执行与复盘", "通过任务运行查看进度，把报告、记忆和投递事件继续沉淀。"],
          ].map(([number, title, text]) => (
            <div key={number} className="surface-panel p-5">
              <div className="text-xs font-semibold text-teal-700">STEP {number}</div>
              <h2 className="mt-4 font-semibold">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
            </div>
          ))}
        </section>

        <section className="mt-16">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <ListChecks className="h-4 w-4 text-teal-700" />
            七个工作区模块
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {sections.map((section) => (
              <article key={section.view} className="surface-panel flex flex-col p-6">
                <div className="flex items-start gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-teal-950 text-teal-100">
                    <section.icon className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-semibold">{section.title}</h2>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{section.summary}</p>
                  </div>
                </div>
                <ol className="mt-5 grid gap-2 sm:grid-cols-2">
                  {section.steps.map((step, index) => (
                    <li key={step} className="flex gap-2 rounded-xl bg-slate-50 px-3 py-2.5 text-xs leading-5 text-slate-600">
                      <span className="font-semibold text-teal-700">{index + 1}</span>
                      {step}
                    </li>
                  ))}
                </ol>
                <Button variant="ghost" className="mt-4 self-start px-0 text-teal-700 hover:bg-transparent hover:text-teal-900" onClick={() => onNavigate(section.view)}>
                  打开{section.title} <ArrowRight className="h-4 w-4" />
                </Button>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

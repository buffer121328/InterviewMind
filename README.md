# InterviewMind — 面必过

> 基于 AI Agent 的全能求职助手技能包。零环境、零部署——让 codex 直接扮演你的专属职业咨询师。

[![Try 面必过 on Socialistic](https://socialistic.ai/api/embed/shaped-skills-91d17b?lang=zh)](https://socialistic.ai/zh/skill/shaped-skills-91d17b?utm_source=github&utm_medium=readme&utm_campaign=20260624-speech-presentation-sim-builders&utm_content=badge)

没装 codex 也想先看看效果？可以[在线试一下](https://socialistic.ai/zh/skill/shaped-skills-91d17b?utm_source=github&utm_medium=readme&utm_campaign=20260624-speech-presentation-sim-builders&utm_content=hyperlink)：上传简历和 JD 就能跑模拟面试 / 简历优化，无需本地环境。

## 为什么用这个

传统「面必过」是一个全栈 Web 应用：Docker + PostgreSQL + pgvector + FastAPI + Next.js。对想试一次模拟面试的求职者来说，环境门槛太高。

**InterviewMind 把核心求职工作流提炼为 AI Agent 可直接执行的技能文件。** Agent 本身就是运行时 + LLM，不需要任何额外基础设施：

| 传统版本 | 技能版 |
|---------|--------|
| Docker + PostgreSQL + pgvector | 零。Agent 上下文即存储 |
| 自己配 API Key | 零。Agent 的 LLM 就是你的模型 |
| FastAPI + Next.js 前后端 | 零。Agent 直接对话执行 |
| mem0 长期记忆 | md 文件，Agent 全文读入上下文 |

**只需要两样东西：codex（推荐，原生语音面试支持），和你的简历文件。**

---

## 技能清单

以下技能作为项目级技能安装后，codex 会根据你的自然语言自动匹配——**不需要前缀或特殊命令**。

| 技能 | 做什么 | 你只需说 |
|------|--------|---------|
| `interviewmind-resume` | PDF 解析 + JD 匹配分析 + 6 维评分 + 定制改写 + A4 HTML 导出 | `优化简历` |
| `interviewmind-interview` | 6 阶段模拟面试（开场→技术深挖→项目实战→行为问题→反问→总结） | `模拟面试 Java后端 社招3年` |
| `interviewmind-project-rewrite` | STAR 法重构项目经历，强动词 + 量化数据 | `STAR改写这段项目经历` |
| `interviewmind-debrief` | 面试复盘 → 能力雷达图 + 弱点报告 + 补强建议 | `复盘上次面试` |
| `interviewmind-boss` | agent-browser 驱动 BOSS 搜索 → 抓岗位 → 匹配打分 → 生成投递资产 | `BOSS搜Java架构师 北京 前5` |
| `interviewmind` | 路由入口，识别意图 → 分派子技能；首次运行初始化工作区 | 以上任一触发词均可 |

---

## 安装

本技能包设计为**项目级别技能**——每个求职方向一个独立工作区，技能随项目走，不污染全局配置。

### 方式一：用 codex 初始化（推荐）

1. 在 codex 中**新建一个空白工作区**（如 `~/job-prep-java/`）
2. 在工作区中对 codex 说：

```
引入 github.com/buffer121328/InterviewMind 的 lite 分支 skills/ 作为项目技能，并按其约定初始化 mianbiguo/ 工作区
```

codex 会自动：
1. 把 `skills/` 下全部技能拷贝到 `.agents/skills/`
2. 初始化 `mianbiguo/` 工作区

### 方式二：手动两步

```bash
# 1. 新建工作区并进入
mkdir ~/my-interview-prep && cd ~/my-interview-prep

# 2. 把 lite 分支的 skills/ 拷到 .agents/skills/
git clone --depth 1 --branch lite https://github.com/buffer121328/InterviewMind.git /tmp/interviewmind
cp -r /tmp/interviewmind/skills/* .agents/skills/
rm -rf /tmp/interviewmind
```

完成后的目录结构：

```
~/my-interview-prep/
├── .agents/skills/                    ← 项目级技能（codex 自动发现）
│   ├── interviewmind/
│   ├── interviewmind-interview/
│   ├── interviewmind-resume/
│   ├── interviewmind-project-rewrite/
│   ├── interviewmind-debrief/
│   └── interviewmind-boss/
├── mianbiguo/                      ← 工作区（首次使用时自动创建）
│   ├── profile.md
│   ├── resume.md
│   ├── jd.md
│   ├── memory_bank.md
│   ├── sessions/
│   └── outputs/
├── 我的简历.pdf                       ← 你的材料
└── jd.md
```

### 多岗位/多方向

不同求职方向用不同项目目录，各自独立：

```bash
~/job-prep-java/      ← 投 Java 岗的简历 + JD + 面试记录
~/job-prep-product/   ← 投产品经理岗的材料
~/job-prep-algorithm/ ← 投算法岗的材料
```

---

## 快速开始

装好后，把简历 PDF 和 JD 丢进工作区目录，打开 codex 直接说：

```
优化简历
```

codex 会自动：
1. 发现目录里的 `resume.pdf`，解析为 `mianbiguo/resume.md`
2. 如果目录里有 `jd.md` 就读，没有就问你要
3. 输出 6 维评分 + 四维匹配 + 逐条改写建议 + A4 精排 HTML

### 一分钟走通全部流程

```bash
# 1. 创建项目 + 安装技能（首次）
mkdir ~/my-interview-prep && cd ~/my-interview-prep
git clone --depth 1 --branch lite https://github.com/buffer121328/InterviewMind.git /tmp/im
cp -r /tmp/im/skills/* .agents/skills/ && rm -rf /tmp/im

# 2. 丢材料
cp ~/Downloads/我的简历.pdf .
echo "粘贴目标岗位 JD" > jd.md

# 3. 在这个目录下打开 codex，说：
#    "优化简历"
# → 拿到优化后简历 + A4 HTML

# 4. 接着：
#    "模拟面试 Java后端 社招3年 严厉拷打型"
# → 6 阶段面试开始

# 5. 面试完：
#    "复盘上次面试"
# → 拿到雷达图 + 弱点报告
```

---

## 详细用法

### 1. 简历优化 `interviewmind-resume`

**你需要准备**：
- 一份简历（支持 `.pdf` / `.docx` / `.txt`，或粘贴纯文本）
- 一份目标岗位 JD（粘贴或写入 `jd.md`）

**触发方式**（任一即可）：
```
优化简历
分析这份简历
改一下我的简历
帮我看看简历和这个JD匹配吗
```

**你会得到**：

| 产物 | 位置 | 说明 |
|------|------|------|
| 6 维评分表 | 对话中 | 结构/完整度/量化/清晰度/亮点/JD匹配，各 1-10 分 |
| 四维匹配分析 | 对话中 | 技能/项目/经验/教育 匹配度百分比 + 差距 |
| 逐条改写建议 | 对话中 | 位置 → 当前内容 → 建议修改 → 理由 |
| 优化后简历 | `mianbiguo/outputs/resume-optimized-日期.md` | Markdown 格式，可直接粘贴 |
| STAR 项目改写 | `mianbiguo/outputs/star-projects-日期.md` | 自动调用 project-rewrite 生成 |
| A4 精排 HTML | `mianbiguo/outputs/resume-日期.html` | Chrome 打开 → Cmd+P → 导出 PDF |

**PDF 解析说明**：codex 会按顺序尝试 `pdftotext`（poppler）→ `PyMuPDF` → 让你粘贴。如果 PDF 是扫描版图片，请直接粘贴文本。

---

### 2. 模拟面试 `interviewmind-interview`

**你需要准备**：
- 已优化过的简历（在 `mianbiguo/resume.md`）
- 知道目标岗位类型和你的求职身份

**触发方式**：
```
模拟面试 Java后端 社招3年
mock interview 产品经理 应届
面试 算法工程师 社招5年 深挖学术型
来一场技术面 前端 社招1-3年
```

**面试风格**（可选，默认「专业高效型」）：

| 风格 | 适合人群 |
|------|---------|
| 严厉拷打型 | 想模拟高压面试、找出盲区 |
| 温和鼓励型 | 面试练习新手、需要建立信心 |
| 专业高效型 | 模拟一线大厂紧凑节奏（默认） |
| 深挖学术型 | 算法/研究员岗位，追问理论原理 |
| 工程实践型 | 资深工程师，关注架构决策和故障处理 |

**面试流程**（6 阶段）：
1. **开场** — 你自我介绍，面试官根据内容追问信息空白
2. **技术深挖** — 基于你简历的技能清单，逐点追问原理和实现
3. **项目实战** — 深挖你最重要的项目：选型理由、难点、可扩展性
4. **行为问题** — 团队协作、故障处理、技术决策等软技能
5. **反问环节** — 你向面试官提问
6. **面试总结** — 6 维评分 + 亮点 + 改进建议 + 下一场方向

**你会得到**：

| 产物 | 位置 | 说明 |
|------|------|------|
| 完整面试记录 | `mianbiguo/sessions/日期-类型.md` | 全部 Q&A + 评分 + 评价 |
| Memory 更新 | `mianbiguo/memory_bank.md` | 弱点维度、改进方向，供复盘用 |

**重要规则**：面试官一次只问一个问题，基于你的简历追问，不编造你没写的内容，评分给具体数字（1-10）。

---

### 3. 项目 STAR 改写 `interviewmind-project-rewrite`

**你需要准备**：
- 一段项目经历原文（从简历复制或直接描述）

**触发方式**：
```
STAR改写这段：[粘贴原文]
用STAR法重写我的项目经历
帮我把这个项目改得更有说服力
```

**你会得到**：

| 产物 | 位置 | 说明 |
|------|------|------|
| STAR 拆解表 | 对话中 | 原文对照，标注缺失环节 |
| 缺口追问 | 对话中 | 如果缺少数据，codex 会追问你补充 |
| 改写后项目 | `mianbiguo/outputs/star-projects-日期.md` | 含情境/任务/成果 + STAR bullets |

**改写标准**：每条 bullet 以强动词开头（设计、实现、优化、重构）→ 含量化数据 → ≤80 中文字符。禁止「参与了」「协助了」等弱动词。

这个技能也会被简历优化流程自动调用。

---

### 4. 面试复盘 `interviewmind-debrief`

**你需要准备**：
- 至少完成过一次模拟面试（`sessions/` 下有记录）

**触发方式**：
```
复盘上次面试
分析我的面试表现
debrief
帮我看看面试哪里答得不好
```

**你会得到**：

| 产物 | 位置 | 说明 |
|------|------|------|
| 6 维逐题分析 | 对话中 | 每道 Q&A 回合的问题诊断 |
| 雷达图 PNG | `mianbiguo/outputs/radar-日期.png` | 6 边形 matplotlib 雷达图 |
| 弱点报告 | 对话中 | 每弱点含具体表现 + 根本原因 + 补强建议 |
| A4 复盘 HTML | `mianbiguo/outputs/debrief-日期.html` | 完整复盘报告，可打印 |
| Memory 更新 | `mianbiguo/memory_bank.md` | 记录最高/最低分维度 + 下次建议 |

---

### 5. BOSS 半自动化 `interviewmind-boss`

**你需要准备**：
- macOS + Chrome 浏览器
- Chrome 中**已登录** BOSS 直聘（zhipin.com）
- agent-browser 已安装：`npm i -g agent-browser && agent-browser install`
- 简历已存在于 `mianbiguo/resume.md`

**触发方式**：
```
BOSS搜Java架构师 北京 前5
在BOSS上找Go后端的岗位 上海 3个
直聘搜产品经理 深圳 10
帮我搜一波Python后端岗 杭州 5
```

**工作流程**：
1. codex 检测你的 Chrome profile（首次会列出 profile 列表让你选哪个已登录 BOSS）
2. 自动打开 BOSS 搜索页，填入关键词和城市
3. 如果遇到滑块验证码 → 告诉你手动滑 → 每 8 秒检测是否完成 → 最长等 180 秒
4. 抓取最多 15 张岗位卡片 → LLM 提取信息
5. 5 维快速匹配打分（技能/级别/行业/薪资/地址）
6. 对前 N 个岗位逐个生成：JD 分析 + 3 条定制打招呼语 + 优化简历

**你会得到**：

| 产物 | 位置 | 说明 |
|------|------|------|
| 岗位匹配表 | 对话中 | 公司/岗位/薪资/匹配分 |
| 投递批次汇总 | `mianbiguo/outputs/jobs-batch-日期.md` | 每岗位含 JD 分析 + 3 语气打招呼 + 简历链接 |
| 定制简历 | `mianbiguo/outputs/resume-公司-日期.md` | 针对该岗位微调的简历 |

**安全说明**：不自动绕过验证码（等你手动完成），卡片间 3 秒间隔，不禁爬虫协议对抗，仅供个人求职使用。

---

## 工作区结构

首次使用时自动创建 `mianbiguo/`：

```
项目目录/
└── mianbiguo/
    ├── profile.md              ← 你的基本信息（codex 引导填写）
    ├── resume.md               ← 你的简历（PDF 解析结果或手写）
    ├── jd.md                   ← 目标岗位 JD（codex 引导填写）
    ├── memory_bank.md          ← 自动维护：偏好、面试历史、弱点
    ├── sessions/               ← 面试对话记录
    │   └── 2026-06-24-Java后端-阿里.md
    └── outputs/                ← 全部产物
        ├── resume-optimized-0624.md
        ├── star-projects-0624.md
        ├── resume-0624.html
        ├── debrief-0624.html
        ├── radar-0624.png
        └── jobs-batch-0624.md
```

---

## 常见问题

**Q: 需要配 API Key 吗？**  
不需要。codex 本身就是 LLM，skill 不额外调用外部 API。

**Q: 我的简历隐私安全吗？**  
全程在本机运行。PDF 解析、LLM 分析、HTML 生成都在 codex 上下文中完成，不经过任何第三方服务器。

**Q: BOSS 功能在 Windows/Linux 上能用吗？**  
当前 Chrome profile 检测脚本和 agent-browser 调用默认适配 macOS。Windows/Linux 需要手动指定 Chrome profile 路径。

**Q: 生成的 HTML 怎么转 PDF？**  
Chrome/Edge 打开 `.html` 文件 → Cmd+P → 另存为 PDF。CSS 已预配 A4 尺寸和打印边距。

**Q: 模拟面试能语音吗？**  
codex 原生支持语音交互，面试过程中可以直接用语音回答，体验接近真实面试。传统全栈版（main 分支）也有语音面试支持。

**Q: 可以两个人同时用吗？**  
不同项目目录互不干扰，各自独立的技能和工作区。

**Q: 我只说「优化简历」codex 怎么知道调哪个技能？**  
项目级技能由描述自动匹配。`interviewmind-resume` 的描述里写了「简历优化、改简历、resume」等触发词，codex 读到你的话会命中对应技能。说不准的时候，`interviewmind`（路由）会出来问你要做哪一项。

---

## 与传统版的关系

| | 技能版（lite 分支） | 传统版（main 分支） |
|---|---|---|
| 使用方式 | codex 对话执行 | Web 应用（localhost:3000） |
| 需安装 | 零 | Docker + PG + pgvector |
| API Key | 零（codex 即 LLM） | 需配 DashScope/DeepSeek 等 |
| 语音面试 | ✅ codex 原生语音 | ✅ OpenAI Realtime |
| 长期记忆 | md 文件 | mem0 + pgvector |
| 求职看板 | ❌ | ✅ |
| 题库 | ❌ | ✅ |
| BOSS 自动化 | agent-browser 半自动 | AppleScript + Chrome |
| 适用 | 个人求职者快速体验 | 需要完整功能/托管服务 |

两者共用一套求职方法论（6 维评分、STAR 改写、6 阶段面试），从技能版开始，需要更多功能再切到传统版。

---

## 许可证

本项目使用 [非商业使用许可证](../LICENSE)。允许个人学习、研究、非商业求职用途。

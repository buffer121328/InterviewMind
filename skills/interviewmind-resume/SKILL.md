---
name: interviewmind-resume
description: >
  简历深度优化与A4排版导出。上传PDF简历自动解析为Markdown，基于JD进行6维度
  匹配评分，输出结构化修改建议（每项包含原文、建议修改、修改理由）。
  最终生成A4大小的精美HTML（可直接打印/转PDF）。触发词：简历优化、改简历、
  resume、简历分析、简历评分。
---

# 简历深度优化

## 启动：确认输入

1. 检查 `mianbiguo/resume.md` 是否存在且有内容
   - 如果不存在 → 搜索当前目录下是否有 .pdf / .docx 文件
   - 如果有 PDF → 执行 PDF 解析（见下节）
   - 如果都没有 → 请用户粘贴简历纯文本，写入 `mianbiguo/resume.md`
2. 检查 `mianbiguo/jd.md` 是否存在
   - 如果不存在 → 请用户粘贴目标岗位 JD 文本，写入 `mianbiguo/jd.md`
3. 读取 `mianbiguo/profile.md` — 补全用户基本信息（如果还没填，轻松问两句）

## PDF 解析（回退链）

按序尝试，成功则跳到「优化流程」：

```
# 方法1: pdftotext (poppler)
pdftotext -layout <pdf_file> mianbiguo/resume.md

# 方法2: PyMuPDF
pip install pymupdf 2>/dev/null && python3 -c "
import fitz, sys
doc = fitz.open(sys.argv[1])
for page in doc:
    print(page.get_text('text'))
doc.close()
" <pdf_file> > mianbiguo/resume.md

# 方法3: 告知用户
"PDF 解析失败。请把简历内容粘贴到这条消息里，我来保存为 resume.md。"
```

无论如何拿到 resume.md 后，告知用户：「已解析。你要先看一遍吗？还是直接基于 JD 开始优化？」

## 优化流程

读取 `skills/interviewmind/references/scoring-rubric.md` 中的 6 维度标准。

### 步骤 1: JD 分析

- 提取 JD 中的：必备技能、加分技能、行业经验要求、级别要求
- 输出简要的 JD 关键要素清单

### 步骤 2: 简历-JD 匹配评估

用 6 维度模型（结构、完整度、量化、清晰度、亮点、JD匹配）对当前简历打分，
同时分析技能/项目/经验/教育四维匹配度。

输出格式：
```markdown
## 匹配评估

| 维度 | 评分 | 依据 |
|------|------|------|
| 结构 | X/10 | ... |
| ... | ... | ... |

## 四维匹配

| 维度 | 匹配度 | 当前状态 | JD要求 | 差距 |
|------|--------|---------|--------|------|
| 技能 | X% | ... | ... | ... |
| 项目 | X% | ... | ... | ... |
| 经验 | X% | ... | ... | ... |
| 教育 | X% | ... | ... | ... |

## 优先改写建议（Top 3）
1. [建议1]
2. [建议2]
3. [建议3]
```

### 步骤 3: 定制改写

逐项输出修改建议，使用以下表格格式：

```markdown
| # | 位置 | 当前内容 | 建议修改 | 理由 |
|---|------|---------|---------|------|
| 1 | 个人信息 | 求职意向: 未写 | 求职意向: Java后端开发工程师 | JD明确要求Java方向 |
| 2 | 技能清单 | "熟悉Spring" | "精通Spring Boot 3.x/Spring Cloud，曾用Seata实现分布式事务，支撑日均50万订单" | 量化+具体化，匹配JD分布式要求 |
```

每项建议必须包含「理由」列。

### 步骤 4: 简历组装

基于改写建议，生成完整优化后简历。保存到 `mianbiguo/outputs/resume-optimized-YYYYMMDD.md`。

### 步骤 5: STAR 项目改写（可选）

如果用户简历中有项目经历 → 自动调用 `Skill("interviewmind-project-rewrite")` 对每个项目做 STAR 改写。
产物保存到 `mianbiguo/outputs/star-projects-YYYYMMDD.md`。

### 步骤 6: A4 HTML 导出

生成 A4 排版 HTML。做法：

1. 读取 `skills/interviewmind/references/html-resume.css` 获取样式
2. 基于优化后的简历内容 + STAR 项目（如果有）组装 HTML，结构：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>XXX 的简历</title>
<style>
/* 内联 html-resume.css 的全部内容，确保独立文件可打印 */
</style>
</head>
<body>

<div class="resume-header">
  <div class="name">姓名</div>
  <div class="contact">
    <span>📧 email@example.com</span>
    <span>📱 138-xxxx-xxxx</span>
    <span>🌐 github.com/xxx</span>
  </div>
</div>

<div class="section-title">技能矩阵</div>
<div class="skill-tags">
  <span class="skill-tag">Java</span>
  <span class="skill-tag">Spring Boot</span>
</div>

<div class="section-title">工作经历</div>
<!-- exp-item 结构 -->

<!-- 如果 star-projects.md 存在，添加项目精选 -->
<div class="section-title">项目精选 (STAR)</div>

<div class="section-title">教育背景</div>
</body>
</html>
```

保存到 `mianbiguo/outputs/resume-YYYYMMDD.html`。

告知用户：「简历 HTML 已生成，用 Chrome/Edge 打开后 Cmd+P 即可打印为 A4 PDF。」

## 约束清单

- [ ] 修改建议必须具体到原文位置
- [ ] 不编造用户没做过的项目或技能
- [ ] HTML 必须在 `<style>` 内内联全部 CSS
- [ ] 所有产物写入 `mianbiguo/outputs/`
- [ ] 更新 `mianbiguo/memory_bank.md`

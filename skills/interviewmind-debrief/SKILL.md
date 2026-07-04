---
name: interviewmind-debrief
description: >
  面试复盘分析。读取面试对话记录（session transcript），输出6维度能力雷达图、
  弱点报告及针对性补强建议。生成独立A4 HTML复盘报告（含雷达图PNG）。
  触发词：面试复盘、debrief、面试分析、能力雷达图、弱点分析。
---

# 面试复盘分析

## 启动

1. 搜索 `mianbiguo/sessions/` 目录，列出现有的面试记录
2. 如果只有一场 → 直接分析
3. 如果有多场 → 让用户选一场
4. 如果没有面试记录 → 提示"还没有面试记录。对我说「模拟面试」开始一场吧"

## 分析流程

### 步骤 1: 逐题评分

读取面试记录，对每个 Q&A 回合做分析。不要求每道题都打分，但至少覆盖以下维度：

| 维度 | 评估内容 | 关注的信号 |
|------|---------|-----------|
| 专业知识 | 基础知识扎实度、技术广度 | 对概念理解的准确度、追问时能否深入 |
| 项目深度 | 实际工作经验、问题解决能力 | 项目描述的细节粒度、trade-off 解释 |
| 系统设计 | 架构能力、技术选型判断力 | 方案对比思维、扩展性/性能考量 |
| 编码能力 | 代码质量意识、工程素养 | 具体实现细节、性能优化经验 |
| 沟通表达 | 结构化表达、逻辑连贯性 | 回答是否有"首先-然后-最后"结构 |
| 逻辑思维 | 分析推理、问题拆解能力 | 面对开放问题的拆解方式 |

### 步骤 2: 生成雷达图

用 Python matplotlib 生成 6 边形雷达图：

```bash
pip install matplotlib 2>/dev/null && python3 -c "
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

categories = ['专业知识', '项目深度', '系统设计', '编码能力', '沟通表达', '逻辑思维']
scores = [6, 7, 5, 7, 8, 6]  # 替换为实际评分

N = len(categories)
angles = [n / float(N) * 2 * np.pi for n in range(N)]
angles += angles[:1]

fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
ax.set_theta_offset(np.pi / 2)
ax.set_theta_direction(-1)

plt.xticks(angles[:-1], categories, fontsize=12, fontfamily='sans-serif')
ax.set_rlabel_position(0)
plt.yticks([2, 4, 6, 8, 10], ['2', '4', '6', '8', '10'], fontsize=8)
plt.ylim(0, 10)

values = scores + scores[:1]
ax.plot(angles, values, 'o-', linewidth=2, color='#2563eb')
ax.fill(angles, values, alpha=0.15, color='#2563eb')

plt.tight_layout()
plt.savefig('mianbiguo/outputs/radar-YYYYMMDD.png', dpi=150, bbox_inches='tight')
print('雷达图已保存')
"
```

### 步骤 3: 弱点报告

输出格式：

```markdown
## 弱点分析

### 弱点 1: [维度名称] — 得分 [X/10]

**具体表现**:
- 在第 N 题 "[问题内容]" 中，用户的回答 [具体问题]
- [另一个具体表现]

**根本原因**: [技术积累不足？表达训练不够？项目经验欠缺？]

**补强建议**:
- [具体可操作的建议 1]
- [具体可操作的建议 2]
```

### 步骤 4: 生成 HTML 报告

生成独立 A4 HTML 报告，保存到 `mianbiguo/outputs/debrief-YYYYMMDD.html`，包含：

- 面试总结标题（日期+类型）
- 内嵌雷达图（用 `<img src="radar-YYYYMMDD.png">` 或 base64 inline）
- 弱点分析表格
- 补强建议清单
- 使用 A4 CSS 样式（内联 `skills/interviewmind/references/html-resume.css`）

### 步骤 5: 更新 memory_bank

在 `mianbiguo/memory_bank.md` 追加：

```markdown
## [日期] 面试复盘
- 最高分维度: [维度] [X/10]
- 最低分维度: [维度] [X/10]
- 下次建议练习: [具体建议]
```

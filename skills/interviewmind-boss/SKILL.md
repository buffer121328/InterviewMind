---
name: interviewmind-boss
description: >
  BOSS直聘半自动化投递。使用agent-browser驱动已登录BOSS的Chrome，
  搜索匹配岗位、抓取卡片、匹配打分、生成定制简历+打招呼文案。
  需要macOS + Chrome + 已登录BOSS直聘。触发词：BOSS投递、BOSS直聘、
  直聘投递、BossCenter、自动打招呼。
---

# BOSS 直聘半自动化

## 前置条件

1. macOS 系统
2. Chrome 浏览器已安装
3. **Chrome 中已登录 BOSS 直聘** (https://www.zhipin.com)
4. agent-browser 已安装：`npm i -g agent-browser && agent-browser install`

## 启动

确认参数：
1. **搜索关键词**（如 "Java架构师" "Go后端" "产品经理"）
2. **城市**（默认北京，如 "上海" "深圳" "全国"）
3. **取前 N 个岗位**（默认 5）
4. **简历内容**（读取 `mianbiguo/resume.md`，如果有优化版本用优化版）

## 步骤 1: 确定 Chrome Profile

读取 `mianbiguo/memory_bank.md`，查找 `BOSS_CHROME_PROFILE=`

- 如果已配置 → 直接用
- 如果未配置 → 执行：

```bash
bash skills/interviewmind/references/chrome-profile.sh
```

根据输出让用户选择 profile 编号，记录完整路径到 `mianbiguo/memory_bank.md`：

```
BOSS_CHROME_PROFILE=/Users/xxx/Library/Application Support/Google/Chrome/Default
```

## 步骤 2: 打开 BOSS 搜索页

将城市名转为 BOSS 的城市代码（100010000=北京, 100020000=上海, 100030000=深圳, 100040000=广州, 100050000=杭州, 0=全国）。如果用户的城市不在列表中，用 0 (全国)。

```bash
agent-browser --profile "<PROFILE_PATH>" open "https://www.zhipin.com/web/geek/job?query=<关键词URL编码>&city=<城市代码>"
```

## 步骤 3: 等待页面加载 + 处理验证码

```bash
agent-browser snapshot -i
```

检查 snapshot 输出：
- 如果看到 `@eN` 中有关键词 "验证" 或 "请完成安全验证" → 进入等待模式
- 如果看到 `@eN` 中有 `text="立即沟通"` 或 `text="查看详情"` → 页面加载完成，进入步骤 4

**验证码等待模式**：
告诉用户：「BOSS 弹出了滑块验证码，请在 Chrome 浏览器里手动滑动完成验证。（最长等待 180 秒）」

然后每 8 秒执行：

```bash
agent-browser snapshot -i | grep -c "验证\|安全验证"
```

如果结果为 0（验证码消失）→ 继续步骤 4。如果 180 秒后仍未消失 → 报错退出。

## 步骤 4: 抓取岗位卡片

用 LLM 从 snapshot 中提取岗位卡片信息。snapshot 输出中，每个 job card 通常包含：
- 岗位名称 (job_title)
- 公司名称 (company_name)
- 薪资范围 (salary_text)
- 工作经验/学历要求
- 公司规模/行业
- 技能标签

最多提取 15 张卡片。如果用户要求的 top N > 15，取 15。

## 步骤 5: 匹配度打分

基于简历内容，对所有卡片做快速匹配度打分。使用以下快速打分维度：

| 维度 | 权重 | 评估方式 |
|------|------|---------|
| 技能匹配 | 40% | 岗位技能标签与简历技能的重合度 |
| 级别匹配 | 20% | 工作经验要求与候选人年限的对齐度 |
| 行业匹配 | 15% | 公司行业与候选人过往行业的重合度 |
| 薪资匹配 | 10% | 薪资范围是否在候选人期望范围内 |
| 地址匹配 | 15% | 城市匹配度 |

输出格式：

```markdown
| # | 公司 | 岗位 | 薪资 | 城市 | 匹配分 | 匹配分析 |
|---|------|------|------|------|--------|---------|
| 1 | XX | Java架构师 | 40-70K | 北京 | 92 | 技能100%匹配，行业相关 |
```

按匹配分降序，取前 N 个。

## 步骤 6: 生成投递资产

对每个 Top N 岗位，生成三样东西：

### A. JD 分析（简要版）

2-3 句关键要求提取 + 匹配点简述。

### B. 定制打招呼语（3 条）

三种语气各一条（每条 ≤ 150 中文字符）：
- **professional**: 正式专业，"您好，我拥有 X 年 XX 经验..."
- **technical**: 技术对口，"您好，关注到贵司在用 XX 技术栈..."
- **thoughtful**: 走心真诚，"您好，看到贵部门在招 XX 方向的架构师..."

### C. 优化简历

基于该岗位的 JD，对 resume.md 做针对性微调 → 保存到 `mianbiguo/outputs/resume-<公司>-YYYYMMDD.md`

## 步骤 7: 汇总输出

所有结果写入 `mianbiguo/outputs/jobs-batch-YYYYMMDD.md`：

```markdown
# BOSS 投递批次 — [日期] [关键词]

| # | 公司 | 岗位 | 薪资 | 匹配分 | 打招呼(professional) |
|---|------|------|------|--------|---------------------|
| 1 | XX | ... | ... | 92 | "您好，我拥有..." |

## 第1名: [公司] - [岗位]

### JD分析
...

### 打招呼文案
- professional: "..."
- technical: "..."
- thoughtful: "..."

### 定制简历
→ [resume-XX-YYYYMMDD.md]
```

## 约束与安全

- **反爬**：不自动绕过验证码，等待用户手动完成。尊重网站使用条款。
- **限速**：卡片之间加 3 秒间隔。
- **隐私**：不将用户简历上传到任何第三方服务。所有 LLM 调用通过本地 agent 完成。
- **免责**：本工具仅供个人求职辅助，不可用于批量商业数据采集。

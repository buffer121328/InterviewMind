"""
简历生成 Graph - 交互式简历生成与包装
流程: 需求分析 -> (可选问询) -> 初稿生成 -> 初稿优化 -> 包装适度性核查 -> 润色审查 -> (循环优化) -> 输出
"""

import json
import logging
from typing import List, Optional, Dict, Any, TypedDict
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from app.schemas.llm_outputs import (
    NeedsAnalysisOutput, DraftOptimizationOutput, FactCheckOutput, FinalReviewOutput
)
from ai.llm.llm_utils import invoke_structured, clean_markdown_response
from ai.llm import llms

logger = logging.getLogger(__name__)


# ============================================================================
# 状态定义
# ============================================================================

class ResumeGenerationState(TypedDict):
    """简历生成状态"""
    # 输入
    resume_content: str
    job_description: str
    optimization_result: dict
    template_style: str
    api_config: Optional[dict]
    user_id: str
    agent_run_id: Optional[str]

    # 中间状态
    missing_info_analysis: Optional[dict]
    questions: List[str]
    user_answers: Dict[str, str]
    draft_content: str
    optimized_draft: str  # 新增：优化后的初稿
    optimization_notes: Optional[dict]  # 新增：优化说明
    fact_check_result: Optional[dict]
    review_result: Optional[dict]
    iteration_count: int

    # 输出
    final_markdown: str
    title: str


# ============================================================================
# 节点实现
# ============================================================================

async def node_analyze_needs(state: ResumeGenerationState) -> dict:
    """
    需求分析节点：分析优化结果，识别需要用户确认的信息
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    optimization_result = state.get("optimization_result") or {}
    api_config = state.get("api_config")

    prompt = f"""你是一位「简历信息核查专家」。请分析以下信息，找出生成完整简历前需要用户确认或补充的关键信息。

【原始简历】：
{resume_content}

【目标职位】：
{job_description}

【优化建议要点】：
{json.dumps(optimization_result.get('key_improvements', [])[:5], ensure_ascii=False)}

请检查以下方面是否有缺失或需要确认：
1. 量化数据（如业绩数字、用户规模、提升比例）- 仅在原文提到但未给出具体数字时询问
2. 具体技术栈或工具 - 仅在JD要求但简历未明确提及且可能具备时询问
3. 项目中的个人贡献和角色 - 仅在描述模糊时询问
4. 与目标岗位高度相关的项目经历 - 仅在项目经历描述模糊时询问

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "has_gaps": true/false,
    "questions": [
        "您在项目A中带来的用户增长大约是多少？（如：增长50%）",
        ...
    ]
}}

**重要提示**：

**什么时候应该提问（has_gaps: true）**：
- 原简历中明确提到了某项成果但缺少具体数字（如"用户增长明显"但没说多少）
- JD 中有明确的硬性要求，但简历中完全没提及（需确认是否具备）
- 关键项目的个人角色/贡献描述非常模糊，无法判断

**什么时候不应该提问（has_gaps: false）**：
- 信息已经足够生成一份完整的简历
- 缺失的信息可以通过合理推断或适度包装来弥补
- 问题太琐碎或对简历质量影响不大

**提问原则**：
- 最多只问 1-3 个最关键的问题
- 问题必须具体、容易回答（给出示例格式）
- 优先问能带来量化数据的问题
- 对于项目经历缺失，请引导用户采用 STAR 法则补充（如：背景、任务、行动、结果）
"""

    try:
        result = await invoke_structured(prompt, NeedsAnalysisOutput, api_config, channel="general")
        questions = result.questions[:3]
        has_gaps = result.has_gaps and len(questions) > 0

        logger.info(f"需求分析完成: has_gaps={has_gaps}, questions={len(questions)}")

        return {
            "missing_info_analysis": {"has_gaps": has_gaps},
            "questions": questions
        }
    except Exception as e:
        logger.error(f"需求分析节点失败: {e}")
        return {
            "missing_info_analysis": {"has_gaps": False, "error": str(e)},
            "questions": []
        }


async def node_generate_draft(state: ResumeGenerationState) -> dict:
    """
    初稿生成节点：根据所有信息生成简历初稿
    允许适度包装（Enhancement），但不能进行恶意造假
    """
    resume_content = state.get("resume_content", "")
    job_description = state.get("job_description", "")
    optimization_result = state.get("optimization_result") or {}
    user_answers = state.get("user_answers", {})
    review_result = state.get("review_result")
    template_style = state.get("template_style", "professional")
    api_config = state.get("api_config")

    # 构建用户补充信息
    user_info_section = ""
    if user_answers:
        answers_text = "\n".join([f"- {q}: {a}" for q, a in user_answers.items()])
        user_info_section = f"\n\n【用户补充信息】：\n{answers_text}"

    # 如果有审查反馈，加入改进指导
    review_guidance = ""
    if review_result and not review_result.get("passed", True):
        issues = review_result.get("issues", [])
        factual_notes = []
        for i in issues:
            if i.get('type') == 'excessive_fabrication':
                # 适配新的结构化字段
                loc = i.get('location', '未知位置')
                fab = i.get('fabricated', '未知内容')
                reason = i.get('reason', '')
                note = f"- 【{loc}】检测到造假：{fab}（原因：{reason}）"
                factual_notes.append(note)

        if factual_notes:
            review_guidance = f"\n\n【重要修正要求】上次生成存在过度包装或逻辑漏洞，请修正：\n" + "\n".join(factual_notes)

    style_guide = {
        "professional": "专业简洁，突出真实成就和数据，适合企业应聘",
        "academic": "学术风格，强调研究成果和发表，适合学术岗位",
        "creative": "创意设计，可以有个性化表达，适合创意行业"
    }

    # 提取关键词分析
    keyword_analysis = optimization_result.get('keyword_analysis', {})
    jd_keywords = keyword_analysis.get('jd_keywords', [])
    missing_keywords = keyword_analysis.get('missing', [])
    keyword_recommendations = keyword_analysis.get('recommendations', [])

    # 构建关键词指导
    keyword_section = ""
    if jd_keywords or missing_keywords or keyword_recommendations:
        keyword_section = f"""

【关键词分析 - 重点执行】：
- JD核心关键词：{json.dumps(jd_keywords[:10], ensure_ascii=False)}
- 简历中缺失的关键词：{json.dumps(missing_keywords[:8], ensure_ascii=False)}
- 建议添加的关键词：{json.dumps(keyword_recommendations[:8], ensure_ascii=False)}

请务必在简历中自然地融入上述关键词，特别是缺失的关键词！
"""

    prompt = f"""你是一位「资深简历包装专家」。请根据以下信息，为候选人打造一份**精炼有力、具有竞争力**的简历。

**核心原则**：
1. **精炼为王**：删减冗余表达，每个要点都要有信息量，避免空洞的描述。
2. **强化岗位匹配**：优先突出与目标职位最相关的经历、技能和成果，弱化或省略不相关内容。
3. **适度包装**：在真实基础上，对经历进行专业化润色和合理延伸（详见下方包装范畴）。
4. **严禁恶意造假**：不能编造不存在的公司、职位或完全不具备的硬技能。

【适度包装的范畴 - 允许执行】：
✅ **语言升维**：将口语化描述升级为专业表达
   - "修了bug" → "修复核心模块内存泄漏问题，提升系统稳定性"
   - "做了个网站" → "独立开发企业官网，提升品牌线上曝光度"

✅ **合理推导**：基于已有经历进行逻辑延伸
   - 开发了后台系统 → "设计并实现企业级后台管理系统，支撑N个业务部门高效运营"
   - 参与用户增长 → "参与用户增长策略制定，助力产品用户规模提升"

✅ **量化成果**：用合理估算的数据增强说服力
   - 使用"约"、"超"、"近"等修饰词，如"用户增长约30%"、"响应时间优化超50%"
   - 基于行业标准估算合理数据，如"服务日活用户10万+"

✅ **岗位匹配强化**：主动对标JD关键词和要求
   - 将JD中的核心关键词自然融入经历描述
   - 突出展示JD要求的技能和项目经验
   - 调整描述角度，让经历更贴合目标岗位

✅ **成果放大**：突出个人贡献和影响力
   - 强调"主导"、"独立完成"、"核心负责"等角色
   - 突出对团队/业务的实际贡献

---

【原始简历】：
{resume_content}

{user_info_section}

【目标职位】：
{job_description}

【关键改进点 - 重点执行】：
{json.dumps(optimization_result.get('key_improvements', [])[:5], ensure_ascii=False, indent=2)}

上述改进点是专家分析后给出的建议，请务必在简历中体现！
{keyword_section}
{review_guidance}

---

【风格要求】：{style_guide.get(template_style, style_guide['professional'])}
【语言要求】：必须使用中文（简体）撰写。

## 输出结构（请严格按照以下格式，内容精炼有力）：

# [姓名]
> [性别] | [年龄] | [联系方式]
[求职意向] | [期望薪资] | [期望城市]

## 个人简介
（2-3句话，精炼概括核心竞争力，抓住以下重点：①核心技术/专业优势 ②最突出的成果或亮点 ③与目标岗位的匹配度。切忌冗长堆砌，每句话都要有信息量！）
- 优先把核心技术/专业优势写在前面

## 工作经历
### [公司名称] | [职位] | [时间段]
- 用精炼的语言描述核心职责和成果
- 优先展示量化成果（数据、规模、提升比例）
- 突出与目标职位相关的经历
（每段经历2-4个最有价值的要点即可，避免堆砌）

## 项目经历
### [项目名称] | [角色] | [时间段]
- 一句话说明项目背景和你的角色
- 重点描述个人贡献和量化成果
（每个项目2-3个核心要点，突出亮点）

## 专业技能
- **核心技能**：与JD最匹配的技术栈（精通/熟练）
- **辅助技能**：其他相关技能简要列出
（技能模块精简为一级列表，突出与JD匹配的核心能力）

## 教育背景
### [学校名称] | [专业] | [学历] | [时间段]
- 仅保留与职位相关的亮点（高GPA、相关课程、荣誉）

---

**输出规范**：
1. 直接输出 Markdown 内容，不要用代码块包裹，禁止使用emoji表情
2. **精炼优先**：每个要点都要有信息量，删除空洞描述
3. **突出重点**：优先展示与目标职位最相关的内容
"""

    try:
        response = await llms.invoke_text(
            [HumanMessage(content=prompt)], api_config, channel="content_writer"
        )
        draft = response.content.strip()

        # 清理可能的代码块包裹
        draft = clean_markdown_response(draft)

        logger.info(f"初稿生成完成 (含适度包装): {len(draft)} 字符")
        return {"draft_content": draft}
    except Exception as e:
        logger.error(f"初稿生成节点失败: {e}")
        return {"draft_content": f"生成失败: {str(e)}"}


async def node_optimize_draft(state: ResumeGenerationState) -> dict:
    """
    初稿优化节点（新增）：检查信息遗漏并按多维度优化
    """
    resume_content = state.get("resume_content", "")
    draft_content = state.get("draft_content", "")
    job_description = state.get("job_description", "")
    user_answers = state.get("user_answers", {})
    api_config = state.get("api_config")

    user_inputs = json.dumps(user_answers, ensure_ascii=False) if user_answers else "无"

    # 获取优化建议
    optimization_result = state.get("optimization_result") or {}
    key_improvements = optimization_result.get('key_improvements', [])
    keyword_analysis = optimization_result.get('keyword_analysis', {})
    jd_keywords = keyword_analysis.get('jd_keywords', [])
    missing_keywords = keyword_analysis.get('missing', [])

    prompt = f"""你是一位「简历质量优化专家」。请对比【原始资料】和【初稿】，进行深度优化。

## 输入信息

【原始简历】：
{resume_content}

【用户补充信息】：
{user_inputs}

【目标职位】：
{job_description}

【当前初稿】：
{draft_content}

---

## 必须执行的优化建议

【关键改进点】（来自专家分析，必须落实）：
{json.dumps(key_improvements[:5], ensure_ascii=False, indent=2)}

【关键词要求】：
- JD核心关键词：{json.dumps(jd_keywords[:10], ensure_ascii=False)}
- 缺失的关键词（必须补充）：{json.dumps(missing_keywords[:8], ensure_ascii=False)}

---

## 优化任务

### 1. 信息完整性检查
对比【原始简历】和【当前初稿】：
- 关键工作经历是否被遗漏？→ 必须保留核心经历
- 重要项目是否被遗漏？→ 必须保留有价值的项目
- 项目日期是否准确？→ 必须与原简历一致

### 2. 精炼度优化（重点！）
**简历要精炼有力，每个要点都要有信息量**：
- 个人简介：控制在2-3句话，抓住核心竞争力和与岗位匹配度
- 工作/项目经历：每段2-4个最有价值的要点，删除空洞描述
- 专业技能：精简为与JD最相关的核心技能，避免罗列过多

### 3. 自我介绍优化（关键！）
个人简介必须做到：
- **精炼**：控制在2-3句话，不超过100字
- **聚焦**：只突出①核心技术优势 ②最突出成果 ③与岗位匹配度
- **有信息量**：每句话都有实质内容，删除"努力"、"热爱"等空洞描述

### 4. 关键词融入
检查【缺失的关键词】是否已自然地融入简历中：
- 在工作职责、项目描述、技能列表中体现
- 确保关键词覆盖率达到80%以上

### 5. 量化与成果
- 保留有说服力的量化成果
- 删除模糊的、没有信息量的描述

### 6. 关键改进点落实检查
逐条检查【关键改进点】是否已在简历中体现，未体现的必须补充。

---

## 输出要求

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "optimized_content": "优化后的完整 Markdown 简历（精炼有力）...",
    "optimization_summary": {{
        "missing_info_fixed": ["补充了XX项目经历", "保留了关键信息..."],
        "content_refined": ["精简了冗余描述", "优化了个人简介..."],
        "skills_focused": ["聚焦核心技能", "突出JD匹配技能..."],
        "keywords_added": ["融入了关键词XX", "补充了技能关键词XX..."],
        "improvements_applied": ["落实了改进点1", "落实了改进点2..."]
    }},
    "quality_scores": {{
        "completeness": 85,
        "conciseness": 85,
        "focus": 90,
        "keyword_coverage": 90,
        "jd_match": 82
    }}
}}

重要提醒：
- optimized_content 必须是完整的 Markdown 简历，禁止使用emoji表情
- **精炼优先**：删除空洞描述，每个要点都要有信息量
- **个人简介必须精炼**：2-3句话抓住重点，切忌冗长
- **关键词和改进点必须落实**
"""

    try:
        result = await invoke_structured(prompt, DraftOptimizationOutput, api_config, channel="content_writer")
        optimized_draft = clean_markdown_response(result.optimized_content)
        optimization_summary = result.optimization_summary.model_dump()
        quality_scores = result.quality_scores.model_dump()

        logger.info(f"初稿优化完成: 补充了 {len(optimization_summary.get('missing_info_fixed', []))} 项遗漏, 长度 {len(optimized_draft)} 字符, 质量评分 completeness={quality_scores.get('completeness', 'N/A')}")

        return {
            "optimized_draft": optimized_draft,
            "optimization_notes": {
                "summary": optimization_summary,
                "scores": quality_scores
            }
        }
    except Exception as e:
        logger.error(f"初稿优化节点失败: {e}")
        # 失败时使用原初稿
        return {
            "optimized_draft": draft_content,
            "optimization_notes": {"error": str(e)}
        }


async def node_fact_check(state: ResumeGenerationState) -> dict:
    """
    包装适度性核查节点：区分"适度包装"和"过度造假"
    """
    resume_content = state.get("resume_content", "")
    # 使用优化后的初稿进行核查
    draft_content = state.get("optimized_draft", "") or state.get("draft_content", "")
    user_answers = state.get("user_answers", {})
    api_config = state.get("api_config")

    user_inputs = json.dumps(user_answers, ensure_ascii=False) if user_answers else "无"

    prompt = f"""你是一位「简历风控专家」。请对比【原始资料】和【生成简历】，检查是否存在**过度包装或恶意造假**。

【判定标准】：
- 🟢 **安全（适度包装）**：语言润色、合理的推断、基于行业标准估算的数据、突显亮点。 -> **无需报告**
- 🔴 **危险（恶意造假）**：
    1. 编造不存在的公司或已确认不存在的职位。
    2. 编造候选人显然不具备的核心硬技能（如文员编造会写操作系统内核）。
    3. 数据极度夸张、违反常理（如实习生独立带来上亿营收）。

【原始资料】：
{resume_content}
用户补充: {user_inputs}

【生成简历】：
{draft_content}

---

请只报告🔴**危险**级别的造假。如果只是🟢适度包装（包括基于经验的合理推断、语言上的专业化润色），请务必**放行**（is_excessive=false）。

**只有在确实出现"无中生有"的核心硬技能或经历时，才标记为过度造假。**

请输出 JSON 格式（不要使用 markdown 代码块、注意 JSON 结构涉及的标点必须是英文）：
{{
    "is_excessive": true/false,  // 是否过度造假
    "risk_details": [
        {{
            "type": "excessive_fabrication",
            "location": "具体位置（如：工作经历-XX公司、项目经历-XX项目、专业技能等）",
            "original": "原始简历中的相关内容（如无则填'无相关描述'）",
            "fabricated": "生成简历中被造假/过度夸大的具体内容",
            "reason": "判定为造假的理由（如：原简历无此技能、数据违反常理等）"
        }}
    ]
}}
"""

    try:
        result = await invoke_structured(prompt, FactCheckOutput, api_config, channel="general")
        result = result.model_dump()
        is_excessive = result.get("is_excessive", False)
        logger.info(f"风控核查完成: is_excessive={is_excessive}")
        return {"fact_check_result": result}
    except Exception as e:
        logger.error(f"风控核查节点失败: {e}")
        return {"fact_check_result": {"is_excessive": False, "risk_details": []}}


async def node_finalize_and_review(state: ResumeGenerationState) -> dict:
    """
    润色与审查节点：基于适度包装原则进行最终确认
    """
    # 使用优化后的初稿
    draft_content = state.get("optimized_draft", "") or state.get("draft_content", "")
    fact_check_result = state.get("fact_check_result") or {}
    optimization_result = state.get("optimization_result") or {}
    api_config = state.get("api_config")

    # 获取 JD 关键词
    jd_keywords = optimization_result.get("keyword_analysis", {}).get("jd_keywords", [])[:10]

    # 构建警告
    warning = ""
    if fact_check_result.get("is_excessive"):
        details = fact_check_result.get("risk_details", [])
        # 构建更清晰的修正指导
        fix_instructions = []
        for i, detail in enumerate(details, 1):
            location = detail.get("location", "未知位置")
            original = detail.get("original", "无相关描述")
            fabricated = detail.get("fabricated", "未知内容")
            reason = detail.get("reason", "未说明")
            fix_instructions.append(
                f"  {i}. 【{location}】\n"
                f"     - 原始内容：{original}\n"
                f"     - 造假内容：{fabricated}\n"
                f"     - 造假原因：{reason}"
            )

        warning = f"""
**风控警告：检测到过度造假，必须修正以下内容**：

{chr(10).join(fix_instructions)}

**修正原则**：
- 对于【造假内容】部分，请根据【原始内容】进行修正或弱化表述
- 将"过于夸张的数据"修改为"合理估算的数据"
- 将"无中生有"的技能修改为"了解/熟悉"或删除该具体技能点（保留其他真实技能）
- **不要删除整段经历，也不要大幅缩减简历篇幅**
"""

    prompt = f"""你是一位「简历终审专家」。请对以下简历进行最终润色。

【简历草稿】：
{draft_content}

【目标职位关键词】：
{json.dumps(jd_keywords, ensure_ascii=False)}

{warning}

请执行以下任务：
1. **修正过度造假**：如果有风控警告，必须修正。
2. **润色语言**：让措辞更加专业、自信（允许适度包装）。
3. **格式检查**：确保 Markdown 格式标准、美观。
4. **长度保持**：**严禁大幅删减内容！** 修正后的简历长度应与草稿基本保持一致（允许+/- 10%波动）。如果不涉及造假的部分，请原样保留或仅做润色。
5. **最终打磨**：确保简历读起来流畅、专业。

请输出 JSON 格式（不要使用 markdown 代码块，注意 JSON 结构涉及的标点必须是英文）：
{{
    "final_content": "最终修订后的完整 Markdown 简历...",
    "review_passed": true/false,
    "modification_notes": ["修正了严重夸大的数据", "优化了项目描述..."],
    "title": "姓名-目标职位"
}}
注意：
- optimized_content 必须是完整的 Markdown 简历，禁止使用emoji表情
- 内容要丰富，不要写得太简洁！每个模块都要有实质内容
- 专业技能要详细，体现深度和与岗位的匹配
- 禁止使用emoji表情
- 禁止修改项目日期
"""

    try:
        result = await invoke_structured(prompt, FinalReviewOutput, api_config, channel="hr_reviewer")
        final_markdown = clean_markdown_response(result.final_content)
        passed = result.review_passed
        title = result.title

        logger.info(f"润色审查完成: passed={passed}")

        return {
            "final_markdown": final_markdown,
            "review_result": {
                "passed": passed,
                "issues": fact_check_result.get("risk_details", [])
            },
            "title": title
        }
    except Exception as e:
        logger.error(f"润色审查节点失败: {e}")
        return {
            "final_markdown": draft_content,
            "review_result": {"passed": True, "error": str(e)},
            "title": "新简历"
        }


# ============================================================================
# 辅助函数
# ============================================================================

def route_after_review(state: ResumeGenerationState) -> str:
    """审查后的路由：决定是循环还是结束"""
    review_result = state.get("review_result") or {}
    iteration_count = state.get("iteration_count", 0)

    # 如果审查通过或达到最大迭代次数，结束
    if review_result.get("passed", False) or iteration_count >= 2:
        return END

    # 否则循环回初稿生成
    return "generate_draft"


async def node_increment_iteration(state: ResumeGenerationState) -> dict:
    """增加迭代计数"""
    return {"iteration_count": state.get("iteration_count", 0) + 1}


def build_resume_generation_graph():
    """构建简历生成 StateGraph"""
    workflow = StateGraph(ResumeGenerationState)

    # 添加节点
    workflow.add_node("generate_draft", node_generate_draft)
    workflow.add_node("optimize_draft", node_optimize_draft)
    workflow.add_node("fact_check", node_fact_check)
    workflow.add_node("finalize_review", node_finalize_and_review)
    workflow.add_node("increment_iteration", node_increment_iteration)

    # 设置入口
    workflow.set_entry_point("generate_draft")

    # 线性流程
    workflow.add_edge("generate_draft", "optimize_draft")
    workflow.add_edge("optimize_draft", "fact_check")
    workflow.add_edge("fact_check", "finalize_review")

    # 条件路由：审查后决定是否循环
    workflow.add_conditional_edges(
        "finalize_review",
        route_after_review,
        {
            END: END,
            "generate_draft": "increment_iteration"
        }
    )

    # 迭代计数后回到初稿生成
    workflow.add_edge("increment_iteration", "generate_draft")

    return workflow.compile()

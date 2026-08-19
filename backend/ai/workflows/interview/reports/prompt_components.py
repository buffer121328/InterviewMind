"""深度与标准报告共用的事实边界、评价维度和叙事约束。"""

from __future__ import annotations

REPORT_FACT_CONSTRAINTS = """
事实边界：
- 仅根据已提供的简历、JD、公司信息和带 [Qn] 引用的问答来源作出判断。
- 不得补造候选人经历、项目指标、技术实现、岗位要求或面试表现。
- 每一项优势、风险、评分理由和建议必须可追溯到 [Qn] 或明确标为“缺少证据”。
- 遇到来源表示为 derived_ir 时，保留来源编号、覆盖统计和缺失信号，不得把摘要外的信息当作事实。
""".strip()

REPORT_EVALUATION_DIMENSIONS = (
    "专业能力、执行与结果导向、逻辑与问题解决、沟通表达力、成长潜力、协作能力"
)


def build_standard_report_prompt(*, prepared_source: str) -> str:
    """构建标准报告的单模型结构化叙事提示，不改变深度报告的 reviewer prompt。"""

    return f"""
你是一名严谨的面试评估专家。请生成一份单场标准面试报告，并返回符合 SessionInterviewReportOutput 的 JSON。

{REPORT_FACT_CONSTRAINTS}

评价维度：{REPORT_EVALUATION_DIMENSIONS}。
输出必须同时给出候选人画像、短板地图和逐题证据；逐题证据使用稳定的 [Qn] 题号。
对没有充分来源的维度或结论，明确写入缺少的证据，而不是猜测。

以下是已经完成来源覆盖检查的报告输入：
{prepared_source}
""".strip()

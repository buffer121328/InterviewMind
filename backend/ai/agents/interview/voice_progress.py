"""Progress inference for voice interview conversations."""

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def calculate_interview_progress(history: List[Dict[str, Any]], plan: List[Dict[str, Any]], initial_q_idx: int = 0) -> Dict[str, Any]:
    """通过分析历史对话，推断当前的面试进度。"""
    current_q_idx = initial_q_idx
    follow_up_count = 0
    last_q_text = ""
    last_planned_q_found = False

    if not plan:
        return {"current_q_idx": 0, "follow_up_count": 0, "last_q_text": "", "is_complete": False}

    def is_match(ai_content: str, q_topic: str, q_content: str, q_idx: int) -> bool:
        """多维度匹配逻辑。"""
        clean_ai = re.sub(r"[^\w\u4e00-\u9fa5]", "", ai_content)

        chinese_nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        num_patterns = [
            f"第{q_idx+1}[个题问话]",
            f"第{q_idx+1}阶段",
            f"^({q_idx+1}[.、])",
            f"({q_idx+1}[.、])",
        ]
        if q_idx < len(chinese_nums):
            num_patterns.append(f"第{chinese_nums[q_idx]}[个题问话]")
            num_patterns.append(f"第{chinese_nums[q_idx]}阶段")

        if q_idx == len(plan) - 1:
            num_patterns.append("最后一题")
            num_patterns.append("最后一个问题")
            num_patterns.append("结束面试")

        if any(re.search(pattern, ai_content) for pattern in num_patterns):
            return True

        if q_topic:
            clean_topic = re.sub(r"[^\w\u4e00-\u9fa5]", "", q_topic)
            if len(clean_topic) >= 2:
                common_filters = ["项目", "经验", "技术", "基础", "了解", "面试", "问题"]
                if clean_topic in clean_ai:
                    if len(clean_topic) <= 2 and clean_topic in common_filters:
                        if re.search(rf"第[一二三四五六七八九十\d][个环节题问话].*{clean_topic}", ai_content) or f"关于{clean_topic}" in ai_content:
                            return True
                    else:
                        return True

        core_text = re.sub(r"[^\w\u4e00-\u9fa5]", "", q_content[:40])
        if len(core_text) >= 12:
            for index in range(len(core_text) - 9):
                if core_text[index:index + 10] in clean_ai:
                    return True
        elif core_text and len(core_text) > 4 and core_text in clean_ai:
            return True

        return False

    for msg in history:
        if msg.get("role") == "assistant":
            content = msg.get("content", "").strip()
            if not content:
                continue

            found_next = False
            for index in range(current_q_idx + 1, len(plan)):
                planned = plan[index]
                if is_match(content, planned.get("topic", ""), planned.get("content", ""), index):
                    current_q_idx = index
                    follow_up_count = 0
                    last_q_text = planned.get("content", "")
                    last_planned_q_found = True
                    found_next = True
                    logger.debug("[Progress] 匹配到新题目索引: %s", index)
                    break

            if not found_next:
                current_plan = plan[current_q_idx]
                if is_match(content, current_plan.get("topic", ""), current_plan.get("content", ""), current_q_idx):
                    if not last_planned_q_found:
                        last_planned_q_found = True
                        last_q_text = current_plan.get("content", "")
                    else:
                        follow_up_count += 1
                        last_q_text = content
                elif last_planned_q_found and len(content) > 10:
                    follow_up_count += 1
                    last_q_text = content

    is_complete = False
    last_ai_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_ai_msg = msg.get("content", "").lower()
            break

    if current_q_idx >= len(plan) - 1:
        closing_keywords = ["面试结束", "再见", "谢谢你的参加", "祝你生活愉快", "今天的面试就到这里", "辛苦了", "拜拜", "期待你的加入"]
        if any(keyword in last_ai_msg for keyword in closing_keywords):
            is_complete = True
        elif follow_up_count >= 3:
            is_complete = True

    return {
        "current_q_idx": current_q_idx,
        "follow_up_count": follow_up_count,
        "last_q_text": last_q_text,
        "is_complete": is_complete,
    }

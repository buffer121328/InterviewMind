"""
岗位去重检测

基于 source_hash 进行精确去重，
基于公司名+岗位名模糊匹配进行相似岗位检测。
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


async def is_duplicate(source_hash: str, user_id: str) -> bool:
    """
    检查是否为重复岗位（基于 source_hash 精确匹配）。

    Args:
        source_hash: 岗位的 source_hash
        user_id: 用户 ID

    Returns:
        True 如果已存在重复岗位
    """
    try:
        from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
        repo = get_job_capture_repo()
        existing = await repo.find_by_hash(source_hash, user_id)
        return existing is not None
    except Exception as e:
        logger.warning(f"[Deduper] 去重查询失败: {e}")
        return False


async def find_similar_jobs(
    company_name: str,
    job_title: str,
    user_id: str,
    threshold: float = 0.8,
) -> List[Dict[str, Any]]:
    """
    查找相似岗位（同公司、同岗位名称的模糊匹配）。

    Args:
        company_name: 公司名
        job_title: 岗位名
        user_id: 用户 ID
        threshold: 相似度阈值

    Returns:
        相似岗位列表
    """
    try:
        from app.db.repositories.jobs.job_capture_repo import get_job_capture_repo
        repo = get_job_capture_repo()

        # 按公司名搜索
        all_jobs = await repo.list_jobs(user_id, limit=100)

        similar = []
        for job in all_jobs:
            sim = _calculate_similarity(
                company_name, job_title,
                job.get("company_name", ""), job.get("job_title", "")
            )
            if sim >= threshold:
                similar.append({**job, "similarity": round(sim, 2)})

        return similar
    except Exception as e:
        logger.warning(f"[Deduper] 相似岗位查询失败: {e}")
        return []


def _calculate_similarity(
    company1: str, title1: str,
    company2: str, title2: str,
) -> float:
    """
    计算两个岗位的相似度。

    策略：公司名匹配 60% 权重 + 岗位名匹配 40% 权重。
    """
    score = 0.0

    # 公司名匹配（60%）
    if company1 and company2:
        c1 = company1.lower().strip()
        c2 = company2.lower().strip()
        if c1 == c2:
            score += 0.6
        elif c1 in c2 or c2 in c1:
            score += 0.4
        else:
            # 计算共同字符比例
            common = len(set(c1) & set(c2))
            max_len = max(len(c1), len(c2))
            if max_len > 0:
                score += 0.2 * (common / max_len)

    # 岗位名匹配（40%）
    if title1 and title2:
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        if t1 == t2:
            score += 0.4
        elif t1 in t2 or t2 in t1:
            score += 0.3
        else:
            words1 = set(t1.split())
            words2 = set(t2.split())
            if words1 and words2:
                overlap = len(words1 & words2)
                union = len(words1 | words2)
                score += 0.2 * (overlap / union)

    return min(score, 1.0)

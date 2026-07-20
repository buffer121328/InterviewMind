"""
简历用户确认服务

管理高风险改写项的用户确认流程：
1. 识别需要确认的改写项
2. 展示改写对比供用户审核
3. 记录确认/拒绝操作
4. 确认后保存最终版本 + 审计日志
"""

import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================================
# 审计日志
# ============================================================================

@dataclass
class AuditEntry:
    """审计日志条目"""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    action: str = ""  # confirmed / rejected / modified / saved
    section_name: str = ""
    original_text: str = ""
    optimized_text: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# 确认服务
# ============================================================================

class ResumeConfirmationService:
    """简历用户确认服务
    
    管理高风险改写的确认流程和最终保存。
    """
    
    def __init__(self, user_id: str = "default_user"):
        self.user_id = user_id
        self._audit_log: List[AuditEntry] = []
        self._pending_items: List[Dict[str, Any]] = []
        self._confirmed_items: List[Dict[str, Any]] = []
        self._rejected_items: List[Dict[str, Any]] = []
    
    def load_pending_items(self, change_items: List[Dict[str, Any]]):
        """加载需要确认的改写项"""
        self._pending_items = []
        for item in change_items:
            if self._requires_confirmation(item):
                self._pending_items.append({
                    "item_id": str(uuid.uuid4()),
                    "section_name": item.get("section_name", ""),
                    "change_type": item.get("change_type", ""),
                    "original_text": item.get("original_text", ""),
                    "optimized_text": item.get("optimized_text", ""),
                    "reason": item.get("reason", ""),
                    "evidence_source": item.get("evidence_source", ""),
                    "confidence": item.get("confidence", 0.8),
                    "status": "pending",
                })
        
        logger.info(
            f"[Confirmation] 加载 {len(self._pending_items)} 条待确认项 "
            f"(共 {len(change_items)} 条改写)"
        )
    
    def get_pending_items(self) -> List[Dict[str, Any]]:
        """获取待确认项列表（供前端展示）"""
        return self._pending_items
    
    def confirm_item(self, item_id: str) -> bool:
        """确认单个改写项"""
        for item in self._pending_items:
            if item["item_id"] == item_id:
                item["status"] = "confirmed"
                self._confirmed_items.append(item)
                self._pending_items.remove(item)
                
                self._log_audit(
                    action="confirmed",
                    section_name=item["section_name"],
                    original_text=item.get("original_text", ""),
                    optimized_text=item.get("optimized_text", ""),
                )
                return True
        return False
    
    def reject_item(self, item_id: str) -> bool:
        """拒绝单个改写项"""
        for item in self._pending_items:
            if item["item_id"] == item_id:
                item["status"] = "rejected"
                self._rejected_items.append(item)
                self._pending_items.remove(item)
                
                self._log_audit(
                    action="rejected",
                    section_name=item["section_name"],
                    original_text=item.get("original_text", ""),
                    optimized_text=item.get("optimized_text", ""),
                )
                return True
        return False
    
    def confirm_all(self) -> int:
        """一键确认所有待确认项"""
        count = 0
        for item in list(self._pending_items):
            if self.confirm_item(item["item_id"]):
                count += 1
        return count
    
    def reject_all(self) -> int:
        """一键拒绝所有待确认项"""
        count = 0
        for item in list(self._pending_items):
            if self.reject_item(item["item_id"]):
                count += 1
        return count
    
    def has_pending(self) -> bool:
        """是否还有待确认项"""
        return len(self._pending_items) > 0
    
    async def save_final_resume(
        self,
        assembled_resume: str,
        job_description: str = "",
        title: str = "优化简历",
    ) -> Optional[str]:
        """
        保存最终版简历（确认后调用）。
        
        Returns:
            保存的 resume_id，如果还有待确认项返回 None
        """
        if self.has_pending():
            logger.warning(f"[Confirmation] 还有 {len(self._pending_items)} 条未确认，不允许保存")
            return None
        
        try:
            from app.infrastructure.db.repositories.resume.resume_generation_repo import get_generation_repo
            
            repo = get_generation_repo()
            resume_id = await repo.save_generated_resume(
                user_id=self.user_id,
                title=title,
                content=assembled_resume,
                job_description=job_description,
            )
            
            # 记录保存审计日志
            self._log_audit(
                action="saved",
                section_name="final_resume",
                original_text="",
                optimized_text=f"resume_id={resume_id}, confirmed={len(self._confirmed_items)}, rejected={len(self._rejected_items)}",
            )
            
            logger.info(
                f"[Confirmation] 最终简历已保存: resume_id={resume_id}, "
                f"confirmed={len(self._confirmed_items)}, rejected={len(self._rejected_items)}"
            )
            
            return resume_id
            
        except Exception as e:
            logger.error(f"[Confirmation] 保存最终简历失败: {e}")
            return None
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """获取审计日志"""
        return [
            {
                "entry_id": entry.entry_id,
                "user_id": entry.user_id,
                "action": entry.action,
                "section_name": entry.section_name,
                "timestamp": entry.timestamp,
            }
            for entry in self._audit_log
        ]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取确认状态摘要"""
        return {
            "total_pending": len(self._pending_items),
            "total_confirmed": len(self._confirmed_items),
            "total_rejected": len(self._rejected_items),
            "can_save": not self.has_pending(),
            "audit_entries": len(self._audit_log),
        }
    
    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    
    @staticmethod
    def _requires_confirmation(item: Dict[str, Any]) -> bool:
        """判断改写项是否需要用户确认"""
        return (
            item.get("requires_user_confirmation", False)
            or item.get("change_type") == "fact_inference"
        )
    
    def _log_audit(
        self,
        action: str,
        section_name: str = "",
        original_text: str = "",
        optimized_text: str = "",
    ):
        """记录审计日志"""
        entry = AuditEntry(
            user_id=self.user_id,
            action=action,
            section_name=section_name,
            original_text=original_text[:200],
            optimized_text=optimized_text[:200],
        )
        self._audit_log.append(entry)
        logger.debug(f"[Confirmation] 审计: {action} - {section_name}")

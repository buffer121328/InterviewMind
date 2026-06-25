"""
记忆相关的数据结构定义

用于 API 响应和内部数据传递。
"""

from typing import Optional
from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    """单条记忆"""
    id: str = Field(description="记忆 ID")
    memory: str = Field(description="记忆内容")
    metadata: dict = Field(default_factory=dict, description="元数据")
    score: Optional[float] = Field(default=None, description="相关性分数")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")


class MemorySearchResponse(BaseModel):
    """记忆搜索响应"""
    success: bool = Field(description="是否成功")
    memories: list[MemoryItem] = Field(default_factory=list, description="记忆列表")
    query: str = Field(description="搜索查询")
    total: int = Field(default=0, description="结果总数")


class MemoryListResponse(BaseModel):
    """记忆列表响应"""
    success: bool = Field(description="是否成功")
    memories: list[MemoryItem] = Field(default_factory=list, description="记忆列表")
    total: int = Field(default=0, description="结果总数")
    user_id: str = Field(description="用户 ID")


class MemoryHistoryItem(BaseModel):
    """记忆历史条目"""
    id: str = Field(description="历史记录 ID")
    memory_id: str = Field(description="记忆 ID")
    event: str = Field(description="事件类型: ADD, UPDATE, DELETE")
    old_memory: Optional[str] = Field(default=None, description="旧记忆内容")
    new_memory: Optional[str] = Field(default=None, description="新记忆内容")
    created_at: Optional[str] = Field(default=None, description="事件时间")


class MemoryHistoryResponse(BaseModel):
    """记忆历史响应"""
    success: bool = Field(description="是否成功")
    history: list[MemoryHistoryItem] = Field(default_factory=list, description="历史记录")
    memory_id: str = Field(description="记忆 ID")


class MemoryDeleteResponse(BaseModel):
    """记忆删除响应"""
    success: bool = Field(description="是否成功")
    message: str = Field(description="提示消息")
    memory_id: Optional[str] = Field(default=None, description="删除的记忆 ID")


class MemoryDeleteAllRequest(BaseModel):
    """清空全部记忆请求"""
    confirm: bool = Field(description="必须为 true 才执行删除")


class MemoryContext(BaseModel):
    """记忆上下文（注入到 prompt）"""
    context: str = Field(description="格式化后的记忆上下文")
    items: list[MemoryItem] = Field(default_factory=list, description="原始记忆列表")
    has_memories: bool = Field(default=False, description="是否有记忆")

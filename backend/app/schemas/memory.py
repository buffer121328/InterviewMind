"""
记忆相关的数据结构定义

用于 API 响应和内部数据传递。
"""

from typing import Optional
from pydantic import BaseModel, Field

from app.domain.memory import MemorySource, MemoryWriteSource
from app.schemas.schemas import ModelChannelConfig


class MemoryApiConfig(BaseModel):
    """mem0/RAG 记忆相关通道的模型配置集合。"""

    mem0_llm: Optional[ModelChannelConfig] = Field(default=None, description="mem0 记忆提取 LLM 通道")
    mem0_embedder: Optional[ModelChannelConfig] = Field(default=None, description="mem0 语义检索 Embedding 通道")
    rag_embedding: Optional[ModelChannelConfig] = Field(default=None, description="RAG 向量检索 Embedding 通道")


class MemoryAccessRequest(BaseModel):
    """记忆访问请求的公共基类，携带可选模型通道配置。"""

    api_config: Optional[MemoryApiConfig] = Field(
        default=None,
        description="前端模型设置中的 mem0 LLM/Embedding 通道",
    )


class MemoryListRequest(MemoryAccessRequest):
    """带来源过滤的记忆列表请求。"""

    page_size: int = Field(default=100, ge=1, le=1000, description="每页条数")
    sources: list[MemorySource] | None = Field(default=None, max_length=4, description="要过滤的记忆来源列表")


class MemorySearchRequest(MemoryAccessRequest):
    """带来源过滤的记忆搜索请求。"""

    query: str = Field(min_length=1, max_length=500, description="搜索关键词")
    limit: int = Field(default=5, ge=1, le=20, description="返回的最大条数")
    memory_type: Optional[str] = Field(default=None, max_length=100, description="记忆类型过滤")
    sources: list[MemorySource] | None = Field(default=None, max_length=4, description="要过滤的记忆来源列表")


class MemoryCreateRequest(MemoryAccessRequest):
    """新增一条记忆的请求。"""

    content: str = Field(min_length=1, max_length=2000, description="记忆内容")
    memory_type: Optional[str] = Field(default=None, max_length=100, description="记忆类型")
    memory_source: MemoryWriteSource | None = Field(default=None, description="记忆来源")


class MemoryUpdateRequest(MemoryAccessRequest):
    """更新一条记忆内容的请求。"""

    content: str = Field(min_length=1, max_length=2000, description="更新后的记忆内容")


class MemoryItem(BaseModel):
    """单条记忆"""
    id: str = Field(description="记忆 ID")
    memory: str = Field(description="记忆内容")
    metadata: dict = Field(default_factory=dict, description="元数据")
    source: MemorySource = Field(default=MemorySource.UNKNOWN, description="公开来源分类")
    score: Optional[float] = Field(default=None, description="相关性分数")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")


class MemorySearchResponse(BaseModel):
    """记忆搜索响应"""
    success: bool = Field(description="是否成功")
    memories: list[MemoryItem] = Field(default_factory=list, description="记忆列表")
    query: str = Field(description="搜索查询")
    total: int = Field(default=0, description="结果总数")
    message: Optional[str] = Field(default=None, description="服务不可用时的安全提示")


class MemoryListResponse(BaseModel):
    """记忆列表响应"""
    success: bool = Field(description="是否成功")
    memories: list[MemoryItem] = Field(default_factory=list, description="记忆列表")
    total: int = Field(default=0, description="结果总数")
    user_id: str = Field(description="用户 ID")
    message: Optional[str] = Field(default=None, description="服务不可用时的安全提示")


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
    message: Optional[str] = Field(default=None, description="服务不可用时的安全提示")


class MemoryDeleteResponse(BaseModel):
    """记忆删除响应"""
    success: bool = Field(description="是否成功")
    message: str = Field(description="提示消息")
    memory_id: Optional[str] = Field(default=None, description="删除的记忆 ID")


class MemoryWriteResponse(BaseModel):
    """记忆写入操作的统一响应。"""

    success: bool = Field(description="是否成功")
    message: str = Field(description="提示消息")
    memory_id: Optional[str] = Field(default=None, description="写入的记忆 ID")


class MemoryDeleteAllRequest(MemoryAccessRequest):
    """清空全部记忆请求"""
    confirm: bool = Field(description="必须为 true 才执行删除")


class MemoryConsolidateRequest(MemoryAccessRequest):
    """记忆整合（去重合并）请求。"""

    dry_run: bool = Field(default=True, description="true 时只生成整合预览，不修改数据")
    confirm: bool = Field(default=False, description="实际执行时必须显式设为 true")
    max_memories: int = Field(default=200, ge=1, le=500, description="参与整合的最大记忆条数")


class MemoryConsolidationOperation(BaseModel):
    """记忆整合中的单条操作。"""

    memory_id: str = Field(description="操作涉及的记忆 ID")
    action: str = Field(description="操作类型：MERGE/REMOVE 等")
    confidence: float = Field(ge=0, le=1, description="操作置信度（0-1）")
    reason: str = Field(max_length=240, description="操作原因说明")


class MemoryConsolidationResponse(BaseModel):
    """记忆整合结果响应。"""

    success: bool = Field(description="是否成功")
    dry_run: bool = Field(description="是否为预览模式")
    total_before: int = Field(ge=0, description="整合前的记忆总数")
    total_after: int = Field(ge=0, description="整合后的记忆总数")
    counts: dict[str, int] = Field(default_factory=dict, description="各操作类型计数")
    applied_counts: dict[str, int] = Field(default_factory=dict, description="已实际应用的操作计数")
    operations: list[MemoryConsolidationOperation] = Field(default_factory=list, description="整合操作列表")
    message: Optional[str] = Field(default=None, description="附加提示消息")


class MemoryCleanupRequest(MemoryAccessRequest):
    """记忆清理（标记保留/删除）请求。"""

    dry_run: bool = Field(default=True, description="true 时只预览 KEEP/MARK/DELETE")
    confirm: bool = Field(default=False, description="应用 MARK/DELETE 前必须显式为 true")
    max_memories: int = Field(default=500, ge=1, le=1000, description="参与清理的最大记忆条数")


class MemoryCleanupOperation(BaseModel):
    """记忆清理中的单条操作。"""

    memory_id: str = Field(description="操作涉及的记忆 ID")
    action: str = Field(description="操作类型：KEEP/MARK/DELETE")
    retention_class: str = Field(description="留存分类（如 keep/delete/candidate）")
    reason: str = Field(max_length=240, description="操作原因说明")
    candidate_since: Optional[str] = Field(default=None, description="成为清理候选的时间")


class MemoryCleanupResponse(BaseModel):
    """记忆清理结果响应。"""

    success: bool = Field(description="是否成功")
    dry_run: bool = Field(description="是否为预览模式")
    total_before: int = Field(ge=0, description="清理前的记忆总数")
    total_after: int = Field(ge=0, description="清理后的记忆总数")
    counts: dict[str, int] = Field(default_factory=dict, description="各操作类型计数")
    applied_counts: dict[str, int] = Field(default_factory=dict, description="已实际应用的操作计数")
    operations: list[MemoryCleanupOperation] = Field(default_factory=list, description="清理操作列表")
    message: Optional[str] = Field(default=None, description="附加提示消息")


class MemoryContext(BaseModel):
    """记忆上下文（注入到 prompt）"""
    context: str = Field(description="格式化后的记忆上下文")
    items: list[MemoryItem] = Field(default_factory=list, description="原始记忆列表")
    has_memories: bool = Field(default=False, description="是否有记忆")

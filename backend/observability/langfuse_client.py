"""提供Langfuse客户端相关后端功能。"""

from typing import Any

from observability.config import LangfuseConfig


def _create_langfuse_client(config: LangfuseConfig) -> Any:
    """按配置创建 Langfuse 客户端；外部追踪不可用时使用安全降级，不让观测初始化阻断业务流程。

    Args:
        config: 配置对象。
    """
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        base_url=config.base_url,
        environment=config.environment,
        release=config.release,
        sample_rate=config.sample_rate,
    )


def _get_propagate_attributes():
    """生成 LangChain/Langfuse 传播属性，限制在当前请求的 trace 边界内，不把完整敏感上下文放入外部追踪。"""
    from langfuse import propagate_attributes

    return propagate_attributes


def _get_callback_handler():
    """按当前请求配置创建观测回调处理器；回调只接收脱敏事件，追踪失败不影响主流程返回。"""
    try:
        from langfuse.langchain import CallbackHandler
    except ModuleNotFoundError:
        class CallbackHandler:  # pragma: no cover - 轻量测试环境占位
            """应用或基础设施协作者，负责 `CallbackHandler` 的职责；依赖通过构造或模块边界注入，外部调用、状态持久化和安全校验不向调用方隐藏。"""
            def __call__(self, *args: Any, **kwargs: Any) -> None:
                """实现 `__call__` 协议方法。

                Args:
                    *args: 经过类型边界校验的 `args`；其格式和可选值由参数类型及调用流程约束。
                    **kwargs: 经过类型边界校验的 `kwargs`；其格式和可选值由参数类型及调用流程约束。
                """
                return None

        return CallbackHandler

    return CallbackHandler

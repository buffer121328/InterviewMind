"""模型供应商构造器注册表。"""

from collections.abc import Callable
from threading import RLock
from typing import Any

ModelFactory = Callable[..., Any]


class ModelProviderRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化 `ModelProviderRegistry` 的依赖和运行配置；构造阶段不执行业务写入，外部客户端只在后续方法调用时承担访问边界。"""
        self._factories: dict[str, ModelFactory] = {}
        self._lock = RLock()

    def register(self, name: str, factory: ModelFactory, *, replace: bool = False) -> None:
        """注册可供运行时发现的声明，拒绝重复或不完整定义，保持模块加载顺序不会改变最终契约。

        Args:
            name: 名称。
            factory: 工厂函数或对象。
            replace: 经过类型边界校验的 `replace`；其格式和可选值由参数类型及调用流程约束。
        """
        key = name.strip().lower()
        if not key:
            raise ValueError("provider name must not be empty")
        with self._lock:
            if key in self._factories and not replace:
                raise ValueError(f"model provider already registered: {key}")
            self._factories[key] = factory

    def create(self, name: str, **config: Any) -> Any:
        """创建当前服务声明的资源或运行对象；由所属仓储/注册表负责校验重复、owner 和持久化边界。

        Args:
            name: 名称。
            **config: 配置对象。
        """
        key = name.strip().lower()
        try:
            factory = self._factories[key]
        except KeyError as exc:
            raise KeyError(f"unknown model provider: {key}") from exc
        return factory(**config)

    def names(self) -> tuple[str, ...]:
        """返回注册表中稳定排序的名称列表，供诊断和管理接口使用。"""
        return tuple(sorted(self._factories))


model_provider_registry = ModelProviderRegistry()


def _create_openai_compatible(**config: Any) -> Any:
    # 懒加载可避免启动阶段初始化模型 SDK，也保留旧接口的兼容性。
    """根据模型 profile 创建 OpenAI-compatible 客户端，应用 URL、超时和凭据注入边界；不把凭据写入日志。

    Args:
        **config: 配置对象。
    """
    from ai.llm.llms import create_llm_from_config

    return create_llm_from_config(**config)


model_provider_registry.register("openai_compatible", _create_openai_compatible)

"""模型供应商构造器注册表。"""

from collections.abc import Callable
from threading import RLock
from typing import Any

ModelFactory = Callable[..., Any]


class ModelProviderRegistry:
    """维护运行时注册表。"""
    def __init__(self) -> None:
        """初始化当前对象实例。"""
        self._factories: dict[str, ModelFactory] = {}
        self._lock = RLock()

    def register(self, name: str, factory: ModelFactory, *, replace: bool = False) -> None:
        """注册 当前对象。

        Args:
            name: 名称。
            factory: 工厂函数或对象。
            replace: 调用方传入的 `replace` 参数。
        """
        key = name.strip().lower()
        if not key:
            raise ValueError("provider name must not be empty")
        with self._lock:
            if key in self._factories and not replace:
                raise ValueError(f"model provider already registered: {key}")
            self._factories[key] = factory

    def create(self, name: str, **config: Any) -> Any:
        """创建 当前对象。

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
        """执行 `names` 相关逻辑。"""
        return tuple(sorted(self._factories))


model_provider_registry = ModelProviderRegistry()


def _create_openai_compatible(**config: Any) -> Any:
    # 懒加载可避免启动阶段初始化模型 SDK，也保留旧接口的兼容性。
    """创建 `openai compatible`。

    Args:
        **config: 配置对象。
    """
    from app.infrastructure.llm.llms import create_llm_from_config

    return create_llm_from_config(**config)


model_provider_registry.register("openai_compatible", _create_openai_compatible)

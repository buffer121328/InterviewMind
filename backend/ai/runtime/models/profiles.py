"""与具体供应商解耦的模型能力描述。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """表示 `ModelProfile` 相关的数据或行为。"""
    tool_calling: bool = True
    structured_output: bool = True
    streaming: bool = True
    audio_input: bool = False
    image_input: bool = False
    max_input_tokens: int | None = None

    def supports(self, capability: str) -> bool:
        """执行 `supports` 相关逻辑。

        Args:
            capability: 调用方传入的 `capability` 参数。
        """
        value = getattr(self, capability, None)
        return bool(value) if isinstance(value, bool) else value is not None

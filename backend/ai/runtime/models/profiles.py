"""与具体供应商解耦的模型能力描述。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """模型提供商和调用参数的结构化配置；只表达 endpoint、模型和能力等声明，凭据由请求边界注入且不应写入该对象。"""
    tool_calling: bool = True
    structured_output: bool = True
    streaming: bool = True
    audio_input: bool = False
    image_input: bool = False
    max_input_tokens: int | None = None

    def supports(self, capability: str) -> bool:
        """判断模型或运行时能力是否支持指定输入，供注册表选择兼容实现。

        Args:
            capability: 经过类型边界校验的 `capability`；其格式和可选值由参数类型及调用流程约束。
        """
        value = getattr(self, capability, None)
        return bool(value) if isinstance(value, bool) else value is not None

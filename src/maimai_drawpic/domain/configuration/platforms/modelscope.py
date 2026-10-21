"""ModelScope 图像平台配置。"""

from maibot_sdk import Field, PluginConfigBase


class ModelScopeModelConfig(PluginConfigBase):
    """ModelScope 图片生成平台的连接与轮询参数。"""

    __ui_label__ = "ModelScope 配置"
    __ui_order__ = 13

    enabled: bool = Field(
        default=True,
        description="是否启用 ModelScope 平台",
        json_schema_extra={
            "label": "启用 ModelScope 平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="https://api-inference.modelscope.cn",
        description="ModelScope API 根地址",
        json_schema_extra={
            "label": "ModelScope 基础 URL",
            "hint": "填写 API 地址，不是控制台或文档地址。",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="",
        description="ModelScope 访问令牌",
        json_schema_extra={
            "label": "API 密钥",
            "hint": "ModelScope 个人访问令牌，形如 ms-xxxxxxxx。",
            "input_type": "password",
            "order": 1,
        },
    )
    models: list[str] = Field(
        default=["Qwen/Qwen-Image-2.1", "Qwen/Qwen-Image-2.1-Turbo"],
        description="ModelScope 可用图片模型列表",
        json_schema_extra={
            "label": "ModelScope 模型列表",
            "hint": "填写 ModelScope 图像模型 ID。质量优先用 Qwen-Image-2.1，速度优先用 Turbo。",
            "order": 2,
        },
    )
    default_size: str = Field(
        default="1024x1024",
        description="默认图片尺寸",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "填写 宽x高，例如 1024x1024。",
            "order": 3,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="按模型覆盖图片尺寸，每项格式为 模型名=宽x高",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "hint": "每行填写一个 模型名=宽x高。",
            "order": 4,
        },
    )
    poll_interval_seconds: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="异步任务轮询间隔（秒）",
        json_schema_extra={
            "label": "轮询间隔（秒）",
            "hint": "ModelScope 为异步任务接口，建议 5 秒。",
            "order": 5,
        },
    )
    poll_timeout_seconds: float = Field(
        default=300.0,
        ge=30.0,
        le=1800.0,
        description="异步任务最长等待时间（秒）",
        json_schema_extra={
            "label": "轮询超时（秒）",
            "hint": "超过该时长仍未完成则判定失败。",
            "order": 6,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="额外 JSON 参数，每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，用于兼容平台新增参数。",
            "order": 7,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用前将提示词改写为英文。",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "Qwen 系列对中文支持良好，通常无需开启。",
            "order": 8,
        },
    )

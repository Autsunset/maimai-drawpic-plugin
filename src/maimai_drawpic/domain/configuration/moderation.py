"""configuration/moderation.py 的强类型配置定义。"""

from maibot_sdk import Field, PluginConfigBase


class PromptModerationConfig(PluginConfigBase):
    """提示词审核配置。"""

    __ui_label__ = "提示词审核"
    __ui_order__ = 12

    enabled: bool = Field(
        default=False,
        description="是否启用提示词审核。启用后会调用 MaiBot 当前配置的 replyer 模型进行识别",
        json_schema_extra={
            "label": "启用提示词审核",
            "hint": "启用后，文生图和图生图的提示词会先交给 MaiBot 的 replyer 模型审核",
            "order": 0,
        },
    )
    review_prompt: str = Field(
        default=(
            "你是绘图提示词审核器。请判断下面的绘图提示词是否适合继续交给绘图模型生成\n"
            "审核要求：\n"
            "1. 如果提示词涉及明显违法、暴力犯罪、血腥猎奇、未成年人色情、仇恨歧视、现实人物色情深度伪造等高风险内容，必须拒绝\n"
            "2. 如果提示词内容普通、安全、可接受，则允许通过\n"
            "3. 你的回复必须严格使用以下格式，不要输出多余内容：\n"
            "结论：PASS 或 REJECT\n"
            "原因：一句简短中文说明\n"
            "\n"
            "待审核提示词：\n"
            "{user_prompt}"
        ),
        description="提示词审核时发送给 replyer 模型的审核提示模板，支持 {user_prompt} 占位符",
        json_schema_extra={
            "label": "提示词审核提示词",
            "hint": "支持 {user_prompt} 占位符；建议要求模型只返回 PASS 或 REJECT 及简短原因",
            "input_type": "textarea",
            "order": 1,
        },
    )


class ImageModerationConfig(PluginConfigBase):
    """生成图片审核配置。"""

    __ui_label__ = "生成图片审核"
    __ui_order__ = 13

    enabled: bool = Field(
        default=False,
        description="是否启用生成图片审核。启用后会调用 MaiBot 当前配置的 vlm 模型进行识别",
        json_schema_extra={
            "label": "启用生成图片审核",
            "hint": "启用后，生成完成的图片会先交给 MaiBot 的 vlm 模型审核，再决定是否发送",
            "order": 0,
        },
    )
    review_prompt: str = Field(
        default=(
            "你是绘图结果审核器。请审核这张图片是否适合直接发送给普通聊天场景\n"
            "审核要求：\n"
            "1. 如果图片包含明显违法、暴力犯罪、血腥猎奇、未成年人色情、仇恨歧视、现实人物色情深度伪造等高风险内容，必须拒绝。\n"
            "2. 如果图片内容普通、安全、可接受，则允许通过。\n"
            "3. 结合本次生成提示词一起判断。\n"
            "4. 你的回复必须严格使用以下格式，不要输出多余内容：\n"
            "结论：PASS 或 REJECT\n"
            "原因：一句简短中文说明\n"
            "\n"
            "本次生成提示词：\n"
            "{user_prompt}"
        ),
        description="生成图片审核时发送给 vlm 模型的审核提示模板，支持 {user_prompt} 占位符",
        json_schema_extra={
            "label": "生成图片审核提示词",
            "hint": "支持 {user_prompt} 占位符；建议要求模型只返回 PASS 或 REJECT 及简短原因",
            "input_type": "textarea",
            "order": 1,
        },
    )

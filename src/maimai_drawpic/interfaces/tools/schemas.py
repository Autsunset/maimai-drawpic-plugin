"""绘图工具的参数声明。"""

from typing import Any

DRAW_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": (
                "图片提示词，描述主体、动作、服装、场景、构图、氛围和画风。写具体一些出图效果更好。"
                "用户提到具体角色名（如某位虚拟主播）时，不要自行补充该角色的发色、发型、瞳色、"
                "体型等外貌细节——插件的角色库会补全正确形象，自行编造会与角色库冲突，反而画错。"
                "场景、动作、服装和画风可以照常补充，画风留空时插件会补一个默认画风。"
            ),
        },
        "model": {
            "type": "string",
            "description": "可选，指定要优先使用的图片模型；未传时使用当前会话首选模型",
        },
        "negative_prompt": {
            "type": "string",
            "description": "可选，本次绘图的反向提示词；支持独立反向字段的平台会单独传递，否则合并到正向提示词",
        },
    },
    "required": ["prompt"],
}


EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "图片编辑提示词，描述希望基于源图修改成什么样；不要把源图片描述写在这里替代真实图片",
        },
        "source_message_id": {
            "type": "string",
            "description": "可选，指定要编辑的源图片消息 ID；不填时自动优先取当前/最近引用消息中的图片，再取最近一张图片",
        },
        "source_image_base64": {
            "type": "string",
            "description": "可选，直接传入真实源图片 Base64 或 data:image/...;base64；不要传图片描述文本",
        },
        "model": {
            "type": "string",
            "description": "可选，指定要优先使用的图片模型；未传时使用当前会话首选模型",
        },
        "negative_prompt": {
            "type": "string",
            "description": "可选，本次图生图的反向提示词；会与平台默认反向词合并",
        },
    },
    "required": ["prompt"],
}


DRAW_STATUS_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "task_id": {
            "type": "string",
            "description": "可选，指定要查询的后台绘图任务 ID；不填时默认查询当前会话最近一个任务",
        },
    },
    "required": [],
}


STYLED_DRAW_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "用户正向提示词；图生图时可以留空，由风格模板和源图片共同决定画面",
        },
        "style": {
            "type": "string",
            "description": "可选的插件全平台风格模板名称；不填时按普通 draw/edit_image 行为执行",
        },
        "negative_prompt": {
            "type": "string",
            "description": "可选的用户反向提示词，会与风格反向模板及平台默认反向词合并",
        },
        "source_message_id": {
            "type": "string",
            "description": "可选，指定图生图源图片消息 ID",
        },
        "source_image_base64": {
            "type": "string",
            "description": "可选，直接提供真实源图片 Base64 或 data URL",
        },
    },
    "required": [],
}


DRAW_STYLES_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "required": [],
}

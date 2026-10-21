"""默认画风兜底。

问题：群友说「画个星瞳」，chat LLM 只把这句话原样传过来。角色库补上了外貌，
但提示词里没有任何画风、媒介、画质描述，图像模型就用最朴素的方式出图——平涂、
白底，观感明显比带风格词的提示词差。

这里在角色补全之后补一段可配置的画风标签，但只在提示词**完全没有**画风线索
时才加：用户或 LLM 已经写了水彩、厚涂、写实摄影这类风格，再加默认风格就是
在打架，出来的图两边都不像。

风格词表按中英文同时收：提示词可能还是中文（ModelScope 等渠道不做英文改写），
也可能是 LLM 已经写好的英文标签。
"""

from __future__ import annotations

import re

# 画风、媒介、画质线索。命中任意一个就说明提示词自己定了调子，默认风格不加。
# 只收真正描述「怎么画」的词：不能收「光」「背景」「细节」这种任何提示词都
# 可能出现的泛词，否则默认风格几乎永远不会补上。
_STYLE_CUES: tuple[str, ...] = (
    # 中文：画风与媒介
    "风格", "画风", "厚涂", "平涂", "赛璐璐", "水彩", "油画", "水墨", "国风",
    "手绘", "素描", "线稿", "写实", "真人", "照片", "摄影", "胶片", "3d",
    "像素", "赛博朋克", "蒸汽波", "浮世绘", "漫画", "绘本", "插画", "立绘",
    "二次元", "动漫", "动画", "cg", "渲染",
    # 中文：画质
    "高清", "超清", "4k", "8k", "画质", "杰作", "大师",
    # 英文结构，如 "watercolor style" / "anime illustration"
    "watercolor", "oil painting", "sketch", "lineart", "line art", "photorealistic",
    "photograph", "cinematic", "3d render", "pixel art", "cel shading", "chibi",
    "illustration", "anime", "manga", "masterpiece", "best quality", "high quality",
    "highly detailed", "ultra detailed", "8k", "4k",
)

_CUE_PATTERN = re.compile(
    "|".join(re.escape(cue) for cue in sorted(_STYLE_CUES, key=len, reverse=True)),
    re.IGNORECASE,
)


def has_style_cue(prompt: str) -> bool:
    """判断提示词是否已经描述了画风或画质。"""

    return bool(_CUE_PATTERN.search(prompt or ""))


def append_default_style(prompt: str, style_prompt: str) -> tuple[str, bool]:
    """提示词没有画风线索时追加默认画风。

    返回 (最终提示词, 是否追加)。style_prompt 为空表示用户关掉了这个功能；
    提示词已自带风格时也原样返回，绝不叠加两种画风。
    """

    style_prompt = (style_prompt or "").strip().strip(", ")
    if not style_prompt or not prompt.strip():
        return prompt, False
    if has_style_cue(prompt):
        return prompt, False
    return f"{prompt.strip().rstrip(', ')}, {style_prompt}", True

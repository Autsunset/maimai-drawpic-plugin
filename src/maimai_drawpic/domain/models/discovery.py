"""模型发现的纯展示规则，不根据名称猜测并写入任务能力。"""

import re

from .aliyun_profiles import resolve_aliyun_model_profile


def is_image_candidate(model: str) -> bool:
    """仅用于模型选择器的初始筛选，用户仍可展开接口返回的全部模型。"""
    return (
        re.search(r"image|imagen|seedream|cogview|kolors|flux|dall[-_]e|stable[-_]diffusion", model, re.I) is not None
    )


def is_supported_aliyun_image(model: str) -> bool:
    """百炼发现只展示插件已接入的图像家族，不混入万象或视频模型。"""
    return resolve_aliyun_model_profile(model).family != "legacy"

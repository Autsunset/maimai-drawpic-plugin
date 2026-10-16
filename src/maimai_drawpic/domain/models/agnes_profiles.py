"""Agnes 图片请求参数；图生图与文生图共用生成端点。"""

from copy import deepcopy
from typing import Any, Dict, List, Optional


def build_agnes_payload(
    prompt: str,
    model: str,
    *,
    size: str,
    ratio: str,
    response_format: str,
    extra_parameters: Dict[str, Any],
    images: Optional[List[str]] = None,
    n: int = 1,
) -> Dict[str, Any]:
    """保留扩展参数，但禁止其改写任务身份、源图与平台专用输出字段。"""
    if n != 1:
        raise ValueError("Agnes 当前每次请求生成 1 张图片")
    reserved = {"model", "prompt", "image", "size", "ratio", "response_format", "return_base64", "n", "tags"}
    if reserved & extra_parameters.keys():
        raise ValueError("Agnes 额外参数不能覆盖模型、提示词、源图、尺寸或响应格式；请使用对应表单字段")
    payload = deepcopy(extra_parameters)
    body = payload.setdefault("extra_body", {})
    if not isinstance(body, dict):
        raise ValueError("Agnes 的 extra_body 必须是 JSON 对象")
    if {"image", "response_format"} & body.keys():
        raise ValueError("Agnes 的参考图与响应格式由任务和表单维护，请勿在 extra_body 重复配置")
    body["response_format"] = response_format
    if images is not None:
        if not images:
            raise ValueError("Agnes 图生图需要至少一张参考图片")
        body["image"] = images
    payload.update(model=model, prompt=prompt, size=size)
    # 2.0 文档仅声明像素尺寸；后续版本支持档位与独立宽高比。
    if model != "agnes-image-2.0-flash":
        payload["ratio"] = ratio
    elif size.upper() in {"1K", "2K", "3K", "4K"}:
        raise ValueError("Agnes Image 2.0 请填写像素尺寸，例如 1024x1024，或设置该模型的尺寸覆盖")
    return payload

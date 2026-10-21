"""ModelScope 图像平台适配器。

ModelScope 的图片接口不是 OpenAI 兼容格式：提交后返回 `task_id`，必须轮询
`/v1/tasks/{id}` 并带上 `X-ModelScope-Task-Type: image_generation` 头，直到
`task_status` 变为 `SUCCEED`，再从 `output_images` 下载图片。

这里继承 `OpenaiImage` 以复用其构造参数、尺寸解析、图片校验、代理配置与错误
脱敏，只覆盖生成流程并自带 JSON 请求方法（父类的 `_post_json` 不接受自定义
请求头，而 ModelScope 的异步协议必须带）。

本文件是原文件；若文件已存在，请用本目录的替换版本覆盖。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncio
import json
import time

import aiohttp

from .openai import OpenaiImage
from ..http import (
    HttpProxySettings,
    read_response_json,
    read_response_text,
    sanitize_provider_url,
)
from ..media.downloads import download_image


class ModelScopeImage(OpenaiImage):
    """通过 ModelScope 异步任务接口执行文生图与图片编辑。"""

    # 父类会把 base_url 规范化为 `<host>/v1`，因此这里只写接口相对路径。
    _SUBMIT_PATH = "images/generations"
    _TASK_PATH = "tasks/{task_id}"
    _ASYNC_SUBMIT_HEADER = {"X-ModelScope-Async-Mode": "true"}
    _ASYNC_POLL_HEADER = {"X-ModelScope-Task-Type": "image_generation"}
    _SUCCEED = "SUCCEED"
    _FAILED = "FAILED"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api-inference.modelscope.cn",
        default_size: str = "1024x1024",
        model_size_overrides: Optional[Dict[str, str]] = None,
        extra_parameters: Optional[Dict[str, Any]] = None,
        request_timeout_seconds: int = 150,
        poll_interval_seconds: float = 5.0,
        poll_timeout_seconds: float = 300.0,
        logger: Any = None,
        proxy_settings: Optional[HttpProxySettings] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_size=default_size,
            model_size_overrides=model_size_overrides,
            extra_parameters=extra_parameters,
            request_timeout_seconds=request_timeout_seconds,
            logger=logger,
            proxy_settings=proxy_settings,
        )
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.poll_timeout_seconds = float(poll_timeout_seconds)

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构建鉴权请求头；内容不得进入日志。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(extra or {})
        return headers

    async def _request_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """执行 HTTP 请求并解析 JSON，错误信息保留状态码与脱敏后的正文。"""
        started_at = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(
            timeout=timeout,
            **self.proxy_settings.aiohttp_session_kwargs(),
        ) as session:
            async with session.request(
                method,
                url,
                headers=self._headers(extra_headers),
                json=payload,
                allow_redirects=False,
                **self.proxy_settings.aiohttp_request_kwargs(),
            ) as response:
                duration = time.monotonic() - started_at
                if response.status != 200:
                    detail = await read_response_text(response, max_bytes=64 * 1024)
                    self._log_error(
                        "ModelScope 接口失败: method=%s status=%s duration=%.2fs url=%s body=%s",
                        method,
                        response.status,
                        duration,
                        sanitize_provider_url(url),
                        str(detail)[:300],
                    )
                    raise RuntimeError(
                        f"ModelScope 接口 HTTP {response.status}（{duration:.2f}s）: {str(detail)[:300]}"
                    )
                result = await read_response_json(response)
                if not isinstance(result, dict):
                    raise RuntimeError("ModelScope 接口返回了非对象 JSON")
                return result

    async def _submit_task(self, payload: Dict[str, Any]) -> str:
        """提交异步生成任务并返回 task_id。"""
        response = await self._request_json(
            "POST",
            self._build_api_url(self._SUBMIT_PATH),
            payload=payload,
            extra_headers=self._ASYNC_SUBMIT_HEADER,
        )
        task_id = response.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise RuntimeError(f"ModelScope 提交响应缺少 task_id: {str(response)[:300]}")
        self._log_info(
            "ModelScope 任务已提交: model=%s task_id=%s",
            payload.get("model"),
            task_id,
        )
        return task_id.strip()

    async def _poll_task(self, task_id: str) -> List[str]:
        """轮询任务直到 SUCCEED 或 FAILED，返回结果图片 URL 列表。"""
        deadline = time.monotonic() + self.poll_timeout_seconds
        previous_status = ""
        url = self._build_api_url(self._TASK_PATH.format(task_id=task_id))
        while time.monotonic() < deadline:
            response = await self._request_json(
                "GET",
                url,
                extra_headers=self._ASYNC_POLL_HEADER,
            )
            status = str(response.get("task_status") or "").strip().upper()

            if status != previous_status:
                self._log_info(
                    "ModelScope 任务状态变化: task_id=%s from=%s to=%s",
                    task_id,
                    previous_status or "SUBMITTED",
                    status or "MISSING",
                )
                previous_status = status

            if status == self._SUCCEED:
                urls = response.get("output_images") or []
                if not isinstance(urls, list) or not urls:
                    raise RuntimeError(f"ModelScope 任务 {task_id} 成功但未返回图片")
                return [str(item) for item in urls]

            if status == self._FAILED:
                message = response.get("message") or response.get("errors") or response
                raise RuntimeError(f"ModelScope 任务 {task_id} 失败: {str(message)[:300]}")

            await asyncio.sleep(self.poll_interval_seconds)

        raise RuntimeError(
            f"ModelScope 任务 {task_id} 轮询超时（{self.poll_timeout_seconds:.0f}s，"
            f"最后状态={previous_status or 'UNKNOWN'}）"
        )

    async def _download_all(self, urls: List[str]) -> List[bytes]:
        """并发下载结果图片。"""
        return await asyncio.gather(
            *(
                download_image(
                    url,
                    base_url=self.base_url,
                    proxy_settings=self.proxy_settings,
                    timeout_seconds=self.request_timeout_seconds,
                )
                for url in urls
            )
        )

    async def _generate(
        self,
        prompt: str,
        model: str,
        n: int,
        images: Optional[List[str]] = None,
    ) -> List[bytes]:
        """提交异步任务，轮询至完成，再下载结果图片。"""
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            **self.extra_parameters,
        }
        size = self._resolve_size(model)
        if size:
            payload["size"] = size
        if images:
            # ModelScope 接受 URL 列表；本地图片统一用 data URL 传递。
            payload["image_url"] = list(images)
        if n and n > 1:
            payload["n"] = int(n)

        task_id = await self._submit_task(payload)
        urls = await self._poll_task(task_id)
        return await self._download_all(urls)

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> List[bytes]:
        return await self._generate(prompt, model, n)

    async def edit_images(
        self,
        prompt: str,
        model: str,
        image_bytes_list: List[bytes],
        n: int = 1,
    ) -> List[bytes]:
        images = await asyncio.to_thread(
            lambda: [self._source_image_data_url(image) for image in image_bytes_list]
        )
        return await self._generate(prompt, model, n, images)

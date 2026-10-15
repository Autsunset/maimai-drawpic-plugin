"""严格校验分块协议，保存路径由调用插件明确提供。"""

from pathlib import Path
import asyncio
import base64
import binascii
import os
import tempfile

from .models import DrawingError, DrawingTransportError
from .transport import DrawingRPC


async def read_image(rpc: DrawingRPC, task_id: str, index: int, max_bytes: int) -> bytes:
    offset, chunks, expected = 0, [], None
    while True:
        response = None
        for attempt in range(3):
            try:
                response = await rpc.call("image", task_id=task_id, index=index, kind="original", offset=offset)
                break
            except DrawingTransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)
        if response.get("error"):
            raise DrawingError(response["error"], task_id=task_id)
        try:
            size = response["size"]
            if type(size) is not int or not 0 < size <= max_bytes:
                raise ValueError("图片超过客户端容量限制或大小无效")
            identity = (size, response["mime"], response["filename"])
            if expected is not None and identity != expected:
                raise ValueError("图片分块来源或大小改变")
            expected = identity
            if identity[1] not in {"image/png", "image/jpeg", "image/webp"}:
                raise ValueError("图片格式无效")
            raw = base64.b64decode(response["data"], validate=True)
            if response["offset"] != offset or not 0 < len(raw) <= 192 * 1024:
                raise ValueError("图片分块偏移或大小无效")
            offset += len(raw)
            if response["next_offset"] != offset or offset > size or type(response["done"]) is not bool:
                raise ValueError("图片分块进度无效")
            if response["done"] != (offset == size):
                raise ValueError("图片分块终止标记无效")
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise DrawingTransportError(f"图片分块协议错误：{exc}") from exc
        chunks.append(raw)
        if response["done"]:
            return await asyncio.to_thread(b"".join, chunks)


def save_bytes(destination: Path, data: bytes, overwrite: bool) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            temporary.replace(destination)
        else:
            # 排他创建目标，避免“先 exists 再 replace”覆盖并发写入者。
            os.link(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

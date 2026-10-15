"""Per-response collection limits, shared across nested parsers and worker threads.

Budgets bound retained compressed results and sequential raster processing; they
are not an RSS guarantee. SDK response allocation happens before our collector.
"""
from contextvars import ContextVar
from functools import wraps
from io import BytesIO
import base64
import inspect

from PIL import Image
from ...domain.errors import ProviderResultError
from .images import MAX_IMAGE_BYTES, check_image_dimensions, validate_image_bytes

# Permit ordinary small batches, or four maximum-size compressed / 4K images.
# Keep this independent from disk retention: processing precedes cache pruning.
MAX_RESULT_IMAGES = 16
MAX_RESULT_BYTES = 100 * 1024 * 1024
MAX_RESULT_PIXELS = 4 * 4096 * 4096


class ResultBudget:
    def __init__(self) -> None:
        self.count = 0
        self.bytes = 0

    def available(self) -> int:
        if self.count >= MAX_RESULT_IMAGES or self.bytes >= MAX_RESULT_BYTES:
            raise ProviderResultError("图片结果超过总量限制（最多 16 张、合计 100 MiB），未重新生成")
        return min(MAX_IMAGE_BYTES, MAX_RESULT_BYTES - self.bytes)

    def accept(self, raw: bytes) -> bytes:
        if len(raw) > self.available():
            raise ProviderResultError("图片结果超过剩余字节预算，未重新生成")
        self.count += 1
        self.bytes += len(raw)
        return raw


_budget = ContextVar("image_result_budget", default=None)


def current_budget() -> ResultBudget:
    return _budget.get() or ResultBudget()


def bounded_results(function):
    """One budget per outer result parser; nested formats share that budget."""
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def asynchronous(*args, **kwargs):
            token = _budget.set(ResultBudget()) if _budget.get() is None else None
            try:
                return await function(*args, **kwargs)
            finally:
                if token is not None:
                    _budget.reset(token)
        return asynchronous
    @wraps(function)
    def synchronous(*args, **kwargs):
        token = _budget.set(ResultBudget()) if _budget.get() is None else None
        try:
            return function(*args, **kwargs)
        finally:
            if token is not None:
                _budget.reset(token)
    return synchronous


def decode_result_base64(value: str | bytes, *, validate: bool = False) -> bytes:
    budget = current_budget()
    # Bound the allocation before decoding, including whitespace-heavy input.
    if len(value) > 4 * ((budget.available() + 2) // 3):
        raise ProviderResultError("图片 Base64 超过剩余结果预算，未重新生成")
    return budget.accept(base64.b64decode(value, validate=validate))


def validate_result_images(images: list[bytes]) -> list[bytes]:
    budget = ResultBudget()
    pixels = 0
    try:
        for raw in images:
            budget.accept(raw)
            with Image.open(BytesIO(raw)) as image:
                pixels += check_image_dimensions(image)
            if pixels > MAX_RESULT_PIXELS:
                raise ValueError("图片结果合计超过 67108864 像素")
        return [validate_image_bytes(raw) for raw in images]
    except ProviderResultError:
        raise
    except Exception as exc:
        raise ProviderResultError(f"图片结果校验失败（{type(exc).__name__}），未重新生成") from None

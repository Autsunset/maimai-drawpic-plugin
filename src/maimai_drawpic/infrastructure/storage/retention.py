"""运行产物的容量与过期策略，只清理本插件拥有的缓存目录。"""

from pathlib import Path
from hashlib import sha256
from threading import RLock
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4
import re
import shutil
import time

from ..concurrency import synchronized
from ..media.images import validate_image_bytes


class CacheCapacityError(ValueError):
    """缓存中受保护的内容或单次结果超过容量，不应触发上游重绘。"""


class ArtifactRetention:
    INPUT_MAX_BYTES = 256 * 1024 * 1024
    INPUT_MAX_FILES = 100
    INPUT_MAX_AGE = 24 * 3600
    RESULT_MAX_BYTES = 300 * 1024 * 1024
    RESULT_MAX_TASKS = 500
    RESULT_MAX_AGE = 30 * 24 * 3600

    def __init__(self, data_dir: Path, runtime_dir: Optional[Path] = None) -> None:
        self.data_dir = data_dir.resolve()
        self.runtime_dir = (runtime_dir if runtime_dir is not None else data_dir).resolve()
        self.result_roots = list(dict.fromkeys((self.runtime_dir / "results", self.data_dir / "results")))
        self._lock = RLock()

    def _owned(self, path: Path, root: Path) -> None:
        if root.is_symlink() or not any(
            root.resolve().is_relative_to(owner) for owner in (self.data_dir, self.runtime_dir)
        ):
            raise ValueError("缓存根目录不属于当前插件")
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.resolve() == root.resolve():
            raise ValueError("拒绝清理不安全的缓存路径")

    def _remove(self, path: Path, root: Path) -> None:
        # Windows 递归清理前，必须验证最终绝对目标在指定的缓存根目录内。
        self._owned(path, root)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    @synchronized
    def prune_inputs(self, incoming: int = 0, exclude: Optional[Path] = None) -> Dict[str, int]:
        files: List[Path] = []
        for name in ("inputs", "uploads"):
            root = self.data_dir / name
            if root.is_symlink():
                raise ValueError("缓存根目录不能为符号链接")
            if root.exists():
                files.extend(
                    path for path in root.iterdir() if path != exclude and path.is_file() and not path.is_symlink()
                )
        now = time.time()
        removed = 0
        remaining = []
        for path in files:
            stat = path.stat()
            if now - stat.st_mtime > self.INPUT_MAX_AGE:
                self._remove(path, path.parent)
                removed += 1
            else:
                remaining.append((stat.st_mtime, path, stat.st_size))
        remaining.sort(key=lambda item: item[0])
        total = sum(item[2] for item in remaining)
        if incoming > self.INPUT_MAX_BYTES:
            raise ValueError("上传图片超过缓存容量")
        while remaining and (
            total + incoming > self.INPUT_MAX_BYTES or len(remaining) + bool(incoming) > self.INPUT_MAX_FILES
        ):
            _, path, size = remaining.pop(0)
            self._remove(path, path.parent)
            total -= size
            removed += 1
        return {"removed": removed, "bytes": total}

    @synchronized
    def claim_input(self, path: Path, digest: str) -> Tuple[str, bytes]:
        """校验、清理配额、原子接管上传共用锁，与其他上传和定时清理互斥。"""
        root = self.data_dir / "uploads"
        self._owned(path, root)
        if path.parent.resolve() != root.resolve():
            raise ValueError("上传文件不属于当前插件")
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise ValueError("上传图片已过期或被清理，请重新上传") from None
        if len(raw) > 20 * 1024 * 1024 or sha256(raw).hexdigest() != digest:
            raise ValueError("上传图片大小或校验值异常")
        validate_image_bytes(raw)
        identifier = uuid4().hex
        directory = self.data_dir / "inputs"
        if directory.is_symlink():
            raise ValueError("输入缓存目录不安全")
        directory.mkdir(parents=True, exist_ok=True)
        self.prune_inputs(len(raw), exclude=path)
        # 同一数据目录内 rename 不复制图片，不存在先写出双份再释放上传的超额窗口。
        path.replace(directory / f"{identifier}.image")
        return identifier, raw

    @synchronized
    def prune_results(self, protected: Set[str], incoming: int = 0) -> Dict[str, int]:
        if incoming > self.RESULT_MAX_BYTES:
            raise CacheCapacityError("单个任务的图片结果超过缓存容量")
        now, removed = time.time(), 0
        remaining = []
        # 新结果放入 SDK 临时目录；兼容读取的旧数据目录缓存共用同一个容量。
        for root in self.result_roots:
            if root.is_symlink():
                raise ValueError("图片缓存根目录不能为符号链接")
            if not root.exists():
                continue
            for path in root.iterdir():
                if not path.is_dir() or path.is_symlink() or not re.fullmatch(r"[a-f0-9]{12}", path.name):
                    continue
                self._owned(path, root)
                stat = path.stat()
                if now - stat.st_mtime > self.RESULT_MAX_AGE and path.name not in protected:
                    self._remove(path, root)
                    removed += 1
                    continue
                size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())
                remaining.append((stat.st_mtime, path, size))
        remaining.sort(key=lambda item: item[0])
        total = sum(item[2] for item in remaining)
        count = len(remaining)
        for _, path, size in remaining:
            if total + incoming <= self.RESULT_MAX_BYTES and count + bool(incoming) <= self.RESULT_MAX_TASKS:
                break
            if path.name in protected:
                continue
            self._remove(path, path.parent)
            total -= size
            count -= 1
            removed += 1
        if total + incoming > self.RESULT_MAX_BYTES:
            raise CacheCapacityError("图片缓存空间不足，正在使用的结果无法清理")
        return {"removed": removed, "bytes": total}

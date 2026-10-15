"""将旧版源码目录中的持久数据迁移到 Runner 授予的目录。"""

from hashlib import file_digest
from pathlib import Path
from typing import Dict, List, Tuple
from uuid import uuid4
import os
import shutil
import tempfile


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def migrate_plugin_data(plugin_dir: Path, data_dir: Path) -> List[Path]:
    """校验并复制旧数据，成功后将原文件改名为备份；冲突时不覆盖。"""

    plugin_dir = plugin_dir.resolve()
    data_dir = data_dir.resolve()
    legacy_dir = plugin_dir / "data"
    if data_dir == plugin_dir or plugin_dir in data_dir.parents or data_dir in plugin_dir.parents:
        raise ValueError("插件数据目录必须独立于旧版数据目录和源码父目录")

    sources: List[Path] = []
    entries: Dict[Path, Tuple[Path, str]] = {}
    source_digests: Dict[Path, str] = {}
    if legacy_dir.exists():
        if legacy_dir.is_symlink() or not legacy_dir.is_dir():
            raise ValueError(f"旧数据目录不是普通目录: {legacy_dir}")
        sources.append(legacy_dir)
        for source in sorted(legacy_dir.rglob("*")):
            if source.is_symlink() or legacy_dir not in source.resolve().parents:
                raise ValueError(f"旧数据包含链接或目录外文件: {source}")
            if source.is_file():
                source_digests[source] = _sha256(source)
                entries[data_dir / source.relative_to(legacy_dir)] = (source, source_digests[source])

    # 更早版本把状态文件直接放在插件根目录；也要迁移，但不搬动 config.toml。
    for name in ("session_preferences.json", "draw_tasks.json", "user_quotas.json"):
        source = plugin_dir / name
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"旧状态文件不是普通文件: {source}")
        digest = _sha256(source)
        source_digests[source] = digest
        target = data_dir / name
        if target in entries and entries[target][1] != digest:
            raise FileExistsError(f"两处旧数据内容冲突，请先处理: {source} / {entries[target][0]}")
        entries[target] = (source, digest)
        sources.append(source)

    # 写入前一次性检查全部目标，避免发现冲突时已经覆盖部分数据。
    for target, (_, digest) in entries.items():
        if target.is_symlink() or data_dir not in target.resolve().parents:
            raise ValueError(f"迁移目标包含链接或越出数据目录: {target}")
        if target.exists() and (not target.is_file() or _sha256(target) != digest):
            raise FileExistsError(f"插件数据迁移冲突，不覆盖现有文件: {target}")

    data_dir.mkdir(parents=True, exist_ok=True)
    for target, (source, digest) in entries.items():
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".migration-", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copy2(source, temporary)
            if _sha256(temporary) != digest:
                raise RuntimeError(f"迁移期间源文件发生变化，请停止旧实例后重试: {source}")
            # 同目录硬链接原子发布完整副本；目标已存在时直接失败，不覆盖竞态写入。
            os.link(temporary, target)
        finally:
            temporary.unlink()

    # 全部副本校验通过后才归档原件；失败或中断时可由相同内容的目标继续迁移。
    if legacy_dir.exists():
        current_files = {path for path in legacy_dir.rglob("*") if path.is_file()}
        expected_files = {path for path in source_digests if legacy_dir in path.parents}
        if current_files != expected_files:
            raise RuntimeError("迁移期间旧数据文件列表发生变化，请停止旧实例后重试")
    for source, digest in source_digests.items():
        if _sha256(source) != digest:
            raise RuntimeError(f"迁移期间源文件发生变化，保留原件: {source}")
    for target, (source, digest) in entries.items():
        if _sha256(source) != digest or _sha256(target) != digest:
            raise RuntimeError(f"迁移期间数据发生变化，保留原件: {source}")
    backups: List[Path] = []
    for source in sources:
        backup = source.with_name(f"{source.name}.migrated-{uuid4().hex}")
        source.rename(backup)
        backups.append(backup)
    return backups


def resolve_workflow_path(configured_path: str, plugin_dir: Path, data_dir: Path) -> Path:
    """解析工作流路径，将旧版 data/ 路径定向到标准持久数据目录。"""

    path = Path(configured_path.replace("\\", "/")).expanduser()
    legacy_dir = (plugin_dir / "data").resolve()
    if path.is_absolute():
        resolved = path.resolve()
        if resolved.is_relative_to(legacy_dir):
            return data_dir / resolved.relative_to(legacy_dir)
        return resolved
    if path.parts and path.parts[0] == "data":
        return data_dir.joinpath(*path.parts[1:])
    return plugin_dir / path

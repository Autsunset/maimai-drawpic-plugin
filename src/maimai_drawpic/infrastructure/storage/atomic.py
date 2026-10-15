from pathlib import Path
from typing import Any
import json
import logging
import os
import sys
import tempfile


def _cleanup_temporary(path: Path | None) -> None:
    if path is None:
        return
    original_error = sys.exc_info()[1]
    try:
        path.unlink(missing_ok=True)
    except OSError as cleanup_error:
        if original_error is None:
            raise
        # Preserve the actual write error; do not include payloads or file paths.
        logging.getLogger(__name__).warning(
            "Atomic temporary file cleanup failed: error_type=%s", type(cleanup_error).__name__
        )


def write_text_atomically(path: Path, text: str) -> None:
    """保留完整换行，在同目录原子替换文本文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        _cleanup_temporary(temporary)


def write_json_atomically(path: Path, payload: Any) -> None:
    """将 JSON 数据原子写入目标文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        temp_path.replace(path)
    finally:
        _cleanup_temporary(temp_path)

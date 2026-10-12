"""Tail recent application log files from the data directory (desktop + dev)."""
from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

DEFAULT_MAX_LINES = 400
DEFAULT_MAX_BYTES = 512 * 1024
KNOWN_LOG_NAMES = ("launcher.log", "electron.log", "backend.log", "uvicorn.log")


def _tail_file(path: Path, *, max_lines: int, max_bytes: int) -> dict[str, Any]:
    if not path.is_file():
        return {
            "name": path.name,
            "path": str(path),
            "missing": True,
            "lines": [],
            "truncated": False,
            "size_bytes": 0,
        }
    size = path.stat().st_size
    truncated = size > max_bytes
    read_size = min(size, max_bytes)
    try:
        with open(path, "rb") as fh:
            if read_size < size:
                fh.seek(-read_size, os.SEEK_END)
                chunk = fh.read(read_size)
                if chunk and not chunk.startswith(b"\n"):
                    chunk = chunk.split(b"\n", 1)[-1]
            else:
                chunk = fh.read()
        text = chunk.decode("utf-8", errors="replace")
    except OSError as exc:
        return {
            "name": path.name,
            "path": str(path),
            "missing": False,
            "error": str(exc),
            "lines": [],
            "truncated": truncated,
            "size_bytes": size,
        }
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
    return {
        "name": path.name,
        "path": str(path),
        "missing": False,
        "lines": lines,
        "truncated": truncated,
        "size_bytes": size,
    }


def _discover_log_paths(data_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for name in KNOWN_LOG_NAMES:
        p = data_dir / name
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    logs_dir = data_dir.parent / "logs"
    if logs_dir.is_dir():
        for p in sorted(logs_dir.glob("*.log")):
            if p not in seen:
                seen.add(p)
                ordered.append(p)
    try:
        for p in sorted(data_dir.glob("*.log")):
            if p not in seen:
                seen.add(p)
                ordered.append(p)
    except OSError:
        pass
    return ordered


def get_recent_logs(
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    max_lines = max(50, min(int(max_lines), 2000))
    max_bytes = max(4096, min(int(max_bytes), 2 * 1024 * 1024))
    data_dir = DATA_DIR
    files: list[dict[str, Any]] = []
    combined: deque[str] = deque(maxlen=max_lines * 3)
    for path in _discover_log_paths(data_dir):
        entry = _tail_file(path, max_lines=max_lines, max_bytes=max_bytes)
        files.append(entry)
        if entry.get("lines"):
            combined.append(f"===== {entry['name']} =====")
            combined.extend(entry["lines"])
    tail_combined = list(combined)[-max_lines:]
    return {
        "data_dir": str(data_dir),
        "max_lines": max_lines,
        "files": files,
        "lines": tail_combined,
    }

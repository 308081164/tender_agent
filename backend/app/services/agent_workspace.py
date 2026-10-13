"""Agent 工程目录：默认工作区、路径白名单内读写、导出镜像。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.models import TenderProject
from app.services.agent_qual_folder import PathNotAllowedError, normalize_folder_path

WORKSPACE_SUB_PROCESS = "过程资料"
WORKSPACE_SUB_OUTPUT = "产出"

_TEXT_EXTENSIONS = frozenset({"md", "markdown", "txt", "json", "csv", "log", "py", "js", "ts", "html", "css", "xml", "yaml", "yml"})


def default_agent_workspace_root() -> Path:
    root = (Path(DATA_DIR) / "agent_workspace" / "default").resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in (WORKSPACE_SUB_PROCESS, WORKSPACE_SUB_OUTPUT):
        (root / name).mkdir(exist_ok=True)
    return root


def ensure_project_workspace_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in (WORKSPACE_SUB_PROCESS, WORKSPACE_SUB_OUTPUT):
        (root / name).mkdir(exist_ok=True)


def validate_workspace_dir(raw: str) -> str:
    """校验并返回规范化后的工程目录绝对路径。"""
    path = normalize_folder_path(raw)
    ensure_project_workspace_layout(path)
    return str(path)


def get_project_workspace_path(project: TenderProject) -> Path | None:
    wd = (getattr(project, "workspace_dir", None) or "").strip()
    if not wd:
        return None
    try:
        p = Path(wd).expanduser().resolve()
        if p.is_dir():
            return p
    except OSError:
        return None
    return None


def resolve_session_workspace_root(db: Session, session) -> Path:
    ws = getattr(session, "workspace", None) or {}
    pid = ws.get("project_id")
    if pid:
        project = db.query(TenderProject).filter(TenderProject.id == int(pid)).first()
        if project:
            proot = get_project_workspace_path(project)
            if proot:
                return proot
    explicit = (ws.get("workspace_dir") or "").strip()
    if explicit:
        return normalize_folder_path(explicit)
    return default_agent_workspace_root()


def normalize_relative_path(root: Path, relative: str) -> Path:
    rel = (relative or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        raise PathNotAllowedError("相对路径不能为空")
    if ".." in rel.split("/"):
        raise PathNotAllowedError("路径不允许包含 ..")
    if rel.startswith("//") or re.match(r"^[a-zA-Z]:", rel):
        raise PathNotAllowedError("请使用相对路径")
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as err:
        raise PathNotAllowedError("路径超出工程目录范围") from err
    return target


def list_workspace_dir(
    db: Session,
    session,
    relative_path: str = "",
) -> dict[str, Any]:
    """列出工程目录下某路径的直接子项（用于文件树懒加载）。"""
    root = resolve_session_workspace_root(db, session)
    rel = (relative_path or "").replace("\\", "/").strip().lstrip("/")
    if rel:
        base = normalize_relative_path(root, rel)
        if not base.is_dir():
            raise NotADirectoryError(f"不是文件夹：{relative_path}")
    else:
        base = root.resolve()

    entries: list[dict[str, Any]] = []
    try:
        children = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as err:
        raise FileNotFoundError(str(err)) from err

    for child in children:
        if child.name.startswith("."):
            continue
        rel_child = child.relative_to(root.resolve()).as_posix()
        entries.append({
            "name": child.name,
            "path": rel_child,
            "type": "dir" if child.is_dir() else "file",
        })

    return {
        "path": rel,
        "workspace_root": str(root),
        "entries": entries,
    }


def read_workspace_file(db: Session, session, relative_path: str) -> dict[str, Any]:
    root = resolve_session_workspace_root(db, session)
    target = normalize_relative_path(root, relative_path)
    if not target.is_file():
        raise FileNotFoundError(f"文件不存在：{relative_path}")
    data = target.read_bytes()
    ext = target.suffix.lstrip(".").lower()
    if ext in _TEXT_EXTENSIONS or ext == "":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return {
            "path": relative_path.replace("\\", "/"),
            "absolute_path": str(target),
            "size_bytes": len(data),
            "encoding": "utf-8",
            "content": text,
            "binary": False,
        }
    return {
        "path": relative_path.replace("\\", "/"),
        "absolute_path": str(target),
        "size_bytes": len(data),
        "encoding": "base64",
        "content": __import__("base64").b64encode(data).decode("ascii"),
        "binary": True,
    }


def write_workspace_file(
    db: Session,
    session,
    relative_path: str,
    content: str,
    *,
    encoding: str = "utf-8",
    mkdirs: bool = True,
) -> dict[str, Any]:
    root = resolve_session_workspace_root(db, session)
    target = normalize_relative_path(root, relative_path)
    if mkdirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    if encoding == "base64":
        raw = __import__("base64").b64decode(content.encode("ascii"))
    else:
        raw = content.encode(encoding or "utf-8")
    target.write_bytes(raw)
    return {
        "path": relative_path.replace("\\", "/"),
        "absolute_path": str(target),
        "size_bytes": len(raw),
        "workspace_root": str(root),
    }


def mirror_bytes_to_project_workspace(
    project: TenderProject,
    relative_path: str,
    data: bytes,
) -> str | None:
    root = get_project_workspace_path(project)
    if not root:
        return None
    target = normalize_relative_path(root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(target)


def chat_staging_dir(session_id: int, batch_id: str) -> Path:
    root = (Path(DATA_DIR) / "chat_staging" / str(session_id) / batch_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root

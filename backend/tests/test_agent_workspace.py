"""工程目录读写与路径约束。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from app.database import Base, SessionLocal, engine
from app.models import ChatSession, TenderProject
from app.services.agent_qual_folder import PathNotAllowedError
from app.services.agent_workspace import (
    default_agent_workspace_root,
    normalize_relative_path,
    read_workspace_file,
    write_workspace_file,
)


def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_default_workspace_created():
    root = default_agent_workspace_root()
    assert root.is_dir()
    assert (root / "过程资料").is_dir()
    assert (root / "产出").is_dir()


def test_relative_path_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_workspace.default_agent_workspace_root",
        lambda: tmp_path.resolve(),
    )
    root = tmp_path.resolve()
    with pytest.raises(PathNotAllowedError):
        normalize_relative_path(root, "../etc/passwd")


def test_write_and_read_session_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_workspace.default_agent_workspace_root",
        lambda: tmp_path.resolve(),
    )
    db = _fresh_db()
    session = ChatSession(title="t", workspace={})
    db.add(session)
    db.commit()
    write_workspace_file(db, session, "产出/notes.md", "# hello\n")
    out = read_workspace_file(db, session, "产出/notes.md")
    assert out["content"].startswith("# hello")
    db.close()


def test_project_workspace_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_qual_folder.allowed_path_prefixes",
        lambda: [tmp_path.resolve()],
    )
    from app.services.agent_workspace import validate_workspace_dir

    proj_dir = tmp_path / "bid-a"
    proj_dir.mkdir()
    validated = validate_workspace_dir(str(proj_dir))
    assert Path(validated).is_dir()

    db = _fresh_db()
    p = TenderProject(title="x", workspace_dir=validated)
    db.add(p)
    db.commit()
    session = ChatSession(title="s", workspace={"project_id": p.id})
    db.add(session)
    db.commit()
    write_workspace_file(db, session, "过程资料/log.txt", "ok")
    assert (proj_dir / "过程资料" / "log.txt").read_text(encoding="utf-8") == "ok"
    db.close()

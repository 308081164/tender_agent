"""Recent logs tail service."""
from pathlib import Path

from app.services.recent_logs import get_recent_logs


def test_tail_known_log(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.recent_logs.DATA_DIR", tmp_path)
    log = tmp_path / "launcher.log"
    log.write_text("alpha\nbeta\n", encoding="utf-8")
    body = get_recent_logs(max_lines=50)
    assert body["data_dir"] == str(tmp_path)
    assert "beta" in body["lines"]
    assert body["files"][0]["name"] == "launcher.log"


def test_missing_logs_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.recent_logs.DATA_DIR", tmp_path)
    body = get_recent_logs(max_lines=50)
    assert Path(body["data_dir"]) == tmp_path
    assert body["lines"] == []

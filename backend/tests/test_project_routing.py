"""项目路由与阶段命名（工作台 ↔ 向导）。"""
from app.routers.api import STEP_NAMES, _workspace_phase_name, _workspace_progress, project_summary
from app.models import TenderProject


def test_workspace_phase_names():
    assert _workspace_phase_name(3) == "Agent创作"
    assert _workspace_phase_name(4) == "AI审查"
    assert _workspace_phase_name(6) == "导出Word"
    assert _workspace_phase_name(6, "exported") == "导出Word"


def test_wizard_step_names_unchanged():
    assert STEP_NAMES[1] == "选择起点"
    assert STEP_NAMES[2] == "信息录入"


def test_project_summary_uses_workspace_phase():
    p = TenderProject(
        id=1,
        title="测试",
        current_step=4,
        fields={"project_name": "XX工程"},
        chapters={},
        status="draft",
    )
    s = project_summary(p)
    assert s["step_name"] == "AI审查"
    assert s["progress"] == _workspace_progress(4)

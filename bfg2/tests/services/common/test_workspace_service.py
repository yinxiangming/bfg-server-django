from types import SimpleNamespace

from bfg.common.services.workspace_service import WorkspaceService


def test_deactivate_workspace_marks_inactive():
    service = WorkspaceService(workspace=None, user=None)
    workspace = SimpleNamespace(is_active=True)
    state = {"saved": False}
    workspace.save = lambda: state.update({"saved": True})

    result = service.deactivate_workspace(workspace)
    assert result.is_active is False
    assert state["saved"] is True

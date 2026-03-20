from types import SimpleNamespace

from bfg.common.services.audit_service import AuditService


def test_log_create_delegates_to_log_action(monkeypatch):
    service = AuditService(workspace=SimpleNamespace(id=1), user=None)
    obj = SimpleNamespace(id=8, workspace_id=1)
    captured = {}

    monkeypatch.setattr(
        service,
        "log_action",
        lambda *args, **kwargs: captured.update({"args": args, **kwargs}) or "ok",
    )

    result = service.log_create(obj, description="created")
    assert result == "ok"
    assert captured["args"][0] == "create"

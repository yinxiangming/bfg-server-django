from io import StringIO

from django.core.management import call_command
from django.contrib.auth import get_user_model

from bfg.common.models import WorkspaceDomain, upsert_custom_workspace_domain
from bfg.common.services.workspace_service import WorkspaceService


User = get_user_model()



def test_sync_workspace_domains_reports_clean_state_for_single_primary_custom_domain(db):
    user = User.objects.create_user(username="sync-user", password="x")
    service = WorkspaceService(workspace=None, user=user)
    workspace = service.create_workspace(name="Sync WS", slug="sync-ws", owner_user=user)

    upsert_custom_workspace_domain(
        workspace,
        "one.sync.test",
        is_primary=True,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
    )
    upsert_custom_workspace_domain(
        workspace,
        "two.sync.test",
        is_primary=False,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        ssl_status=WorkspaceDomain.SSL_ACTIVE,
    )

    out = StringIO()
    call_command("sync_workspace_domains", "--workspace", "sync-ws", "--apply", stdout=out)

    primary_count = workspace.domains.filter(
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        is_primary=True,
    ).count()
    assert primary_count == 1
    assert "Domains repaired:" in out.getvalue()

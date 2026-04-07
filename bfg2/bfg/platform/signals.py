# -*- coding: utf-8 -*-
from django.db.models.signals import post_save
from django.dispatch import receiver

from bfg.common.models import ensure_system_default_workspace_domain
from bfg.platform.models import Cluster, WorkspacePlatformProfile


@receiver(post_save, sender=WorkspacePlatformProfile)
def ensure_system_default_domain_on_profile_save(sender, instance, **kwargs):
    workspace = getattr(instance, "workspace", None)
    if workspace:
        ensure_system_default_workspace_domain(workspace)


@receiver(post_save, sender=Cluster)
def ensure_system_default_domains_on_cluster_save(sender, instance, **kwargs):
    for workspace in instance.workspaces.select_related("workspace").values_list("workspace_id", flat=True):
        if workspace:
            from bfg.common.models import Workspace
            ws = Workspace.objects.filter(id=workspace).first()
            if ws:
                ensure_system_default_workspace_domain(ws)

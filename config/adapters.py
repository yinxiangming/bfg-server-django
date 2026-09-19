from types import SimpleNamespace

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site


class ClusterAccountAdapter(DefaultAccountAdapter):
    """Use the hosting Cluster brand in account emails instead of a platform vendor name."""

    def send_mail(self, template_prefix, email, context):
        request = getattr(self, 'request', None)
        site = get_current_site(request) if request is not None else None
        context = dict(context)
        context['current_site'] = SimpleNamespace(
            name=self._cluster_name(site),
            domain=getattr(site, 'domain', '') or '',
        )
        message = self.render_mail(template_prefix, email, context)
        message.send()

    @staticmethod
    def _cluster_name(site):
        configured = str(getattr(settings, 'CLUSTER_NAME', '') or '').strip()
        if configured:
            return configured
        try:
            from bfg.platform.models import Cluster

            cluster = Cluster.objects.filter(is_active=True).order_by('id').first()
            if cluster and cluster.name:
                return cluster.name.strip()
        except Exception:
            pass
        fallback = str(getattr(settings, 'SITE_NAME', '') or '').strip()
        if fallback.lower() in {'surlex', 'surlex limited'}:
            return 'Idlevo'
        return fallback or 'Idlevo'

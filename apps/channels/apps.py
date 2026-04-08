# -*- coding: utf-8 -*-
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ChannelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.channels"
    label = "channels"
    verbose_name = _("Channels")

    def ready(self):
        from apps.channels import handlers  # noqa: F401
        self._register_beat_schedule()

    def _register_beat_schedule(self) -> None:
        """Register Celery Beat periodic tasks when the app is ready."""
        try:
            from celery import current_app
            from celery.schedules import crontab
        except ImportError:
            return  # Celery not installed — skip

        current_app.conf.beat_schedule.update({
            # Pull feedback for all active listings — every hour
            "channels-fetch-feedback": {
                "task": "apps.channels.tasks.periodic_fetch_feedback",
                "schedule": crontab(minute=0),
            },
            # Pull buyer questions every 15 minutes
            "channels-fetch-questions": {
                "task": "apps.channels.tasks.periodic_fetch_questions",
                "schedule": crontab(minute="*/15"),
            },
            # Check for expiring listings — daily at 2 AM
            "channels-relist-check": {
                "task": "apps.channels.tasks.periodic_relist_check",
                "schedule": crontab(hour=2, minute=0),
            },
        })

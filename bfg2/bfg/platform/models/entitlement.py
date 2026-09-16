# -*- coding: utf-8 -*-
"""
What a workspace has paid for, or been given.

An entitlement is the answer to "may this workspace use this at all", kept apart
from whether it has switched the thing on: a workspace can deactivate an add-on it
still pays for, and an add-on whose payment lapsed stays activated but unavailable
until the entitlement is renewed.
"""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bfg.common.managers import TenantScopedModel


class WorkspaceEntitlement(TenantScopedModel):
    """One thing a workspace is entitled to, for one period.

    ``key`` is the key of an add-on extension, or ``KEY_BASE_PLAN`` (the empty
    string) for the base plan itself. An extension key can never be empty, so the
    two can never collide.

    Renewal writes a new row rather than moving an old one, so what a workspace was
    entitled to last quarter survives. ``current_period_end`` empty means the
    entitlement does not expire, which is how an indefinite grant is recorded;
    ``grace_until`` is how long an entitlement already moved to ``grace`` keeps
    working. A row still marked ``active`` whose period has run out keeps working
    for the deployment's ``grace_days`` and no longer, so an entitlement lapses
    on time rather than on something remembering to sweep it — see ``is_live``.

    Scoping works the way ``UsageRecord``'s does: entitlement questions are asked
    from scheduled work and from the platform console, neither of which has a
    workspace bound to the thread, so the services read ``all_objects`` and filter
    by workspace themselves.
    """

    # The base plan, as opposed to a named add-on extension.
    KEY_BASE_PLAN = ""

    SOURCE_PURCHASED = "purchased"
    SOURCE_GRANTED = "granted"
    SOURCE_CHOICES = (
        (SOURCE_PURCHASED, _("Purchased")),
        (SOURCE_GRANTED, _("Granted")),
    )

    STATUS_ACTIVE = "active"
    # Paid up until recently; still usable while the deployment waits for payment.
    STATUS_GRACE = "grace"
    STATUS_ENDED = "ended"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, _("Active")),
        (STATUS_GRACE, _("Grace")),
        (STATUS_ENDED, _("Ended")),
    )

    workspace = models.ForeignKey(
        "common.Workspace",
        verbose_name=_("Workspace"),
        on_delete=models.CASCADE,
        related_name="entitlements",
    )
    key = models.CharField(_("Key"), max_length=64, blank=True)
    plan = models.ForeignKey(
        "shop.SubscriptionPlan",
        verbose_name=_("Plan"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entitlements",
        help_text=_("Empty for an entitlement that was granted rather than bought."),
    )
    source = models.CharField(
        _("Source"), max_length=16, choices=SOURCE_CHOICES, default=SOURCE_PURCHASED
    )
    starts_at = models.DateTimeField(_("Starts At"), default=timezone.now)
    current_period_end = models.DateTimeField(
        _("Current Period End"), null=True, blank=True,
        help_text=_("Empty never expires."),
    )
    grace_until = models.DateTimeField(_("Grace Until"), null=True, blank=True)
    status = models.CharField(
        _("Status"), max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    reason = models.CharField(
        _("Reason"), max_length=255, blank=True,
        help_text=_("Why the entitlement exists, for one that was granted."),
    )
    ended_reason = models.CharField(_("Ended Reason"), max_length=255, blank=True)
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        verbose_name = _("Workspace Entitlement")
        verbose_name_plural = _("Workspace Entitlements")
        ordering = ["key", "-starts_at"]
        indexes = [
            models.Index(fields=["workspace", "key", "status"]),
            models.Index(fields=["status", "current_period_end"]),
        ]
        base_manager_name = "all_objects"

    def __str__(self):
        return f"{self.key or 'base plan'} @ workspace {self.workspace_id} ({self.status})"

    def is_live(self, at=None) -> bool:
        """Whether this row grants use of its key at ``at`` (default now).

        The rule lives in ``bfg.platform.services.entitlements.live_filter`` and is
        applied to this row rather than repeated here, so that one row and a list
        of them can never disagree. That costs a lookup by primary key, which is
        what makes it right for a row in hand and wrong for a list: filter the
        queryset with ``live_filter`` instead.
        """
        from bfg.platform.services.entitlements import live_filter

        return type(self).all_objects.filter(pk=self.pk).filter(live_filter(at)).exists()

# -*- coding: utf-8 -*-
"""
The autocomplete sessions that have not been paid for yet.

Google bills address autocomplete by the *session*, not by the request: the
keystrokes a shopper types are free when the session ends in a chosen address,
because the place details call that follows is charged for the whole session
instead. Only a session the shopper walks away from is billed, and then per
autocomplete request.

So an autocomplete request cannot be metered when it is made — at that moment
nobody knows yet which of the two it will turn out to be. A row here is one
session that is still undecided: it counts the requests made so far and remembers
when the last one was. Picking an address deletes the row unbilled
(:func:`apps.geo.services.billing.close_session`); going quiet for long enough
means the shopper left, and the row is billed and deleted
(:func:`apps.geo.services.billing.settle_abandoned`).

The table therefore stays small by construction — a row lives for as long as one
person is filling in one address field — and it is the extension's own, kept out
of the platform's usage tables, which record money that has already been decided.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bfg.common.managers import TenantScopedModel


class AutocompleteSession(TenantScopedModel):
    """One address-lookup session whose autocomplete requests are not yet billed.

    ``token`` is the session token the client generates and sends with every
    request of one lookup; it is what ties the keystrokes and the eventual details
    call together at Google, so it is what they are counted against here too. It
    is only ever matched exactly, and only within one workspace: two workspaces
    that happen to mint the same token keep separate rows and separate bills.

    Rows are written through ``all_objects`` with an explicit workspace filter
    rather than through the scoped ``objects`` manager, as the platform's usage
    tables are. A ``get_or_create`` against a scoped manager with no workspace
    bound to the thread would find nothing and insert a duplicate, and this row is
    a count of money owed.
    """

    workspace = models.ForeignKey(
        'common.Workspace',
        verbose_name=_('Workspace'),
        on_delete=models.CASCADE,
        related_name='address_autocomplete_sessions',
    )
    token = models.CharField(
        _('Session Token'),
        max_length=64,
        help_text=_('The provider session token the client sent with these requests.'),
    )
    request_count = models.PositiveIntegerField(
        _('Autocomplete Requests'),
        default=0,
        help_text=_('Autocomplete requests made in this session, billable only if it is abandoned.'),
    )
    started_at = models.DateTimeField(_('Started At'), default=timezone.now)
    last_request_at = models.DateTimeField(
        _('Last Request At'),
        default=timezone.now,
        help_text=_('When this session was last used; how an abandoned session is recognised.'),
    )

    class Meta:
        verbose_name = _('Autocomplete Session')
        verbose_name_plural = _('Autocomplete Sessions')
        ordering = ['-last_request_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'token'],
                name='geo_autocomplete_session_uniq',
            ),
        ]
        indexes = [
            # Every request sweeps its own workspace for sessions that have gone
            # quiet; this is the index that keeps the sweep off the table itself.
            models.Index(fields=['workspace', 'last_request_at']),
        ]
        base_manager_name = 'all_objects'

    def __str__(self):
        return f'{self.token} × {self.request_count} (workspace {self.workspace_id})'

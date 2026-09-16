# -*- coding: utf-8 -*-
"""
The part of the console only the people who run the deployment may use.

GET    /api/v1/platform/console/variables/                        every variable, with its default and what it is now
PATCH  /api/v1/platform/console/variables/{key}/                  body: {"value": ..., "reason": "..."}
GET    /api/v1/platform/console/meter-prices/                     ?meter=KEY narrows it to one
POST   /api/v1/platform/console/meter-prices/                     body: {"meter", "vendor_cost", "unit_size", "margin"?, "effective_from"?}
GET    /api/v1/platform/console/exchange-rates/                   ?base=USD&currency=NZD&limit=50
POST   /api/v1/platform/console/exchange-rates/                   body: {"from", "to", "rate", "effective_date"?}
GET    /api/v1/platform/console/workspaces/{id}/usage-cap/
PATCH  /api/v1/platform/console/workspaces/{id}/usage-cap/        body: {"cap_points": "50"} or {"cap_points": null}
POST   /api/v1/platform/console/workspaces/{id}/grants/           body: {"key", "months" | "never_expires", "reason"}

The console proper is shared with workspace owners; none of this is. These set what
every workspace on the deployment is charged by, and give one workspace something
it has not paid for, so an owner is refused all of it with 403
``platform_admin_required`` — the same answer for a workspace they own, one they
do not, and one that does not exist, which is what keeps the refusal from telling
them which. A platform administrator naming a workspace that does not exist is
answered 404 ``workspace_not_found``, exactly as the rest of the console answers
one it cannot reach.

The two workspace paths sit under the console's own ``workspaces`` prefix, so that
what a platform administrator does to a workspace reads as part of the same
resource; see ``urls.py`` for why the registration order there matters.

Every refusal is ``{"code", "detail"}`` and may carry more about what was wrong.
The codes are:

``platform_admin_required``   403, for anyone who does not administer the platform
``workspace_not_found``       404, for a workspace id that is not one
``unknown_platform_variable`` 404, for a variable this deployment does not declare
``invalid_platform_variable`` 400, for a value that variable cannot hold
``reason_required``           400, for a change or a grant nobody would say why they made
``invalid_meter_price``       400, for a price the columns cannot hold
``invalid_exchange_rate``     400, for a rate that is not a positive number, or a currency that is not one
``invalid_usage_cap``         400, for a cap the column cannot hold
``invalid_grant``             400, for a grant that names no period, or both, or an impossible one
``unknown_extension``         400, for a key no deployed extension declares
``already_entitled``          409, for a workspace that already holds what is being granted

Nothing here edits a price or a variable's history: a price is only ever added
(``/meter-prices/`` takes GET and POST and has no detail route at all), and a
change to a variable is written to its trail rather than over the last one. That
is what lets a bill issued months ago still be explained by the rows it was
calculated from.

Platform paths are public, so no workspace is bound to these requests: everything
reads ``all_objects`` and filters by workspace itself. The one thing that runs a
workspace's own code — resuming an extension after a grant — binds that workspace
while it does, which ``console_admin`` takes care of rather than the view.
"""
from collections.abc import Mapping
from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from bfg.platform.models.entitlement import WorkspaceEntitlement
from bfg.platform.models.variables import PlatformVariableChange
from bfg.platform.permissions import IsPlatformAdmin
from bfg.platform.services import console_admin, exchange_rates, pricing, usage
from bfg.platform.services import platform_variables as variables
from bfg.platform.views.console_views import WORKSPACE_NOT_FOUND

PLATFORM_ADMIN_REQUIRED = 'platform_admin_required'
REASON_REQUIRED = 'reason_required'
INVALID_GRANT = 'invalid_grant'

# Longer than this is what an entitlement with no end is for, and a number this
# large is far more often a typo than a decade somebody meant to give away.
MAX_GRANT_MONTHS = 120

#: How long a reason may be: the shorter of the two columns that have to hold one,
#: read off them so that neither can be overrun by a reason this accepted.
REASON_MAX_LENGTH = min(
    PlatformVariableChange._meta.get_field('reason').max_length,
    WorkspaceEntitlement._meta.get_field('reason').max_length,
)


class _MayAdministerPlatform(IsPlatformAdmin):
    """``IsPlatformAdmin``, refusing with a code the console can act on.

    DRF sends a dict message as the response body, which is how the code reaches
    the client next to the detail.
    """

    message = {
        'code': PLATFORM_ADMIN_REQUIRED,
        'detail': 'Only platform administrators can use this part of the console.',
    }


def _body(request) -> dict:
    """The request body as a mapping, or a refusal for anything else."""
    if not isinstance(request.data, Mapping):
        raise ValidationError({'code': 'invalid_body', 'detail': 'Send the change as a JSON object.'})
    return request.data


def _refused(exc, http_status):
    """A service's refusal as the body the console reads: its code, what it said, and why."""
    return Response({'code': exc.code, 'detail': exc.message, **exc.details}, status=http_status)


def _reason(data, code=REASON_REQUIRED) -> str:
    """The reason the caller gave, refused when they gave none.

    Required rather than optional because the record of who changed what is worth
    little without it: these are the numbers a deployment bills by, and "why is
    the margin 0.45" has to be answerable by the row itself a year later.
    """
    reason = data.get('reason')
    reason = reason.strip() if isinstance(reason, str) else ''
    if not reason:
        raise ValidationError({'code': code, 'detail': 'Say why this is being done.'})
    if len(reason) > REASON_MAX_LENGTH:
        raise ValidationError({
            'code': code,
            'detail': f'A reason is at most {REASON_MAX_LENGTH} characters.',
        })
    return reason


def _moment(value, field, code):
    """``value`` as an aware datetime, or ``None`` when it was left out.

    A date on its own is midnight on that day, and a time with no offset is read
    in the deployment's own time zone rather than guessed at as UTC.
    """
    if value is None or value == '':
        return None
    try:
        moment = parse_datetime(str(value))
        if moment is None:
            day = parse_date(str(value))
            moment = datetime.combine(day, time.min) if day else None
    except ValueError:
        # Well formed but impossible, such as the 31st of February.
        moment = None
    if moment is None:
        raise ValidationError({
            'code': code,
            'detail': f'{field} is a date or a timestamp (2026-10-01, 2026-10-01T00:00:00Z).',
        })
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


def _day(value, field, code):
    """``value`` as a date, or ``None`` when it was left out."""
    if value is None or value == '':
        return None
    try:
        day = parse_date(str(value))
    except ValueError:
        day = None
    if day is None:
        raise ValidationError({'code': code, 'detail': f'{field} is a date (2026-10-01).'})
    return day


class ConsolePlatformVariableViewSet(viewsets.GenericViewSet):
    """The deployment's own numbers: margins, grace periods, retention, the default cap."""

    permission_classes = [_MayAdministerPlatform]
    lookup_field = 'key'
    lookup_value_regex = r'[a-z][a-z0-9_]*'

    def list(self, request):
        """Every variable the deployment declares, whether or not anything has set it.

        Each entry carries the ``default`` it would have with no row, the ``value``
        in force now, what kind of number it is, what it means, and the last change
        made to it with the reason its author gave.

        A ``decimal`` variable's values are strings rather than JSON numbers, for
        the reason ``console_billing`` gives: they are multiplied into money.
        ``int`` and ``bool`` variables are themselves.
        """
        return Response(console_admin.variable_entries())

    def partial_update(self, request, key=None):
        """Override one variable, recording who changed it and why.

        The body is ``{"value": ..., "reason": "..."}``. A reason is required: the
        change is kept for as long as the bills it explains. A key this deployment
        does not declare is 404 rather than stored — it is a typo, not a new
        setting — and a value the variable cannot hold is 400.
        """
        data = _body(request)
        if 'value' not in data:
            raise ValidationError({
                'code': variables.InvalidPlatformVariable.default_code,
                'detail': 'Send the new value as {"value": ..., "reason": "..."}.',
            })
        reason = _reason(data)
        try:
            entry = console_admin.change_variable(key, data['value'], user=request.user, reason=reason)
        except variables.UnknownPlatformVariable as unknown:
            return _refused(unknown, status.HTTP_404_NOT_FOUND)
        except variables.InvalidPlatformVariable as invalid:
            return _refused(invalid, status.HTTP_400_BAD_REQUEST)
        return Response(entry)


class ConsoleMeterPriceViewSet(viewsets.GenericViewSet):
    """What each meter costs, and what it used to.

    Add-only by construction: there is no detail route, so no request can edit or
    delete a price. A vendor's new rate is a new row with a later
    ``effective_from``, which is what lets a bill already calculated still be
    explained by the row it was calculated from.
    """

    permission_classes = [_MayAdministerPlatform]

    def list(self, request):
        """Every meter's whole price history, newest first, with the live row marked.

        ``?meter=KEY`` narrows it to one. ``in_force`` on each meter is the id of
        the price a call would be billed at right now, and ``null`` for a meter
        whose every price starts later — which is what a price entered with the
        wrong date looks like, and until one starts nothing is billed for it.
        """
        return Response(console_admin.meter_price_entries(request.query_params.get('meter')))

    def create(self, request):
        """Price a meter from a moment on, without touching what it cost before.

        The body is ``{"meter", "vendor_cost", "unit_size", "margin"?,
        "effective_from"?}``. ``vendor_cost`` is what the vendor charges for one
        ``unit_size`` of the meter, so a rate quoted per million tokens is
        ``unit_size`` 1000000; it is required rather than defaulted to 1, because
        a price entered without it would be a million times too high. ``margin``
        left out follows the deployment's ``usage_margin``, and a change to that
        then moves this price too. ``effective_from`` is now by default.

        The answer is the whole meter, not only the row written, because a price
        dated behind one that already exists changes nothing today and the entry
        says which row is in force.
        """
        data = _body(request)
        code = pricing.InvalidMeterPrice.default_code
        for field in ('meter', 'vendor_cost', 'unit_size'):
            if data.get(field) in (None, ''):
                raise ValidationError({
                    'code': code,
                    'detail': f'{field} is required to price a meter.',
                    'field': field,
                })
        try:
            entry = console_admin.add_meter_price(
                str(data['meter']).strip(),
                vendor_cost=data['vendor_cost'],
                unit_size=data['unit_size'],
                margin=data.get('margin'),
                effective_from=_moment(data.get('effective_from'), 'effective_from', code),
            )
        except pricing.InvalidMeterPrice as invalid:
            return _refused(invalid, status.HTTP_400_BAD_REQUEST)
        return Response(entry, status=status.HTTP_201_CREATED)


class ConsoleExchangeRateViewSet(viewsets.GenericViewSet):
    """The rates bills are converted at, and a way to enter one the feed missed."""

    permission_classes = [_MayAdministerPlatform]

    def list(self, request):
        """The rates most recently stored, newest day first.

        ``?base=`` and ``?currency=`` narrow it to one side of a pair, ``?limit=``
        asks for more or fewer than the default. ``source`` says whether a row was
        read from the reference feed or entered by hand.
        """
        return Response(
            console_admin.exchange_rate_entries(
                base=request.query_params.get('base'),
                currency=request.query_params.get('currency'),
                limit=_limit(request.query_params.get('limit')),
            )
        )

    def create(self, request):
        """Enter a rate by hand, for a day the feed could not be read for.

        The body is ``{"from", "to", "rate", "effective_date"?}``, the date being
        today by default. The row records that it was typed rather than published,
        because a bill has to be explainable long afterwards. A day already stored
        is overwritten rather than duplicated, and a later refresh that does reach
        the feed replaces it with the published number: this is a stand-in, not an
        override that sticks.
        """
        data = _body(request)
        code = exchange_rates.InvalidExchangeRate.default_code
        for field in ('from', 'to', 'rate'):
            if data.get(field) in (None, ''):
                raise ValidationError({
                    'code': code,
                    'detail': f'{field} is required to store a rate.',
                    'field': field,
                })
        try:
            entry = console_admin.set_exchange_rate(
                str(data['from']),
                str(data['to']),
                data['rate'],
                on=_day(data.get('effective_date'), 'effective_date', code),
                user=request.user,
            )
        except exchange_rates.InvalidExchangeRate as invalid:
            return _refused(invalid, status.HTTP_400_BAD_REQUEST)
        return Response(entry, status=status.HTTP_201_CREATED)


def _limit(value):
    """``?limit=`` as a number of rows, or the default for anything that is not one.

    Not refused: a listing is a listing, and a console asking for ``limit=many``
    is better served the first page than an error. What it may ask for at most is
    ``console_admin``'s to decide.
    """
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return console_admin.RATES_DEFAULT_LIMIT


class ConsoleWorkspaceAdminViewSet(viewsets.GenericViewSet):
    """What a platform administrator decides for one workspace, and its owner may not.

    Only the two actions below; everything else about a workspace is
    ``ConsoleWorkspaceViewSet``, which owners share.
    """

    permission_classes = [_MayAdministerPlatform]
    lookup_value_regex = r'[0-9]+'

    @action(detail=True, methods=['get', 'patch'], url_path='usage-cap')
    def usage_cap(self, request, pk=None):
        """Read or set how many points of metered usage this workspace may run up a month.

        ``cap_points`` is the workspace's own and is ``null`` for one that follows
        the deployment's ``monthly_usage_cap_points``; ``effective_cap_points`` is
        what is actually enforced and ``source`` says which of the two it came
        from. PATCH ``{"cap_points": null}`` puts a workspace back on the default,
        which is not the same as ``{"cap_points": "0"}`` — a cap of zero stops it
        metering anything at all.
        """
        workspace = self._workspace(pk)
        if request.method.lower() == 'get':
            return Response(console_admin.usage_cap_entry(workspace))

        data = _body(request)
        if 'cap_points' not in data:
            raise ValidationError({
                'code': usage.InvalidUsageCap.default_code,
                'detail': 'Send the cap as {"cap_points": "50"}, or null to follow the default.',
            })
        try:
            entry = console_admin.set_usage_cap(workspace, data['cap_points'])
        except usage.InvalidUsageCap as invalid:
            return _refused(invalid, status.HTTP_400_BAD_REQUEST)
        return Response(entry)

    @action(detail=True, methods=['post'])
    def grants(self, request, pk=None):
        """Give this workspace an entitlement it has not bought.

        The body is ``{"key", "months" | "never_expires", "reason"}``. ``key`` is
        an add-on's extension key, or ``""`` for the base plan; it is required
        even when empty, so that a body that forgot it does not quietly hand out a
        plan. Exactly one of ``months`` (a whole number, at most ``MAX_GRANT_MONTHS``)
        and ``never_expires`` says how long it runs. A reason is required, and is
        kept on the row.

        A workspace that already holds a live entitlement to the key is refused
        with 409 ``already_entitled``, carrying the entitlement it already has,
        rather than given a second row to renew and explain.

        The extension is **not** switched on, except one the platform itself
        paused when an entitlement ran out, which is resumed; ``extension`` in the
        answer says which happened. See ``console_admin.grant_entitlement``.
        """
        workspace = self._workspace(pk)
        data = _body(request)
        key = self._key(data)
        months = self._months(data)
        reason = _reason(data, INVALID_GRANT)
        try:
            granted = console_admin.grant_entitlement(
                workspace, key, months=months, reason=reason, user=request.user
            )
        except console_admin.AlreadyEntitled as held:
            return _refused(held, status.HTTP_409_CONFLICT)
        return Response(granted, status=status.HTTP_201_CREATED)

    # ── Reading the request ──────────────────────────────────────────

    def _workspace(self, pk):
        """The workspace being administered, or 404 as the rest of the console answers."""
        from bfg.common.models import Workspace

        workspace = Workspace.objects.filter(pk=pk).first()
        if workspace is None:
            raise NotFound({'code': WORKSPACE_NOT_FOUND, 'detail': 'Workspace not found.'})
        return workspace

    @staticmethod
    def _key(data) -> str:
        key = data.get('key')
        if key is None or not isinstance(key, str):
            raise ValidationError({
                'code': INVALID_GRANT,
                'detail': 'Name what is being granted as "key", or "" for the base plan.',
            })
        key = key.strip()
        if not console_admin.extension_key_exists(key):
            raise ValidationError({
                'code': console_admin.UNKNOWN_EXTENSION,
                'detail': f'No extension named {key}.',
                'key': key,
            })
        return key

    @staticmethod
    def _months(data):
        """How many months the grant runs, or ``None`` for one that does not expire."""
        months, never = data.get('months'), data.get('never_expires')
        if never not in (None, True, False):
            raise ValidationError({
                'code': INVALID_GRANT, 'detail': 'never_expires is true or false.',
            })
        if bool(never) == (months is not None):
            raise ValidationError({
                'code': INVALID_GRANT,
                'detail': 'Give either months or never_expires, not both and not neither.',
            })
        if never:
            return None
        # ``True`` is an int in Python, and granting one month because somebody
        # sent a boolean is worse than refusing it.
        if isinstance(months, bool) or not isinstance(months, int):
            raise ValidationError({
                'code': INVALID_GRANT, 'detail': 'months is a whole number of months.',
            })
        if not 1 <= months <= MAX_GRANT_MONTHS:
            raise ValidationError({
                'code': INVALID_GRANT,
                'detail': f'months is from 1 to {MAX_GRANT_MONTHS}; longer is what never_expires is for.',
            })
        return months

# -*- coding: utf-8 -*-
"""Platform-admin workspace console endpoints.

These endpoints deliberately expose lifecycle controls without exposing cluster
credentials or allowing a hard delete from the web console.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import dateparse, timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bfg.platform.permissions import IsPlatformSuperuser
from bfg.platform.services.audit_service import record_platform_audit, redact_platform_audit_value
from bfg.platform.services.configuration_service import (
    PLATFORM_VARIABLES,
    platform_variable_decimal,
    platform_variable_item,
    validate_platform_variable,
)
from bfg.platform.services.provision_service import suspend_workspace, resume_workspace
from bfg.platform.utils import is_embedded_mode, is_platform_workspace
from bfg.common.exceptions import WorkspaceCapacityUnavailable
from bfg.common.models import normalize_hostname
from bfg.common.services.workspace_service import WorkspaceService
from bfg.common.services.user_service import UserService


def _change_reason(request):
    """Require an operator explanation for every state-changing console request."""
    reason = str(
        request.data.get("reason")
        or request.headers.get("X-Platform-Change-Reason")
        or ""
    ).strip()
    if len(reason) < 3:
        raise ValidationError({"reason": "Provide a change reason of at least 3 characters."})
    return reason[:500]


def _confirmed(request):
    if request.data.get("confirm") is not True:
        raise ValidationError({"confirm": "confirm=true is required."})


def _cluster_snapshot(cluster):
    """Return auditable cluster state without connection secrets."""
    return {
        "id": cluster.id,
        "name": cluster.name,
        "region": cluster.region,
        "api_base_url": cluster.api_base_url,
        "frontend_base_url": cluster.frontend_base_url,
        "db_host": cluster.db_host,
        "db_port": cluster.db_port,
        "redis_configured": bool(cluster.redis_url),
        "s3_bucket": cluster.s3_bucket,
        "max_workspaces": cluster.max_workspaces,
        "is_accepting_new": cluster.is_accepting_new,
        "is_active": cluster.is_active,
        "config_version": cluster.config_version,
    }


def _decimal(value, *, minimum=None, maximum=None, places=None):
    """Parse a finite decimal without passing through floating-point JSON."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"value": "Use a decimal number."}) from exc
    if not result.is_finite() or (minimum is not None and result < minimum) or (
        maximum is not None and result > maximum
    ):
        raise ValidationError({"value": "Use a value in the permitted range."})
    return result.quantize(Decimal(places)) if places is not None else result


def _decimal_text(value):
    return format(value, "f")


def _automatic_reason(request, fallback):
    """Keep a useful audit reason for compact forms without a reason field."""
    reason = str(request.data.get("reason") or request.headers.get("X-Platform-Change-Reason") or "").strip()
    return reason[:500] or fallback


def _changer(user):
    return {"id": user.id, "username": user.username} if user else None


def _parse_effective_from(value):
    if value in (None, ""):
        return None
    parsed = dateparse.parse_datetime(str(value))
    if not parsed:
        raise ValidationError({"effective_from": "Use an ISO-8601 date and time."})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _add_months(moment, months):
    """Keep a grant on the same calendar day where that day exists."""
    month = moment.month - 1 + months
    year = moment.year + month // 12
    month = month % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, monthrange(year, month)[1]))


class PlatformConsoleVariableViewSet(viewsets.ViewSet):
    """Typed Platform variables, overridden by Django superusers only."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]
    lookup_field = "key"

    def list(self, request):
        return Response([platform_variable_item(key) for key in sorted(PLATFORM_VARIABLES)])

    def partial_update(self, request, key=None):
        if key not in PLATFORM_VARIABLES:
            return Response(
                {"detail": "This Platform variable is not declared.", "code": "unknown_platform_variable"},
                status=status.HTTP_404_NOT_FOUND,
            )
        reason = _change_reason(request)
        try:
            value = validate_platform_variable(key, request.data.get("value"))
        except ValueError as exc:
            return Response(
                {"detail": str(exc), "code": "invalid_platform_variable"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Override = apps.get_model("platform", "PlatformVariableOverride")
        Change = apps.get_model("platform", "PlatformVariableChange")
        with transaction.atomic():
            current = Override.objects.select_for_update().filter(key=key).first()
            old_value = current.value if current else PLATFORM_VARIABLES[key]["default"]
            if old_value != value:
                if current:
                    current.value = value
                    current.reason = reason
                    current.updated_by = request.user
                    current.save(update_fields=["value", "reason", "updated_by", "updated_at"])
                else:
                    Override.objects.create(key=key, value=value, reason=reason, updated_by=request.user)
                Change.objects.create(
                    key=key, old_value=old_value, new_value=value, reason=reason, changed_by=request.user,
                )
                record_platform_audit(
                    request=request, action="configuration.variable_updated", target_type="platform_variable",
                    target_id=key, reason=reason, before={"value": old_value}, after={"value": value},
                )
        return Response(platform_variable_item(key))


class PlatformConsoleMeterPriceViewSet(viewsets.ViewSet):
    """Append-only pricing history for every metered Platform capability."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]

    @staticmethod
    def _price_item(price):
        effective_margin = price.margin if price.margin is not None else platform_variable_decimal("default_meter_margin")
        points_per_unit = ((price.vendor_cost / Decimal(price.unit_size)) * (Decimal("1") + effective_margin)).quantize(
            Decimal("0.0000000001")
        )
        return {
            "id": price.id,
            "vendor_cost": _decimal_text(price.vendor_cost),
            "unit_size": price.unit_size,
            "margin": _decimal_text(price.margin) if price.margin is not None else None,
            "effective_margin": _decimal_text(effective_margin),
            "uses_default_margin": price.margin is None,
            "points_per_unit": _decimal_text(points_per_unit),
            "effective_from": price.effective_from,
            "created_at": price.created_at,
        }

    @classmethod
    def _group_items(cls, prices):
        now = timezone.now()
        grouped = {}
        for price in prices:
            grouped.setdefault(price.meter, []).append(price)
        response = []
        for meter in sorted(grouped):
            rows = grouped[meter]
            active = [row for row in rows if row.effective_from is None or row.effective_from <= now]
            current = max(active, key=lambda row: (row.effective_from or row.created_at, row.id)) if active else None
            response.append({
                "meter": meter,
                "in_force": current.id if current else None,
                "prices": [
                    {**cls._price_item(row), "in_force": bool(current and row.id == current.id)}
                    for row in rows
                ],
            })
        return response

    def list(self, request):
        MeterPrice = apps.get_model("platform", "PlatformMeterPrice")
        meter = (request.query_params.get("meter") or "").strip()
        if len(meter) > 100:
            raise ValidationError({"meter": "Use a meter key of 100 characters or fewer."})
        prices = MeterPrice.objects.filter(meter=meter) if meter else MeterPrice.objects.all()
        return Response(self._group_items(list(prices.order_by("meter", "-effective_from", "-created_at", "-id"))))

    def create(self, request):
        meter = str(request.data.get("meter") or "").strip()
        if not meter or len(meter) > 100:
            return Response({"detail": "Use a meter key of 1 to 100 characters.", "code": "invalid_meter_price"}, status=400)
        try:
            cost = _decimal(request.data.get("vendor_cost"), minimum=Decimal("0.00000001"), places="0.00000001")
            unit_size = int(request.data.get("unit_size"))
            if unit_size < 1:
                raise ValueError
            raw_margin = request.data.get("margin")
            margin = None if raw_margin in (None, "") else _decimal(
                raw_margin, minimum=Decimal("0"), maximum=Decimal("1"), places="0.000001"
            )
            effective_from = _parse_effective_from(request.data.get("effective_from"))
        except (ValidationError, TypeError, ValueError):
            return Response({"detail": "Check the cost, unit size, margin, and effective date.", "code": "invalid_meter_price"}, status=400)
        MeterPrice = apps.get_model("platform", "PlatformMeterPrice")
        reason = _automatic_reason(request, f"Added a price for meter {meter}.")
        price = MeterPrice.objects.create(
            meter=meter, vendor_cost=cost, unit_size=unit_size, margin=margin,
            effective_from=effective_from, created_by=request.user,
        )
        record_platform_audit(
            request=request, action="configuration.meter_price_added", target_type="meter",
            target_id=meter, reason=reason,
            after={"price_id": price.id, "vendor_cost": _decimal_text(cost), "unit_size": unit_size,
                   "margin": _decimal_text(margin) if margin is not None else None,
                   "effective_from": effective_from.isoformat() if effective_from else None},
        )
        return Response(self._group_items(list(MeterPrice.objects.filter(meter=meter)))[0], status=status.HTTP_201_CREATED)


class PlatformConsoleExchangeRateViewSet(viewsets.ViewSet):
    """Global finance rates with a traceable manual fallback for a missing feed day."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]
    _DEFAULT_LIMIT = 50
    _MAX_LIMIT = 200

    @staticmethod
    def _currency_code(value, field):
        code = str(value or "").strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValidationError({field: "Use a three-letter currency code."})
        return code

    @staticmethod
    def _item(rate):
        return {
            "id": rate.id,
            "from": rate.from_currency.code,
            "to": rate.to_currency.code,
            "rate": _decimal_text(rate.rate),
            "effective_date": rate.effective_date,
            "source": rate.source,
            "entered_by": _changer(rate.entered_by),
        }

    def list(self, request):
        try:
            limit = int(request.query_params.get("limit", self._DEFAULT_LIMIT))
        except (TypeError, ValueError):
            raise ValidationError({"limit": "Use a whole number between 1 and 200."})
        if not 1 <= limit <= self._MAX_LIMIT:
            raise ValidationError({"limit": "Use a whole number between 1 and 200."})
        ExchangeRate = apps.get_model("finance", "ExchangeRate")
        rates = ExchangeRate.objects.select_related("from_currency", "to_currency", "entered_by").order_by(
            "-effective_date", "-id"
        )
        if request.query_params.get("base"):
            rates = rates.filter(from_currency__code=self._currency_code(request.query_params["base"], "base"))
        if request.query_params.get("currency"):
            rates = rates.filter(to_currency__code=self._currency_code(request.query_params["currency"], "currency"))
        return Response([self._item(rate) for rate in rates[:limit]])

    def create(self, request):
        try:
            from_code = self._currency_code(request.data.get("from"), "from")
            to_code = self._currency_code(request.data.get("to"), "to")
            if from_code == to_code:
                raise ValidationError({"to": "Choose a different currency."})
            rate_value = _decimal(request.data.get("rate"), minimum=Decimal("0.000001"), places="0.000001")
            effective_date = date.fromisoformat(str(request.data.get("effective_date") or timezone.localdate().isoformat()))
        except (ValidationError, TypeError, ValueError):
            return Response({"detail": "Check the currencies, rate, and effective date.", "code": "invalid_exchange_rate"}, status=400)
        Currency = apps.get_model("finance", "Currency")
        ExchangeRate = apps.get_model("finance", "ExchangeRate")
        from_currency = Currency.objects.filter(code=from_code, is_active=True).first()
        to_currency = Currency.objects.filter(code=to_code, is_active=True).first()
        if not from_currency or not to_currency:
            return Response({"detail": "Both currencies must be active on this Platform.", "code": "unknown_currency"}, status=400)
        reason = _automatic_reason(request, f"Entered {from_code} to {to_code} exchange rate.")
        with transaction.atomic():
            existing = ExchangeRate.objects.select_for_update().filter(
                from_currency=from_currency, to_currency=to_currency, effective_date=effective_date,
            ).first()
            before = self._item(existing) if existing else {}
            if existing:
                existing.rate = rate_value
                existing.source = "manual"
                existing.entered_by = request.user
                existing.save(update_fields=["rate", "source", "entered_by"])
                stored = existing
            else:
                stored = ExchangeRate.objects.create(
                    from_currency=from_currency, to_currency=to_currency, rate=rate_value,
                    effective_date=effective_date, source="manual", entered_by=request.user,
                )
            record_platform_audit(
                request=request, action="configuration.exchange_rate_set", target_type="exchange_rate",
                target_id=f"{from_code}-{to_code}-{effective_date.isoformat()}", reason=reason,
                before=before, after=self._item(stored),
            )
        return Response(self._item(stored), status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED)


class PlatformConsoleWorkspaceViewSet(viewsets.ViewSet):
    """Cross-workspace management for platform administrators only."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]

    class Pagination(LimitOffsetPagination):
        """Bounded, explicit pagination for the cross-tenant inventory."""
        default_limit = 100
        max_limit = 500
        limit_query_param = "page_size"

    _STATUS_FILTERS = {"active", "suspended", "inactive"}

    def _workspace(self, pk):
        Workspace = apps.get_model("common", "Workspace")
        return Workspace.objects.select_related("platform_profile__cluster").get(pk=pk)

    def _administrator_users(self, workspace):
        """Return eligible reset recipients using the ownership model for this mode."""
        User = apps.get_model("common", "User")
        if is_embedded_mode():
            StaffMember = apps.get_model("common", "StaffMember")
            user_ids = StaffMember.all_objects.filter(
                workspace=workspace, is_active=True, role__code__in=["admin", "owner"],
            ).values_list("user_id", flat=True)
        else:
            PlatformMembership = apps.get_model("platform", "PlatformMembership")
            # PlatformMembership ownership is durable; StaffMember roles may change
            # inside the tenant and must not grant cross-workspace reset authority.
            user_ids = PlatformMembership.objects.filter(
                profile__workspace=workspace, is_active=True, role="owner",
            ).values_list("user_id", flat=True)
        return User.objects.filter(id__in=user_ids, is_active=True).order_by("id")

    def _owner(self, workspace):
        user = self._administrator_users(workspace).first()
        if not user:
            return None
        return {"id": user.id, "username": user.username, "email": user.email or None}

    def _item(self, workspace):
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        owner = self._owner(workspace)
        domains = list(workspace.domains.values_list("hostname", flat=True))
        staff_count = apps.get_model("common", "StaffMember").all_objects.filter(
            workspace=workspace, is_active=True
        ).count()
        return {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "is_active": workspace.is_active,
            "is_platform": is_platform_workspace(workspace),
            "suspended_at": profile.suspended_at.isoformat() if profile and profile.suspended_at else None,
            "scheduled_deletion_at": (
                profile.scheduled_deletion_at.isoformat()
                if profile and profile.scheduled_deletion_at else None
            ),
            "created_at": workspace.created_at,
            "domains": domains,
            "owner": owner,
            "owned_by_viewer": bool(owner and owner["id"] == self.request.user.id),
            "staff_count": staff_count,
            "active_extensions": [],
            "cluster": ({"id": cluster.id, "name": cluster.name, "region": cluster.region,
                         "is_active": cluster.is_active} if cluster else None),
        }

    def list(self, request):
        Workspace = apps.get_model("common", "Workspace")
        queryset = Workspace.objects.select_related("platform_profile__cluster").order_by("-created_at")
        term = (request.query_params.get("search") or "").strip()
        if term:
            queryset = queryset.filter(Q(name__icontains=term) | Q(slug__icontains=term))
        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter:
            if status_filter not in self._STATUS_FILTERS:
                raise ValidationError({"status": "Use active, suspended, or inactive."})
            if status_filter == "active":
                queryset = queryset.filter(is_active=True, platform_profile__suspended_at__isnull=True)
            elif status_filter == "suspended":
                queryset = queryset.filter(platform_profile__suspended_at__isnull=False)
            else:
                queryset = queryset.filter(is_active=False, platform_profile__suspended_at__isnull=True)
        cluster_id = (request.query_params.get("cluster") or "").strip()
        if len(cluster_id) > 32:
            raise ValidationError({"cluster": "Use a Cluster ID of 32 characters or fewer."})
        if cluster_id:
            queryset = queryset.filter(platform_profile__cluster_id=cluster_id)

        paginator = self.Pagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([self._item(workspace) for workspace in page])

    def retrieve(self, request, pk=None):
        try:
            workspace = self._workspace(pk)
        except apps.get_model("common", "Workspace").DoesNotExist:
            return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = self._item(workspace)
        payload["email"] = workspace.email
        payload["phone"] = workspace.phone
        payload["settings"] = workspace.settings or {}
        payload["extensions"] = []
        return Response(payload)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        workspace = self._workspace(pk)
        before = {"is_active": workspace.is_active}
        suspend_workspace(workspace, initiated_by=request.user, reason=reason)
        record_platform_audit(
            request=request, action="workspace.suspend", target_type="workspace",
            target_id=workspace.id, reason=reason, before=before,
            after={"is_active": workspace.is_active},
        )
        return Response(self._item(workspace))

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        workspace = self._workspace(pk)
        before = {"is_active": workspace.is_active}
        resume_workspace(workspace, initiated_by=request.user)
        record_platform_audit(
            request=request, action="workspace.resume", target_type="workspace",
            target_id=workspace.id, reason=reason, before=before,
            after={"is_active": workspace.is_active},
        )
        return Response(self._item(workspace))

    @action(detail=True, methods=["post"])
    def delete(self, request, pk=None):
        """Schedule a recoverable deletion; never remove tenant data here."""
        _confirmed(request)
        reason = _change_reason(request)
        WorkspaceOperation = apps.get_model("platform", "WorkspaceOperation")
        Workspace = apps.get_model("common", "Workspace")
        WorkspacePlatformProfile = apps.get_model("platform", "WorkspacePlatformProfile")
        with transaction.atomic():
            try:
                workspace = Workspace.objects.select_for_update().select_related(
                    "platform_profile__cluster"
                ).get(pk=pk)
            except Workspace.DoesNotExist:
                return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
            profile, _ = WorkspacePlatformProfile.objects.get_or_create(workspace=workspace)
            # A second submit must not silently extend the deletion window.
            if profile.scheduled_deletion_at:
                return Response(self._item(workspace))
            before = {"is_active": workspace.is_active, "scheduled_deletion_at": None}
            workspace.is_active = False
            workspace.save(update_fields=["is_active"])
            profile.scheduled_deletion_at = timezone.now() + timedelta(days=30)
            profile.save(update_fields=["scheduled_deletion_at", "updated_at"])
            WorkspaceOperation.objects.create(workspace=workspace, operation="delete", status="completed",
                                              initiated_by=request.user, details={"soft": True, "reason": reason},
                                              completed_at=timezone.now())
            record_platform_audit(
                request=request, action="workspace.deletion_scheduled", target_type="workspace",
                target_id=workspace.id, reason=reason, before=before,
                after={"is_active": False, "scheduled_deletion_at": profile.scheduled_deletion_at.isoformat()},
            )
            # ``select_related`` can hold a stale one-to-one object when a profile was
            # created through ``get_or_create`` above. Re-read before serializing the
            # response so the UI receives the actual deletion deadline.
            return Response(self._item(self._workspace(workspace.id)))

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        """Cancel a scheduled deletion and restore a workspace to active state."""
        _confirmed(request)
        reason = _change_reason(request)
        Workspace = apps.get_model("common", "Workspace")
        with transaction.atomic():
            try:
                workspace = Workspace.objects.select_for_update().select_related(
                    "platform_profile__cluster"
                ).get(pk=pk)
            except Workspace.DoesNotExist:
                return Response({"detail": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
            profile = getattr(workspace, "platform_profile", None)
            if not profile or not profile.scheduled_deletion_at:
                return Response({
                    "detail": "This workspace is not scheduled for deletion.",
                    "code": "workspace_not_scheduled_for_deletion",
                }, status=status.HTTP_409_CONFLICT)
            scheduled_at = profile.scheduled_deletion_at
            resume_workspace(workspace, initiated_by=request.user)
            record_platform_audit(
                request=request, action="workspace.deletion_cancelled", target_type="workspace",
                target_id=workspace.id, reason=reason,
                before={"is_active": False, "scheduled_deletion_at": scheduled_at.isoformat()},
                after={"is_active": True, "scheduled_deletion_at": None},
            )
            return Response(self._item(workspace))

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        workspace = self._workspace(pk)
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        owner = self._owner(workspace)
        data = {
            "format": "idlevo-workspace-v1",
            "scope": "configuration-template",
            "does_not_include": ["members", "business_data", "media"],
            "workspace": {"name": workspace.name, "slug": workspace.slug, "email": workspace.email,
                          "phone": workspace.phone, "settings": workspace.settings or {}},
            "owner_email": owner["email"] if owner else None,
            "cluster": {"id": cluster.id, "name": cluster.name, "region": cluster.region} if cluster else None,
            # Importing a hostname never proves control. The destination always
            # restores custom domains as pending, non-primary candidates.
            "custom_domains": list(workspace.domains.filter(
                kind=apps.get_model("common", "WorkspaceDomain").KIND_CUSTOM,
            ).values("hostname")),
            "exported_at": timezone.now().isoformat(),
        }
        record_platform_audit(
            request=request, action="workspace.exported", target_type="workspace",
            target_id=workspace.id, reason="Workspace configuration export downloaded.",
            after={"format": data["format"]},
        )
        import json
        response = HttpResponse(json.dumps(data, indent=2, default=str), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="workspace-{workspace.slug}.json"'
        return response

    @action(detail=False, methods=["post"], url_path="import-workspace")
    @transaction.atomic
    def import_workspace(self, request):
        _confirmed(request)
        reason = _change_reason(request)
        data = request.data if isinstance(request.data, dict) else {}
        export_format = data.get("format")
        if export_format and export_format != "idlevo-workspace-v1":
            return Response({
                "detail": "This is not a supported Idlevo workspace configuration export.",
                "code": "unsupported_workspace_import_format",
            }, status=status.HTTP_400_BAD_REQUEST)
        source = data.get("workspace", data)
        if not isinstance(source, dict):
            return Response({"detail": "workspace must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        name = str(source.get("name", "")).strip()
        if not name:
            return Response({"detail": "workspace.name is required."}, status=status.HTTP_400_BAD_REQUEST)
        Workspace = apps.get_model("common", "Workspace")
        slug = source.get("slug") or None
        if slug and Workspace.objects.filter(slug=slug).exists():
            return Response({"detail": "A workspace with this slug already exists."}, status=status.HTTP_409_CONFLICT)
        User = apps.get_model("common", "User")
        owner_email = str(data.get("owner_email", "")).strip().lower()
        if not owner_email:
            return Response({
                "detail": "owner_email is required to import a workspace configuration.",
                "code": "workspace_import_owner_required",
            }, status=status.HTTP_400_BAD_REQUEST)
        owner = User.objects.filter(email__iexact=owner_email, is_active=True).first()
        if not owner:
            return Response({
                "detail": "The import owner must be an active user on this Platform.",
                "code": "workspace_import_owner_not_found",
            }, status=status.HTTP_400_BAD_REQUEST)

        cluster_data = data.get("cluster") if isinstance(data.get("cluster"), dict) else {}
        cluster = None
        cluster_id = str(cluster_data.get("id") or "").strip()
        if cluster_id:
            Cluster = apps.get_model("platform", "Cluster")
            try:
                cluster = Cluster.objects.get(pk=cluster_id)
            except Cluster.DoesNotExist:
                return Response({
                    "detail": "The exported Cluster is not available on this Platform.",
                    "code": "workspace_import_cluster_not_found",
                }, status=status.HTTP_409_CONFLICT)

        domains_data = data.get("custom_domains", [])
        if not isinstance(domains_data, list) or len(domains_data) > 20:
            return Response({"detail": "custom_domains must contain at most 20 domains."}, status=status.HTTP_400_BAD_REQUEST)
        custom_domains = []
        for item in domains_data:
            hostname = normalize_hostname(item.get("hostname") if isinstance(item, dict) else item)
            if not hostname:
                return Response({"detail": "A custom domain is invalid."}, status=status.HTTP_400_BAD_REQUEST)
            custom_domains.append(hostname)
        if len(set(custom_domains)) != len(custom_domains):
            return Response({"detail": "Custom domains must be unique."}, status=status.HTTP_400_BAD_REQUEST)
        WorkspaceDomain = apps.get_model("common", "WorkspaceDomain")
        conflicts = list(WorkspaceDomain.objects.filter(hostname__in=custom_domains).values_list("hostname", flat=True))
        if conflicts:
            return Response({
                "detail": "One or more custom domains are already assigned on this Platform.",
                "code": "workspace_import_domain_conflict",
                "domains": conflicts,
            }, status=status.HTTP_409_CONFLICT)

        try:
            workspace = WorkspaceService(user=request.user).create_workspace(
                name=name, slug=slug, owner_user=owner, email=source.get("email", ""),
                phone=source.get("phone", ""), settings=source.get("settings") or {},
                region=(cluster.region if cluster else cluster_data.get("region")) or "us",
                cluster=cluster,
            )
        except WorkspaceCapacityUnavailable as exc:
            return Response(
                {"detail": str(exc), "code": exc.default_code},
                status=status.HTTP_409_CONFLICT,
            )
        WorkspaceDomain.objects.bulk_create([
            WorkspaceDomain(
                workspace=workspace,
                hostname=hostname,
                kind=WorkspaceDomain.KIND_CUSTOM,
                verification_status=WorkspaceDomain.VERIFICATION_PENDING,
                ssl_status=WorkspaceDomain.SSL_NONE,
                is_primary=False,
            )
            for hostname in custom_domains
        ])
        record_platform_audit(
            request=request, action="workspace.imported", target_type="workspace",
            target_id=workspace.id, reason=reason,
            after={"slug": workspace.slug, "cluster_id": workspace.platform_profile.cluster_id, "custom_domains": custom_domains},
        )
        return Response(self._item(workspace), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reset-admin-password")
    def reset_admin_password(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        workspace = self._workspace(pk)
        administrators = self._administrator_users(workspace)
        requested_email = str(request.data.get("email") or "").strip()
        recipient = (
            administrators.filter(email__iexact=requested_email).first()
            if requested_email else administrators.first()
        )
        if not recipient or not recipient.email:
            return Response(
                {"detail": "Choose an active Workspace administrator with an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = getattr(workspace, "platform_profile", None)
        cluster = getattr(profile, "cluster", None) if profile else None
        from django.conf import settings
        frontend_url = (getattr(settings, "FRONTEND_URL", "") or getattr(cluster, "frontend_base_url", "")).rstrip("/")
        if not frontend_url:
            return Response({"detail": "Password reset frontend is not configured."}, status=status.HTTP_409_CONFLICT)
        if not UserService.request_password_reset(recipient.email, frontend_url):
            return Response(
                {"detail": "The password reset email could not be sent. Check email delivery settings and try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        record_platform_audit(
            request=request, action="workspace.password_reset_requested", target_type="workspace",
            target_id=workspace.id, reason=reason, after={"administrator_id": recipient.id},
        )
        return Response({"detail": "If the account exists, a password reset email has been sent."})

    @action(detail=True, methods=["get", "patch"], url_path="usage-cap")
    def usage_cap(self, request, pk=None):
        """Read or override the cap which controls one workspace's metered allowance."""
        workspace = self._workspace(pk)
        UsageCap = apps.get_model("platform", "WorkspaceUsageCap")
        cap = UsageCap.objects.filter(workspace=workspace).first()
        default_cap = platform_variable_decimal("default_usage_cap_points")

        def item(current):
            own = current.cap_points if current else None
            effective = own if own is not None else default_cap
            return {
                "workspace": workspace.id,
                "cap_points": _decimal_text(own) if own is not None else None,
                "default_cap_points": _decimal_text(default_cap),
                "effective_cap_points": _decimal_text(effective),
                "source": "workspace" if own is not None else "platform",
            }

        if request.method == "GET":
            return Response(item(cap))
        raw = request.data.get("cap_points")
        if raw is None:
            desired = None
        else:
            try:
                desired = _decimal(raw, minimum=Decimal("0"), places="0.0001")
            except ValidationError:
                return Response({"detail": "Use a non-negative cap in points.", "code": "invalid_usage_cap"}, status=400)
        reason = _automatic_reason(request, "Changed a workspace metered-usage cap.")
        with transaction.atomic():
            current, _ = UsageCap.objects.select_for_update().get_or_create(workspace=workspace)
            before = item(current)
            if desired is None:
                current.delete()
                result = None
            else:
                current.cap_points = desired
                current.updated_by = request.user
                current.save(update_fields=["cap_points", "updated_by", "updated_at"])
                result = current
            record_platform_audit(
                request=request, action="workspace.usage_cap_updated", target_type="workspace",
                target_id=workspace.id, reason=reason, before=before, after=item(result),
            )
        return Response(item(result))

    @action(detail=True, methods=["post"], url_path="grants")
    def grants(self, request, pk=None):
        """Grant a temporary or perpetual base-plan/extension entitlement."""
        workspace = self._workspace(pk)
        key = str(request.data.get("key") or "").strip()
        if len(key) > 255:
            return Response({"detail": "Use an entitlement key of 255 characters or fewer.", "code": "invalid_grant"}, status=400)
        never_expires = request.data.get("never_expires") is True
        raw_months = request.data.get("months")
        if never_expires == (raw_months not in (None, "")):
            return Response({"detail": "Choose a finite term or never expires.", "code": "invalid_grant"}, status=400)
        months = None
        if not never_expires:
            try:
                months = int(raw_months)
            except (TypeError, ValueError):
                months = 0
            if not 1 <= months <= 120:
                return Response({"detail": "Use between 1 and 120 months.", "code": "invalid_grant"}, status=400)
        try:
            reason = _change_reason(request)
        except ValidationError:
            return Response({"detail": "Provide a grant reason.", "code": "invalid_grant"}, status=400)
        Entitlement = apps.get_model("platform", "WorkspaceEntitlement")
        now = timezone.now()
        with transaction.atomic():
            active = Entitlement.objects.select_for_update().filter(
                workspace=workspace, key=key, status=Entitlement.STATUS_ACTIVE,
            ).filter(Q(current_period_end__isnull=True) | Q(current_period_end__gt=now)).first()
            if active:
                return Response({
                    "detail": "This workspace already has that entitlement.",
                    "code": "already_entitled",
                    "entitlement": self._entitlement_item(active),
                }, status=status.HTTP_409_CONFLICT)
            Entitlement.objects.filter(
                workspace=workspace, key=key, status=Entitlement.STATUS_ACTIVE,
                current_period_end__lte=now,
            ).update(status=Entitlement.STATUS_EXPIRED)
            entitlement = Entitlement.objects.create(
                workspace=workspace, key=key, status=Entitlement.STATUS_ACTIVE,
                current_period_end=None if never_expires else _add_months(now, months),
                reason=reason, created_by=request.user,
            )
            item = self._entitlement_item(entitlement)
            record_platform_audit(
                request=request, action="workspace.entitlement_granted", target_type="workspace",
                target_id=workspace.id, reason=reason, after={"entitlement": item},
            )
        return Response({"workspace": workspace.id, "entitlement": item, "extension": None}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _entitlement_item(entitlement):
        return {
            "id": entitlement.id,
            "key": entitlement.key,
            "status": entitlement.status,
            "source": entitlement.source,
            "starts_at": entitlement.starts_at,
            "current_period_end": entitlement.current_period_end,
            "reason": entitlement.reason,
        }


class PlatformConsoleClusterViewSet(viewsets.ViewSet):
    """Platform-owned cluster inventory and safe operational settings."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]

    _WRITABLE_FIELDS = {
        "name", "region", "api_base_url", "frontend_base_url", "db_host", "db_port",
        "redis_url", "s3_bucket", "max_workspaces", "is_accepting_new", "is_active",
    }

    def _cluster(self, pk):
        Cluster = apps.get_model("platform", "Cluster")
        return Cluster.objects.get(pk=pk)

    def _workspace_count(self, cluster):
        return cluster.workspaces.count()

    def _item(self, cluster):
        workspace_count = self._workspace_count(cluster)
        max_workspaces = cluster.max_workspaces
        capacity_percentage = 100 if max_workspaces == 0 else min(
            100, int((workspace_count / max_workspaces) * 100)
        )
        return {
            "id": cluster.id,
            "name": cluster.name,
            "region": cluster.region,
            "api_base_url": cluster.api_base_url,
            "frontend_base_url": cluster.frontend_base_url,
            "db_host": cluster.db_host,
            "db_port": cluster.db_port,
            # Connection credentials remain write-only even for a superuser browser
            # session. A replacement can be submitted, but a stored secret is never
            # sent back over the API or copied into an audit/client cache.
            "redis_configured": bool(cluster.redis_url),
            "s3_bucket": cluster.s3_bucket,
            "max_workspaces": max_workspaces,
            "config_version": cluster.config_version,
            "workspace_count": workspace_count,
            "capacity_percentage": capacity_percentage,
            "is_accepting_new": cluster.is_accepting_new,
            "is_active": cluster.is_active,
            "health_status": cluster.health_status,
            "last_health_check": cluster.last_health_check,
            "created_at": cluster.created_at,
            "updated_at": cluster.updated_at,
        }

    def _validated_values(self, data, *, creating):
        from rest_framework import serializers

        fields = {key: data[key] for key in self._WRITABLE_FIELDS if key in data}
        if creating:
            fields["id"] = data.get("id")
            required = {
                "id", "name", "region", "api_base_url", "db_host", "redis_url", "s3_bucket",
            }
            missing = sorted(key for key in required if not fields.get(key))
            if missing:
                raise serializers.ValidationError({key: "This field is required." for key in missing})

        if "id" in fields:
            fields["id"] = str(fields["id"]).strip()
            if not fields["id"] or len(fields["id"]) > 32:
                raise serializers.ValidationError({"id": "Use a non-empty identifier of 32 characters or fewer."})

        if "name" in fields:
            fields["name"] = str(fields["name"]).strip()
            if not fields["name"]:
                raise serializers.ValidationError({"name": "This field may not be blank."})

        if "region" in fields and fields["region"] not in {"us", "eu", "apac"}:
            raise serializers.ValidationError({"region": "Choose us, eu, or apac."})

        for key in ("api_base_url", "frontend_base_url"):
            if key in fields and fields[key]:
                value = str(fields[key]).strip()
                if not value.startswith(("http://", "https://")):
                    raise serializers.ValidationError({key: "Use an http:// or https:// URL."})
                fields[key] = value

        if "redis_url" in fields:
            value = str(fields["redis_url"]).strip()
            # Existing deployments historically stored an HTTP health endpoint here.
            # Keep those clusters editable while accepting native Redis URLs for new ones.
            if not value.startswith(("redis://", "rediss://", "http://", "https://")):
                raise serializers.ValidationError({"redis_url": "Use a Redis or HTTP URL."})
            fields["redis_url"] = value

        for key in ("db_port", "max_workspaces"):
            if key in fields:
                try:
                    fields[key] = int(fields[key])
                except (TypeError, ValueError):
                    raise serializers.ValidationError({key: "Use a whole number."})
                if fields[key] < (1 if key == "db_port" else 0):
                    raise serializers.ValidationError({key: "Use a positive value." if key == "db_port" else "Use zero or more."})

        for key in ("is_accepting_new", "is_active"):
            if key in fields and not isinstance(fields[key], bool):
                raise serializers.ValidationError({key: "Use true or false."})

        return fields

    def list(self, request):
        Cluster = apps.get_model("platform", "Cluster")
        return Response([self._item(cluster) for cluster in Cluster.objects.all()])

    def retrieve(self, request, pk=None):
        try:
            return Response(self._item(self._cluster(pk)))
        except apps.get_model("platform", "Cluster").DoesNotExist:
            return Response({"detail": "Cluster not found."}, status=status.HTTP_404_NOT_FOUND)

    def create(self, request):
        _confirmed(request)
        reason = _change_reason(request)
        values = self._validated_values(request.data, creating=True)
        Cluster = apps.get_model("platform", "Cluster")
        if Cluster.objects.filter(pk=values["id"]).exists():
            return Response({"detail": "A cluster with this identifier already exists."}, status=status.HTTP_409_CONFLICT)
        cluster = Cluster.objects.create(**values)
        record_platform_audit(
            request=request, action="cluster.created", target_type="cluster", target_id=cluster.id,
            reason=reason, after=_cluster_snapshot(cluster),
        )
        return Response(self._item(cluster), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        _confirmed(request)
        reason = _change_reason(request)
        try:
            expected_version = int(request.data.get("expected_version"))
        except (TypeError, ValueError):
            raise ValidationError({"expected_version": "Provide the configuration version you read."})
        if expected_version < 1:
            raise ValidationError({"expected_version": "Use a positive configuration version."})
        try:
            with transaction.atomic():
                Cluster = apps.get_model("platform", "Cluster")
                cluster = Cluster.objects.select_for_update().get(pk=pk)
                if cluster.config_version != expected_version:
                    return Response({
                        "detail": "This Cluster changed while you were editing it. Reload and review the latest configuration.",
                        "code": "cluster_version_conflict",
                        "current_version": cluster.config_version,
                    }, status=status.HTTP_409_CONFLICT)
                values = self._validated_values(request.data, creating=False)
                if values.get("is_accepting_new") is True and values.get("is_active", cluster.is_active) is False:
                    raise ValidationError({"is_accepting_new": "An inactive Cluster cannot accept new workspaces."})
                if values.get("is_active") is False:
                    values["is_accepting_new"] = False
                if "max_workspaces" in values and values["max_workspaces"] < self._workspace_count(cluster):
                    return Response(
                        {"detail": "Capacity cannot be below the number of assigned workspaces."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                before = _cluster_snapshot(cluster)
                for field, value in values.items():
                    setattr(cluster, field, value)
                if values:
                    cluster.config_version += 1
                    cluster.save(update_fields=[*values.keys(), "config_version", "updated_at"])
                    record_platform_audit(
                        request=request, action="cluster.updated", target_type="cluster", target_id=cluster.id,
                        reason=reason, before=before, after=_cluster_snapshot(cluster),
                    )
                return Response(self._item(cluster))
        except apps.get_model("platform", "Cluster").DoesNotExist:
            return Response({"detail": "Cluster not found."}, status=status.HTTP_404_NOT_FOUND)


class PlatformConsoleAuditEventViewSet(viewsets.ViewSet):
    """Read-only, paginated history of sensitive Platform control-plane changes."""

    permission_classes = [IsAuthenticated, IsPlatformSuperuser]
    _DEFAULT_LIMIT = 50
    _MAX_LIMIT = 100

    @staticmethod
    def _event_item(event):
        """Serialize an event without request metadata or unredacted snapshots."""
        return {
            "id": str(event.id),
            "action": event.action,
            "target": {"type": event.target_type, "id": event.target_id},
            "reason": event.reason,
            "actor": (
                {"id": event.actor_id, "username": event.actor.username}
                if event.actor_id else None
            ),
            "before": redact_platform_audit_value(event.before or {}),
            "after": redact_platform_audit_value(event.after or {}),
            "created_at": event.created_at,
        }

    def _limit(self, request):
        raw_limit = request.query_params.get("limit", self._DEFAULT_LIMIT)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        if not 1 <= limit <= self._MAX_LIMIT:
            raise ValidationError({"limit": "Use a whole number between 1 and 100."})
        return limit

    def _cursor(self, request):
        cursor = request.query_params.get("cursor")
        if not cursor:
            return None
        try:
            payload = signing.loads(cursor, salt="platform-audit-events", max_age=60 * 60 * 24 * 30)
            created_at = dateparse.parse_datetime(payload["created_at"])
            event_id = payload["id"]
        except (KeyError, TypeError, ValueError, signing.BadSignature):
            raise ValidationError({"cursor": "Use a valid audit-event cursor."})
        if not created_at:
            raise ValidationError({"cursor": "Use a valid audit-event cursor."})
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, timezone.get_current_timezone())
        return created_at, event_id

    @staticmethod
    def _next_cursor(event):
        return signing.dumps(
            {"created_at": event.created_at.isoformat(), "id": str(event.id)},
            salt="platform-audit-events",
        )

    def list(self, request):
        PlatformAuditEvent = apps.get_model("platform", "PlatformAuditEvent")
        events = PlatformAuditEvent.objects.select_related("actor").order_by("-created_at", "-id")
        for field, maximum in (("action", 100), ("target_type", 64), ("target_id", 255)):
            value = (request.query_params.get(field) or "").strip()
            if len(value) > maximum:
                raise ValidationError({field: f"Use {maximum} characters or fewer."})
            if value:
                events = events.filter(**{field: value})

        cursor = self._cursor(request)
        if cursor:
            created_at, event_id = cursor
            events = events.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=event_id))

        limit = self._limit(request)
        page = list(events[:limit + 1])
        has_next = len(page) > limit
        page = page[:limit]
        return Response({
            "results": [self._event_item(event) for event in page],
            "next": self._next_cursor(page[-1]) if has_next and page else None,
        })

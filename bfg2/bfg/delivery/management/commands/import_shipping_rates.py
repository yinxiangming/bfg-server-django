# -*- coding: utf-8 -*-
"""
Import carriers, delivery zones and freight services from JSON into a workspace.

A storefront with no FreightService for the customer's country shows "no shipping options
available" and cannot take an order, so this configuration is launch-critical — yet it is
per-workspace business data that no migration or seed can supply. This command makes it a
reviewable file that can be replayed onto every environment, and re-run after a database is
refreshed from a snapshot.

Prices are expressed through the shipping templates in `bfg.delivery.schemas.freight_templates`
rather than as raw pricing config, so anything imported here stays editable in the admin
freight editor afterwards.

Usage:
    python manage.py import_shipping_rates <path-to-json> --workspace=<slug_or_id> [--confirm]

JSON shape:
    {
      "zones": [
        {"code": "NZ", "name": "New Zealand", "countries": ["NZ"], "order": 10}
      ],
      "carriers": [
        {
          "code": "NZPOST", "name": "NZ Post",
          "tracking_url_template": "https://.../{tracking_number}",
          "services": [
            {
              "code": "NZ_ECONOMY", "name": "Economy", "description": "...",
              "estimated_days_min": 2, "estimated_days_max": 3, "order": 10,
              "zones": ["NZ"],
              "template": "free_over_amount",
              "params": {"threshold_amount": 100, "fallback_base": 6.5, "fallback_per_kg": 0}
            }
          ]
        }
      ]
    }

`template` is any id from `manage.py`-visible freight templates (flat_rate, base_plus_per_kg,
first_kg_then_per_kg, weight_tiers, free_over_amount, free_over_weight,
first_cbm_then_per_cbm); `params` are that template's form fields.
"""

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from bfg.common.models import Workspace
from bfg.delivery.models import Carrier, DeliveryZone, FreightService
from bfg.delivery.schemas.freight_templates import form_params_to_config, get_template


class Command(BaseCommand):
    help = "Import carriers, delivery zones and freight services from JSON into a workspace"

    def add_arguments(self, parser):
        parser.add_argument("rates_path", type=str, help="Path to shipping rates JSON")
        parser.add_argument(
            "--workspace",
            type=str,
            required=True,
            help="Workspace slug or numeric id",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually write. Without it the command only reports the plan.",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Deactivate freight services of the imported carriers that the file omits.",
        )

    def handle(self, *args, **options):
        rates_path = Path(options["rates_path"]).resolve()
        if not rates_path.exists():
            self.stdout.write(self.style.ERROR(f"File not found: {rates_path}"))
            return
        try:
            with open(rates_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as e:
            self.stdout.write(self.style.ERROR(f"Invalid JSON: {e}"))
            return

        ws_arg = options["workspace"].strip()
        try:
            workspace = (
                Workspace.objects.get(id=int(ws_arg))
                if ws_arg.isdigit()
                else Workspace.objects.get(slug=ws_arg)
            )
        except Workspace.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Workspace not found: {ws_arg}"))
            return

        # Resolve every price up front: a half-applied rate table is worse than none, and a
        # bad template id should not be discovered after the carriers have been written.
        try:
            plan = self._build_plan(payload)
        except (KeyError, TypeError, ValueError) as e:
            self.stdout.write(self.style.ERROR(f"Refusing to run — {e}"))
            return

        self._report(plan, workspace)

        if not options["confirm"]:
            self.stdout.write(
                self.style.WARNING("[dry-run] nothing written — re-run with --confirm")
            )
            return

        with transaction.atomic():
            counts = self._apply(plan, workspace, options["deactivate_missing"])

        self.stdout.write(
            self.style.SUCCESS(
                f"workspace={workspace.slug} zones={counts['zones']} "
                f"carriers={counts['carriers']} services={counts['services']} "
                f"deactivated={counts['deactivated']}"
            )
        )

    def _build_plan(self, payload):
        """Validate the file and resolve every template into a concrete pricing config."""
        zones = []
        for i, raw in enumerate(payload.get("zones", [])):
            code = (raw.get("code") or "").strip()
            countries = raw.get("countries")
            if not code:
                raise ValueError(f"zones[{i}]: code is required")
            if not isinstance(countries, list) or not countries:
                raise ValueError(f"zones[{i}] ({code}): countries must be a non-empty list")
            zones.append(
                {
                    "code": code,
                    "name": raw.get("name") or code,
                    "countries": [str(c).upper() for c in countries],
                    "order": int(raw.get("order", 100)),
                }
            )
        zone_codes = {z["code"] for z in zones}

        carriers = []
        for i, raw in enumerate(payload.get("carriers", [])):
            code = (raw.get("code") or "").strip()
            if not code:
                raise ValueError(f"carriers[{i}]: code is required")
            services = []
            for j, svc in enumerate(raw.get("services", [])):
                where = f"carriers[{i}].services[{j}]"
                svc_code = (svc.get("code") or "").strip()
                if not svc_code:
                    raise ValueError(f"{where}: code is required")
                template_id = svc.get("template")
                if not get_template(template_id):
                    raise ValueError(f"{where} ({svc_code}): unknown template {template_id!r}")
                config, base_price, price_per_kg = form_params_to_config(
                    template_id, svc.get("params") or {}
                )
                for zone_code in svc.get("zones") or []:
                    if zone_code not in zone_codes:
                        raise ValueError(
                            f"{where} ({svc_code}): zone {zone_code!r} is not defined in this file"
                        )
                services.append(
                    {
                        "code": svc_code,
                        "name": svc.get("name") or svc_code,
                        "description": svc.get("description", ""),
                        "estimated_days_min": int(svc.get("estimated_days_min", 1)),
                        "estimated_days_max": int(svc.get("estimated_days_max", 7)),
                        "transport_type": svc.get("transport_type", ""),
                        "order": int(svc.get("order", 100)),
                        "zones": list(svc.get("zones") or []),
                        "config": config,
                        "base_price": Decimal(str(base_price)),
                        "price_per_kg": Decimal(str(price_per_kg)),
                    }
                )
            carriers.append(
                {
                    "code": code,
                    "name": raw.get("name") or code,
                    "carrier_type": raw.get("carrier_type", ""),
                    "tracking_url_template": raw.get("tracking_url_template", ""),
                    "services": services,
                }
            )
        return {"zones": zones, "carriers": carriers}

    def _report(self, plan, workspace):
        for zone in plan["zones"]:
            self.stdout.write(f"  zone     {zone['code']:<16} {', '.join(zone['countries'])}")
        for carrier in plan["carriers"]:
            self.stdout.write(f"  carrier  {carrier['code']:<16} {carrier['name']}")
            for svc in carrier["services"]:
                zones = ",".join(svc["zones"]) or "all countries"
                self.stdout.write(
                    f"    service {svc['code']:<20} {svc['name'][:30]:<32} "
                    f"base={svc['base_price']:>7} /kg={svc['price_per_kg']:>5} "
                    f"[{svc['config'].get('template_id')}] -> {zones}"
                )

    def _apply(self, plan, workspace, deactivate_missing):
        counts = {"zones": 0, "carriers": 0, "services": 0, "deactivated": 0}

        zones_by_code = {}
        for spec in plan["zones"]:
            zone, _ = DeliveryZone.objects.update_or_create(
                workspace=workspace,
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "countries": spec["countries"],
                    "order": spec["order"],
                    "is_active": True,
                },
            )
            zones_by_code[spec["code"]] = zone
            counts["zones"] += 1

        for spec in plan["carriers"]:
            # Tenant-scoped default manager resolves the workspace from request middleware,
            # which does not exist in a management command; the explicit filter is the
            # tenant boundary.
            carrier, _ = Carrier.all_objects.update_or_create(
                workspace=workspace,
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "carrier_type": spec["carrier_type"],
                    "tracking_url_template": spec["tracking_url_template"],
                    "is_active": True,
                },
            )
            counts["carriers"] += 1

            for svc in spec["services"]:
                service, _ = FreightService.objects.update_or_create(
                    workspace=workspace,
                    carrier=carrier,
                    code=svc["code"],
                    defaults={
                        "name": svc["name"],
                        "description": svc["description"],
                        "base_price": svc["base_price"],
                        "price_per_kg": svc["price_per_kg"],
                        "estimated_days_min": svc["estimated_days_min"],
                        "estimated_days_max": svc["estimated_days_max"],
                        "transport_type": svc["transport_type"],
                        "config": svc["config"],
                        "order": svc["order"],
                        "is_active": True,
                    },
                )
                service.delivery_zones.set(
                    [zones_by_code[c] for c in svc["zones"]]
                )
                counts["services"] += 1

            if deactivate_missing:
                keep = {s["code"] for s in spec["services"]}
                stale = FreightService.objects.filter(
                    workspace=workspace, carrier=carrier, is_active=True
                ).exclude(code__in=keep)
                counts["deactivated"] += stale.update(is_active=False)

        return counts

# -*- coding: utf-8 -*-
"""
Agent capabilities for marketing: send_campaign, create_discount_code.
Handlers delegate to CampaignService / Coupon creation; required_permission = IsWorkspaceStaff.
"""
from django.utils import timezone

from bfg.common.models import Customer
from bfg.core.agent import AgentCapability, registry as agent_registry
from bfg.core.permissions import IsWorkspaceStaff
from bfg.marketing.models import Campaign, Coupon, DiscountRule
from bfg.marketing.services.promo_service import CampaignService


def _send_campaign_handler(
    request,
    *,
    campaign_id: int,
    customer_id: int,
    issue_coupon: bool = False,
    discount_rule_id: int = None,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    campaign = Campaign.objects.get(id=campaign_id, workspace=workspace)
    customer = Customer.objects.get(id=customer_id, workspace=workspace)
    service = CampaignService(workspace=workspace, user=request.user)
    participation, coupon = service.join_campaign(
        customer=customer,
        campaign=campaign,
        issue_coupon=issue_coupon,
        discount_rule_id=discount_rule_id,
    )
    return {
        "campaign_id": campaign_id,
        "customer_id": customer_id,
        "participation_id": participation.id,
        "status": participation.status,
        "coupon_code": coupon.code if coupon else None,
    }


def _create_discount_code_handler(
    request,
    *,
    discount_rule_id: int,
    code: str,
    valid_from: str = None,
    valid_until: str = None,
    usage_limit: int = None,
    **kwargs
):
    workspace = getattr(request, "workspace", None)
    if not workspace:
        raise ValueError("Workspace is required")
    rule = DiscountRule.objects.get(id=discount_rule_id, workspace=workspace)
    code = (code or "").strip()
    if not code:
        raise ValueError("code is required")
    if Coupon.objects.filter(workspace=workspace, code=code).exists():
        raise ValueError(f"Coupon code '{code}' already exists")
    now = timezone.now()
    if valid_from:
        try:
            from datetime import datetime
            valid_from_dt = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
            if timezone.is_naive(valid_from_dt):
                valid_from_dt = timezone.make_aware(valid_from_dt)
        except Exception:
            valid_from_dt = now
    else:
        valid_from_dt = now
    valid_until_dt = None
    if valid_until:
        try:
            from datetime import datetime
            valid_until_dt = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if timezone.is_naive(valid_until_dt):
                valid_until_dt = timezone.make_aware(valid_until_dt)
        except Exception:
            pass
    coupon = Coupon.objects.create(
        workspace=workspace,
        discount_rule=rule,
        code=code,
        valid_from=valid_from_dt,
        valid_until=valid_until_dt,
        usage_limit=usage_limit,
        is_active=True,
    )
    return {
        "coupon_id": coupon.id,
        "code": coupon.code,
        "discount_rule_id": discount_rule_id,
        "valid_from": coupon.valid_from.isoformat() if coupon.valid_from else None,
        "valid_until": coupon.valid_until.isoformat() if coupon.valid_until else None,
    }


CAPABILITIES = [
    AgentCapability(
        id="marketing.send_campaign",
        name="Send campaign (join customer to campaign)",
        description="Register a customer in a campaign (Boost). Optionally issue a coupon.",
        app_label="marketing",
        input_schema={
            "type": "object",
            "required": ["campaign_id", "customer_id"],
            "properties": {
                "campaign_id": {"type": "integer", "description": "Campaign ID"},
                "customer_id": {"type": "integer", "description": "Customer ID"},
                "issue_coupon": {"type": "boolean", "description": "Issue a coupon on join"},
                "discount_rule_id": {"type": "integer", "description": "Discount rule for issued coupon"},
            },
        },
        handler=_send_campaign_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
    AgentCapability(
        id="marketing.create_discount_code",
        name="Create discount code",
        description="Create a coupon (discount code) for a discount rule.",
        app_label="marketing",
        input_schema={
            "type": "object",
            "required": ["discount_rule_id", "code"],
            "properties": {
                "discount_rule_id": {"type": "integer", "description": "Discount rule ID"},
                "code": {"type": "string", "description": "Coupon code (unique per workspace)"},
                "valid_from": {"type": "string", "description": "Valid from (ISO datetime)"},
                "valid_until": {"type": "string", "description": "Valid until (ISO datetime)"},
                "usage_limit": {"type": "integer", "description": "Max total uses"},
            },
        },
        handler=_create_discount_code_handler,
        required_permission=(IsWorkspaceStaff,),
    ),
]


def register_capabilities():
    for cap in CAPABILITIES:
        agent_registry.register(cap)

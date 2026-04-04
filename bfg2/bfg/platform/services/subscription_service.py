# -*- coding: utf-8 -*-
"""
Subscription Service
Handles Platform-level SaaS billing via Stripe.
"""
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.apps import apps

from bfg.platform.services.feature_service import sync_plan_features


def get_or_create_platform_billing_customer(workspace, stripe_customer_id: str = None):
    """
    Get or create a Customer record for platform billing.
    Uses the workspace owner (first active StaffMember with owner/admin role).
    """
    Customer = apps.get_model("common", "Customer")
    StaffMember = apps.get_model("common", "StaffMember")

    owner_membership = (
        StaffMember.objects.filter(workspace=workspace, is_active=True)
        .select_related("user")
        .first()
    )
    if not owner_membership:
        raise ValueError(f"No active staff member found for workspace {workspace.id}")

    user = owner_membership.user
    customer, _ = Customer.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={"email": user.email},
    )
    if stripe_customer_id and not customer.gateway_metadata.get("stripe_customer_id"):
        customer.gateway_metadata = {"stripe_customer_id": stripe_customer_id}
        customer.save(update_fields=["gateway_metadata"])
    return customer


class SubscriptionService:

    def create_checkout(self, workspace, plan, billing_interval: str, user) -> str:
        """
        Create a Stripe Checkout Session for platform billing.
        Returns the checkout URL.
        """
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        price_id = (
            plan.stripe_price_id_annual
            if billing_interval == "annual"
            else plan.stripe_price_id_monthly
        )
        if not price_id:
            raise ValueError(f"No Stripe price ID configured for plan {plan.id} ({billing_interval})")

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        session = stripe.checkout.Session.create(
            customer_email=user.email,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{frontend_url}/admin/platform/workspaces/{workspace.id}?checkout=success",
            cancel_url=f"{frontend_url}/admin/platform/workspaces/{workspace.id}/billing",
            metadata={
                "workspace_id": str(workspace.id),
                "plan_id": str(plan.id),
                "billing_interval": billing_interval,
            },
        )
        return session.url

    def handle_checkout_completed(self, session) -> None:
        """
        Stripe Webhook handler: checkout.session.completed
        Creates or updates the platform Subscription record.
        """
        Workspace = apps.get_model("common", "Workspace")
        SubscriptionPlan = apps.get_model("shop", "SubscriptionPlan")
        Subscription = apps.get_model("shop", "Subscription")

        workspace_id = session["metadata"]["workspace_id"]
        plan_id = session["metadata"]["plan_id"]
        billing_interval = session["metadata"].get("billing_interval", "monthly")

        workspace = Workspace.objects.get(id=workspace_id)
        plan = SubscriptionPlan.objects.get(id=plan_id)
        customer = get_or_create_platform_billing_customer(
            workspace, stripe_customer_id=session.get("customer")
        )

        now = timezone.now()
        delta = timedelta(days=365 if billing_interval == "annual" else 30)

        Subscription.objects.update_or_create(
            workspace=workspace,
            is_platform_billing=True,
            defaults={
                "customer": customer,
                "plan": plan,
                "billing_interval": billing_interval,
                "status": "active",
                "stripe_subscription_id": session.get("subscription") or "",
                "stripe_customer_id": session.get("customer") or "",
                "cancel_at_period_end": False,
                "start_date": now,
                "next_billing_date": now + delta,
            },
        )
        sync_plan_features(workspace, plan)

    def handle_subscription_updated(self, stripe_sub) -> None:
        """Stripe Webhook: customer.subscription.updated"""
        Subscription = apps.get_model("shop", "Subscription")
        status_map = {
            "active": "active",
            "trialing": "trialing",
            "past_due": "past_due",
            "canceled": "cancelled",
            "unpaid": "past_due",
        }
        Subscription.objects.filter(
            stripe_subscription_id=stripe_sub["id"],
            is_platform_billing=True,
        ).update(
            status=status_map.get(stripe_sub["status"], stripe_sub["status"]),
            cancel_at_period_end=stripe_sub.get("cancel_at_period_end", False),
        )

    def handle_subscription_deleted(self, stripe_sub) -> None:
        """Stripe Webhook: customer.subscription.deleted"""
        Subscription = apps.get_model("shop", "Subscription")
        Subscription.objects.filter(
            stripe_subscription_id=stripe_sub["id"],
            is_platform_billing=True,
        ).update(status="cancelled", end_date=timezone.now())

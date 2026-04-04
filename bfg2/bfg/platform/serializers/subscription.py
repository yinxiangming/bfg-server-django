# -*- coding: utf-8 -*-
"""
Subscription serializer for platform billing status.
"""
from rest_framework import serializers


class SubscriptionSerializer(serializers.Serializer):
    """Read-only subscription status."""
    id = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    billing_interval = serializers.CharField(read_only=True)
    start_date = serializers.DateTimeField(read_only=True)
    end_date = serializers.DateTimeField(read_only=True)
    next_billing_date = serializers.DateTimeField(read_only=True)
    trial_end = serializers.DateTimeField(read_only=True)
    cancel_at_period_end = serializers.BooleanField(read_only=True)

    # Nested plan info
    plan_name = serializers.SerializerMethodField()
    plan_price = serializers.SerializerMethodField()

    def get_plan_name(self, obj):
        return obj.plan.name if obj.plan else None

    def get_plan_price(self, obj):
        if not obj.plan:
            return None
        if obj.billing_interval == "annual":
            return str(obj.plan.price_annual) if hasattr(obj.plan, "price_annual") else str(obj.plan.price)
        return str(obj.plan.price)

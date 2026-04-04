# -*- coding: utf-8 -*-
"""
SubscriptionPlan serializer for Platform plan listing/pricing page.
"""
from rest_framework import serializers


class SubscriptionPlanSerializer(serializers.Serializer):
    """Read-only plan for pricing page."""
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)

    # Pricing
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    interval = serializers.CharField(read_only=True)
    price_annual = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    annual_discount_percent = serializers.IntegerField(read_only=True)

    # Limits
    limits = serializers.JSONField(read_only=True)

    # Features
    features = serializers.JSONField(read_only=True)

    # Trial
    trial_period_days = serializers.IntegerField(read_only=True)

    is_active = serializers.BooleanField(read_only=True)
    sort_order = serializers.IntegerField(read_only=True)

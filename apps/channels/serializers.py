# -*- coding: utf-8 -*-
from rest_framework import serializers

from apps.channels.models import (
    ChannelFAQRule,
    ExternalChannel,
    ExternalFeedback,
    ExternalListing,
    ExternalQuestion,
)


class ExternalChannelSerializer(serializers.ModelSerializer):
    # credentials are write-only; read responses only surface non-sensitive metadata
    credentials = serializers.JSONField(write_only=True, required=False, default=dict)
    channel_type_display = serializers.CharField(source="get_channel_type_display", read_only=True)

    class Meta:
        model = ExternalChannel
        fields = [
            "id",
            "channel_type",
            "channel_type_display",
            "name",
            "credentials",
            "config",
            "is_active",
            "last_sync_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "last_sync_at", "created_at", "updated_at"]


class ExternalListingSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ExternalListing
        fields = [
            "id",
            "product",
            "product_name",
            "channel",
            "channel_name",
            "external_id",
            "status",
            "status_display",
            "mapped_data",
            "channel_meta",
            "expires_at",
            "last_synced",
            "error_detail",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "external_id",
            "status",
            "mapped_data",
            "channel_meta",
            "last_synced",
            "error_detail",
            "created_at",
            "updated_at",
        ]


class ExternalFeedbackSerializer(serializers.ModelSerializer):
    feedback_type_display = serializers.CharField(source="get_feedback_type_display", read_only=True)

    class Meta:
        model = ExternalFeedback
        fields = [
            "id",
            "listing",
            "external_id",
            "author",
            "rating",
            "feedback_type",
            "feedback_type_display",
            "comment",
            "received_at",
            "reply",
            "replied_at",
            "is_replied",
        ]
        read_only_fields = ["id", "external_id", "received_at"]


class ExternalQuestionSerializer(serializers.ModelSerializer):
    answer_status_display = serializers.CharField(source="get_answer_status_display", read_only=True)

    class Meta:
        model = ExternalQuestion
        fields = [
            "id",
            "listing",
            "external_id",
            "question_text",
            "asker",
            "asked_at",
            "answer_text",
            "answered_at",
            "answer_status",
            "answer_status_display",
            "is_auto_answered",
        ]
        read_only_fields = [
            "id",
            "external_id",
            "question_text",
            "asker",
            "asked_at",
            "answered_at",
            "is_auto_answered",
        ]


class ChannelFAQRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelFAQRule
        fields = [
            "id",
            "channel",
            "keywords",
            "answer",
            "priority",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

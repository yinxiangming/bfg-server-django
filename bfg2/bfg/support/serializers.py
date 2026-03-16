# -*- coding: utf-8 -*-
"""
BFG Support Module Serializers
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from typing import Optional

from .models import SupportTicket, SupportTicketMessage, TicketAssignment, TicketCategory, TicketPriority, TicketTag


class TicketMessageSerializer(serializers.ModelSerializer):
    """Read-only serializer for ticket message (used in detail)."""
    sender_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)

    class Meta:
        model = SupportTicketMessage
        fields = ['id', 'message', 'is_staff_reply', 'is_internal', 'sender', 'sender_name', 'created_at']
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_sender_name(self, obj) -> Optional[str]:
        if obj.sender:
            return obj.sender.get_full_name() or obj.sender.username
        return None


class TicketAssignmentSerializer(serializers.ModelSerializer):
    """Read-only serializer for assignment history."""
    assigned_from_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.SerializerMethodField()
    assigned_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)

    class Meta:
        model = TicketAssignment
        fields = ['id', 'assigned_from', 'assigned_from_name', 'assigned_to', 'assigned_to_name', 'assigned_by', 'assigned_by_name', 'reason', 'assigned_at']
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_assigned_from_name(self, obj) -> Optional[str]:
        if obj.assigned_from:
            return obj.assigned_from.get_full_name() or obj.assigned_from.username
        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_assigned_to_name(self, obj) -> Optional[str]:
        if obj.assigned_to:
            return obj.assigned_to.get_full_name() or obj.assigned_to.username
        return None

    @extend_schema_field(OpenApiTypes.STR)
    def get_assigned_by_name(self, obj) -> Optional[str]:
        if obj.assigned_by:
            return obj.assigned_by.get_full_name() or obj.assigned_by.username
        return None


class TicketListSerializer(serializers.ModelSerializer):
    """Ticket list serializer (concise)"""
    customer_name = serializers.SerializerMethodField()
    priority_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    
    class Meta:
        model = SupportTicket
        fields = [
            'id', 'ticket_number', 'subject', 'customer', 'customer_name',
            'priority', 'priority_name', 'status', 'assigned_to', 'assigned_to_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'ticket_number', 'created_at', 'updated_at']
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_customer_name(self, obj) -> Optional[str]:
        if obj.customer and hasattr(obj.customer, 'user'):
            return obj.customer.user.get_full_name() or obj.customer.user.username
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_priority_name(self, obj) -> Optional[str]:
        if obj.priority:
            return obj.priority.name if hasattr(obj.priority, 'name') else str(obj.priority)
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_assigned_to_name(self, obj) -> Optional[str]:
        if obj.assigned_to:
            return obj.assigned_to.get_full_name() or obj.assigned_to.username
        return None


class TicketDetailSerializer(serializers.ModelSerializer):
    """Ticket detail serializer (full) with first page of messages and assignments."""
    customer_name = serializers.SerializerMethodField()
    customer_data = serializers.SerializerMethodField()
    priority_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_data = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    messages = serializers.SerializerMethodField()
    messages_count = serializers.SerializerMethodField()
    assignments = TicketAssignmentSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            'id', 'ticket_number', 'subject', 'description', 'customer', 'customer_name', 'customer_data',
            'category', 'category_name', 'priority', 'priority_name', 'status', 'channel',
            'assigned_to', 'assigned_to_name', 'assigned_to_data', 'team', 'related_order',
            'created_at', 'updated_at', 'first_response_at', 'resolved_at', 'closed_at',
            'messages', 'messages_count', 'assignments'
        ]
        read_only_fields = [
            'id', 'ticket_number', 'created_at', 'updated_at',
            'first_response_at', 'resolved_at', 'closed_at'
        ]
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_customer_name(self, obj) -> Optional[str]:
        if obj.customer and hasattr(obj.customer, 'user'):
            return obj.customer.user.get_full_name() or obj.customer.user.username
        return None
    
    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_customer_data(self, obj) -> Optional[dict]:
        """Return brief customer data for template rendering"""
        if obj.customer and hasattr(obj.customer, 'user'):
            user = obj.customer.user
            return {
                'id': obj.customer.id,
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'email': user.email or '',
                'company_name': obj.customer.company_name or '',
            }
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_priority_name(self, obj) -> Optional[str]:
        if obj.priority:
            return obj.priority.name if hasattr(obj.priority, 'name') else str(obj.priority)
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_assigned_to_name(self, obj) -> Optional[str]:
        if obj.assigned_to:
            return obj.assigned_to.get_full_name() or obj.assigned_to.username
        return None
    
    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_assigned_to_data(self, obj) -> Optional[dict]:
        """Return brief assigned_to user data for template rendering"""
        if obj.assigned_to:
            return {
                'id': obj.assigned_to.id,
                'first_name': obj.assigned_to.first_name or '',
                'last_name': obj.assigned_to.last_name or '',
                'email': obj.assigned_to.email or '',
                'username': obj.assigned_to.username or '',
            }
        return None
    
    @extend_schema_field(OpenApiTypes.STR)
    def get_category_name(self, obj) -> Optional[str]:
        if obj.category:
            return obj.category.name if hasattr(obj.category, 'name') else str(obj.category)
        return None

    @extend_schema_field(TicketMessageSerializer(many=True))
    def get_messages(self, obj):
        """Return first 10 messages for initial load; use /messages/ action for more."""
        messages = sorted(obj.messages.all(), key=lambda m: m.id)[:10]
        return TicketMessageSerializer(messages, many=True).data

    @extend_schema_field(OpenApiTypes.INT)
    def get_messages_count(self, obj) -> int:
        return obj.messages.count()


class TicketCategorySerializer(serializers.ModelSerializer):
    """Ticket category CRUD serializer."""

    class Meta:
        model = TicketCategory
        fields = ['id', 'name', 'description', 'order', 'is_active']
        read_only_fields = ['id']


class TicketPrioritySerializer(serializers.ModelSerializer):
    """Ticket priority CRUD serializer."""

    class Meta:
        model = TicketPriority
        fields = [
            'id', 'name', 'level', 'color',
            'response_time_hours', 'resolution_time_hours',
            'is_active'
        ]
        read_only_fields = ['id']


class MeTicketCreateSerializer(serializers.ModelSerializer):
    """Serializer for customer creating a ticket via /api/v1/me/tickets/."""

    class Meta:
        model = SupportTicket
        fields = ['subject', 'description', 'category', 'priority']
        extra_kwargs = {
            'category': {'required': False, 'allow_null': True},
            'priority': {'required': False, 'allow_null': True},
        }


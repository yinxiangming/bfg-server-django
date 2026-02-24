# -*- coding: utf-8 -*-
"""
BFG Support Module Serializers
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from typing import Optional

from .models import SupportTicket, TicketCategory, TicketPriority, TicketTag


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
    """Ticket detail serializer (full)"""
    customer_name = serializers.SerializerMethodField()
    customer_data = serializers.SerializerMethodField()
    priority_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    assigned_to_data = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S', read_only=True)
    
    class Meta:
        model = SupportTicket
        fields = [
            'id', 'ticket_number', 'subject', 'description', 'customer', 'customer_name', 'customer_data',
            'category', 'category_name', 'priority', 'priority_name', 'status', 'channel',
            'assigned_to', 'assigned_to_name', 'assigned_to_data', 'team', 'related_order',
            'created_at', 'updated_at', 'first_response_at', 'resolved_at', 'closed_at'
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


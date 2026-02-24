# -*- coding: utf-8 -*-
"""
BFG Support Module API Views
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db import transaction

from bfg.core.permissions import IsWorkspaceStaff
from .models import SupportTicket
from .serializers import TicketListSerializer, TicketDetailSerializer


class SupportTicketViewSet(viewsets.ModelViewSet):
    """Support ticket management ViewSet"""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self.action in ['retrieve', 'create', 'update', 'partial_update']:
            return TicketDetailSerializer
        return TicketListSerializer
    
    def get_queryset(self):
        """Get tickets for current workspace"""
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return SupportTicket.objects.none()
        
        queryset = SupportTicket.objects.filter(workspace=workspace).select_related(
            'customer', 'customer__user', 'priority', 'category', 'assigned_to', 'team'
        ).order_by('-created_at')
        
        # Filter by status if provided
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by priority if provided
        priority_filter = self.request.query_params.get('priority')
        if priority_filter:
            queryset = queryset.filter(priority__name=priority_filter)
        
        return queryset

    def perform_create(self, serializer):
        """
        Set workspace automatically on create.
        """
        workspace = getattr(self.request, 'workspace', None)
        with transaction.atomic():
            # Generate ticket number TKT-YYYYMMDD-XXXX
            today_str = timezone.now().strftime('%Y%m%d')
            prefix = f"TKT-{today_str}-"
            last_ticket = SupportTicket.objects.filter(
                workspace=workspace,
                ticket_number__startswith=prefix
            ).order_by('-ticket_number').first()
            if last_ticket and last_ticket.ticket_number:
                try:
                    last_seq = int(last_ticket.ticket_number.split('-')[-1])
                except (ValueError, IndexError):
                    last_seq = 0
            else:
                last_seq = 0
            next_seq = str(last_seq + 1).zfill(4)
            ticket_number = f"{prefix}{next_seq}"

            serializer.save(workspace=workspace, ticket_number=ticket_number)
    
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close a ticket"""
        ticket = self.get_object()
        ticket.status = 'closed'
        ticket.closed_at = timezone.now()
        ticket.save()
        
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)


# -*- coding: utf-8 -*-
"""
BFG Support Module API Views
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.utils import timezone
from django.db import transaction

from bfg.core.permissions import IsWorkspaceStaff
from .models import SupportTicket, SupportTicketMessage, TicketAssignment, TicketCategory, TicketPriority
from .serializers import (
    TicketListSerializer,
    TicketDetailSerializer,
    TicketMessageSerializer,
    TicketCategorySerializer,
    TicketPrioritySerializer,
)
from .options import get_options


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
        ).prefetch_related('messages', 'assignments').order_by('-created_at')

        # Filter by scope: my = assigned to current user, unassigned = no assignee
        scope = self.request.query_params.get('scope')
        if scope == 'my':
            queryset = queryset.filter(assigned_to=self.request.user)
        elif scope == 'unassigned':
            queryset = queryset.filter(assigned_to__isnull=True)

        # Filter by status (single or in_progress/closed)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            if status_filter == 'in_progress':
                queryset = queryset.filter(status__in=['new', 'open', 'pending', 'on_hold'])
            elif status_filter == 'closed':
                queryset = queryset.filter(status__in=['resolved', 'closed'])
            else:
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

            instance = serializer.save(workspace=workspace, ticket_number=ticket_number)
            if instance.assigned_to_id:
                TicketAssignment.objects.create(
                    ticket=instance,
                    assigned_from=None,
                    assigned_to=instance.assigned_to,
                    assigned_by=self.request.user
                )

    def perform_update(self, serializer):
        """On assigned_to change, create TicketAssignment record."""
        instance = serializer.instance
        old_assigned_to_id = instance.assigned_to_id
        new_assigned_to = serializer.validated_data.get('assigned_to')
        with transaction.atomic():
            serializer.save()
            if new_assigned_to is not None and old_assigned_to_id != new_assigned_to.id:
                TicketAssignment.objects.create(
                    ticket=instance,
                    assigned_from_id=old_assigned_to_id,
                    assigned_to=new_assigned_to,
                    assigned_by=self.request.user
                )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close a ticket"""
        ticket = self.get_object()
        ticket.status = 'closed'
        ticket.closed_at = timezone.now()
        ticket.save()
        serializer = self.get_serializer(ticket)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reply')
    def reply(self, request, pk=None):
        """Add a staff reply to the ticket."""
        ticket = self.get_object()
        message_text = (request.data.get('message') or request.data.get('message_text') or '').strip()
        if not message_text:
            return Response({'detail': 'message is required'}, status=status.HTTP_400_BAD_REQUEST)
        is_internal = request.data.get('is_internal', False)
        with transaction.atomic():
            SupportTicketMessage.objects.create(
                ticket=ticket,
                message=message_text.strip(),
                is_staff_reply=True,
                is_internal=bool(is_internal),
                sender=request.user
            )
            if not ticket.first_response_at:
                ticket.first_response_at = timezone.now()
            if ticket.status == 'new':
                ticket.status = 'open'
            ticket.save(update_fields=['first_response_at', 'status', 'updated_at'])
        serializer = self.get_serializer(ticket)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='messages')
    def list_messages(self, request, pk=None):
        """Paginated messages for ticket (page, page_size)."""
        ticket = self.get_object()
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(50, max(1, int(request.query_params.get('page_size', 10))))
        start = (page - 1) * page_size
        qs = ticket.messages.order_by('id')
        total = qs.count()
        messages = qs[start : start + page_size]
        return Response({
            'count': total,
            'results': TicketMessageSerializer(messages, many=True).data,
            'page': page,
            'page_size': page_size
        })


class SupportOptionsView(APIView):
    """GET /api/v1/support/options/ - ticket statuses, priorities, categories for forms."""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]

    def get(self, request):
        workspace = getattr(request, 'workspace', None)
        if not workspace:
            return Response({'ticket_statuses': [], 'ticket_priorities': [], 'ticket_categories': []})
        data = get_options(workspace)
        return Response(data)


class TicketCategoryViewSet(viewsets.ModelViewSet):
    """Ticket category CRUD for current workspace."""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    serializer_class = TicketCategorySerializer

    def get_queryset(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return TicketCategory.objects.none()
        return TicketCategory.objects.filter(workspace=workspace).order_by('order', 'name')

    def perform_create(self, serializer):
        workspace = getattr(self.request, 'workspace', None)
        if workspace:
            serializer.save(workspace=workspace)


class TicketPriorityViewSet(viewsets.ModelViewSet):
    """Ticket priority CRUD for current workspace."""
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    serializer_class = TicketPrioritySerializer

    def get_queryset(self):
        workspace = getattr(self.request, 'workspace', None)
        if not workspace:
            return TicketPriority.objects.none()
        return TicketPriority.objects.filter(workspace=workspace).order_by('level')

    def perform_create(self, serializer):
        workspace = getattr(self.request, 'workspace', None)
        if workspace:
            serializer.save(workspace=workspace)


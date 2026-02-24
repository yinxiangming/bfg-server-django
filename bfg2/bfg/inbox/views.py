"""
BFG Inbox Module API Views

ViewSets for inbox module
"""

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from bfg.core.permissions import IsWorkspaceAdmin, IsWorkspaceStaff
from bfg.inbox.models import Message, MessageRecipient, MessageTemplate, SMSMessage
from bfg.inbox.serializers import (
    MessageSerializer, MessageRecipientSerializer,
    MessageTemplateSerializer, SMSMessageSerializer
)
from bfg.inbox.services import MessageService


class MessageViewSet(viewsets.ModelViewSet):
    """Message ViewSet (Staff only for sending)"""
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        return Message.objects.filter(
            workspace=self.request.workspace
        ).select_related('sender').order_by('-created_at')
    
    def perform_create(self, serializer):
        """Set workspace and sender automatically on create"""
        serializer.save(
            workspace=self.request.workspace,
            sender=self.request.user
        )
    
    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Send message to recipients"""
        message = self.get_object()
        
        # Get recipient IDs from request
        recipient_ids = request.data.get('recipient_ids', [])
        
        if not recipient_ids:
            return Response(
                {'detail': 'recipient_ids required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add recipients
        from bfg.common.models import Customer
        recipients = Customer.objects.filter(
            workspace=request.workspace,
            id__in=recipient_ids
        )
        
        for recipient in recipients:
            MessageRecipient.objects.get_or_create(
                message=message,
                recipient=recipient
            )
        
        return Response({'status': 'sent', 'recipient_count': len(recipients)})


class MessageRecipientViewSet(viewsets.ReadOnlyModelViewSet):
    """Message recipient ViewSet (Customer's inbox)"""
    serializer_class = MessageRecipientSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        # Get current customer
        from bfg.common.models import Customer
        customer = Customer.objects.filter(
            workspace=self.request.workspace,
            user=self.request.user
        ).first()
        
        if not customer:
            return MessageRecipient.objects.none()
        
        return MessageRecipient.objects.filter(
            recipient=customer,
            is_deleted=False
        ).select_related('message').order_by('-delivered_at')
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """Mark message as read"""
        message_recipient = self.get_object()
        
        service = MessageService(workspace=request.workspace, user=request.user)
        message_recipient = service.mark_as_read(message_recipient)
        
        serializer = self.get_serializer(message_recipient)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get unread message count"""
        from bfg.common.models import Customer
        customer = Customer.objects.filter(
            workspace=request.workspace,
            user=request.user
        ).first()
        
        if not customer:
            return Response({'count': 0})
        
        service = MessageService(workspace=request.workspace, user=request.user)
        count = service.get_unread_count(customer)
        
        return Response({'count': count})
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive message"""
        message_recipient = self.get_object()
        message_recipient.is_archived = True
        message_recipient.save()
        
        return Response({'status': 'archived'})
    
    @action(detail=True, methods=['post'])
    def mark_unread(self, request, pk=None):
        """Mark message as unread"""
        message_recipient = self.get_object()
        message_recipient.is_read = False
        message_recipient.read_at = None
        message_recipient.save()
        
        serializer = self.get_serializer(message_recipient)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """Mark all messages as read"""
        from bfg.common.models import Customer
        customer = Customer.objects.filter(
            workspace=request.workspace,
            user=request.user
        ).first()
        
        if not customer:
            return Response({'detail': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
        
        updated = MessageRecipient.objects.filter(
            recipient=customer,
            is_deleted=False,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return Response({'status': 'success', 'updated_count': updated})
    
    @action(detail=False, methods=['post'])
    def bulk_mark_read(self, request):
        """Bulk mark messages as read"""
        message_ids = request.data.get('message_ids', [])
        
        if not message_ids:
            return Response(
                {'detail': 'message_ids required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from bfg.common.models import Customer
        customer = Customer.objects.filter(
            workspace=request.workspace,
            user=request.user
        ).first()
        
        if not customer:
            return Response({'detail': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
        
        updated = MessageRecipient.objects.filter(
            id__in=message_ids,
            recipient=customer,
            is_deleted=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return Response({'status': 'success', 'updated_count': updated})
    
    @action(detail=False, methods=['post'])
    def bulk_mark_unread(self, request):
        """Bulk mark messages as unread"""
        message_ids = request.data.get('message_ids', [])
        
        if not message_ids:
            return Response(
                {'detail': 'message_ids required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from bfg.common.models import Customer
        customer = Customer.objects.filter(
            workspace=request.workspace,
            user=request.user
        ).first()
        
        if not customer:
            return Response({'detail': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
        
        updated = MessageRecipient.objects.filter(
            id__in=message_ids,
            recipient=customer,
            is_deleted=False
        ).update(
            is_read=False,
            read_at=None
        )
        
        return Response({'status': 'success', 'updated_count': updated})
    
    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        """Bulk delete messages (soft delete)"""
        message_ids = request.data.get('message_ids', [])
        
        if not message_ids:
            return Response(
                {'detail': 'message_ids required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from bfg.common.models import Customer
        customer = Customer.objects.filter(
            workspace=request.workspace,
            user=request.user
        ).first()
        
        if not customer:
            return Response({'detail': 'Customer not found'}, status=status.HTTP_404_NOT_FOUND)
        
        updated = MessageRecipient.objects.filter(
            id__in=message_ids,
            recipient=customer,
            is_deleted=False
        ).update(is_deleted=True)
        
        return Response({'status': 'success', 'deleted_count': updated})


class MessageTemplateViewSet(viewsets.ModelViewSet):
    """Message template ViewSet (Admin only)"""
    serializer_class = MessageTemplateSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdmin]
    
    def get_queryset(self):
        return MessageTemplate.objects.filter(
            workspace=self.request.workspace
        ).order_by('name')
    
    def perform_create(self, serializer):
        """Set workspace automatically on create"""
        serializer.save(workspace=self.request.workspace)


class SMSMessageViewSet(viewsets.ReadOnlyModelViewSet):
    """SMS message ViewSet (Staff only)"""
    serializer_class = SMSMessageSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceStaff]
    
    def get_queryset(self):
        return SMSMessage.objects.filter(
            workspace=self.request.workspace
        ).select_related('customer').order_by('-created_at')

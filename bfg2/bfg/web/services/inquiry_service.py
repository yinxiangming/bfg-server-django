"""
BFG Web Module Services

Inquiry management service for customer submissions
"""

from typing import Any, Dict, Optional
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from bfg.core.services import BaseService
from bfg.web.models import Inquiry, Site


class InquiryService(BaseService):
    """
    Inquiry management service
    
    Handles customer inquiry creation, processing, and notifications
    """
    
    @transaction.atomic
    def create_inquiry(
        self,
        name: str,
        message: str,
        inquiry_type: str = 'inquiry',
        site: Optional[Site] = None,
        **kwargs: Any
    ) -> Inquiry:
        """
        Create a new inquiry from customer submission
        
        Args:
            name: Customer name
            message: Inquiry message
            inquiry_type: Type of inquiry (booking/inquiry/feedback/other)
            site: Optional site reference
            **kwargs: Additional fields (email, phone, subject, form_data, etc.)
            
        Returns:
            Inquiry: Created inquiry instance
        """
        inquiry = Inquiry.objects.create(
            workspace=self.workspace,
            site=site,
            inquiry_type=inquiry_type,
            name=name,
            message=message,
            email=kwargs.get('email', ''),
            phone=kwargs.get('phone', ''),
            subject=kwargs.get('subject', ''),
            form_data=kwargs.get('form_data', {}),
            source_page=kwargs.get('source_page'),
            source_url=kwargs.get('source_url', ''),
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent', ''),
        )
        
        # Trigger notifications asynchronously
        self._send_notifications(inquiry)
        
        return inquiry
    
    def _send_notifications(self, inquiry: Inquiry) -> None:
        """
        Send notifications for new inquiry (email and webhook)
        
        Args:
            inquiry: The inquiry to notify about
        """
        # Get notification config from site or workspace default
        notification_config = {}
        if inquiry.site:
            notification_config = inquiry.site.notification_config or {}
        
        if not notification_config:
            # Try to get from default site
            default_site = Site.objects.filter(
                workspace=self.workspace,
                is_default=True
            ).first()
            if default_site:
                notification_config = default_site.notification_config or {}
        
        # Schedule async tasks
        from bfg.web.tasks import send_inquiry_email, send_inquiry_webhook
        
        email_config = notification_config.get('email', {})
        if email_config.get('enabled') and email_config.get('recipients'):
            send_inquiry_email.delay(inquiry.id)
        
        webhook_config = notification_config.get('webhook', {})
        if webhook_config.get('enabled') and webhook_config.get('url'):
            send_inquiry_webhook.delay(inquiry.id)
    
    def get_inquiries(
        self,
        status: Optional[str] = None,
        inquiry_type: Optional[str] = None,
        assigned_to: Optional[int] = None,
    ) -> QuerySet[Inquiry]:
        """
        Get filtered inquiries list
        
        Args:
            status: Filter by status
            inquiry_type: Filter by inquiry type
            assigned_to: Filter by assigned user ID
            
        Returns:
            QuerySet of inquiries
        """
        queryset = Inquiry.objects.filter(
            workspace=self.workspace
        ).select_related('site', 'source_page', 'assigned_to')
        
        if status:
            queryset = queryset.filter(status=status)
        
        if inquiry_type:
            queryset = queryset.filter(inquiry_type=inquiry_type)
        
        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)
        
        return queryset.order_by('-created_at')
    
    @transaction.atomic
    def update_inquiry_status(
        self,
        inquiry: Inquiry,
        status: str,
        notes: Optional[str] = None,
    ) -> Inquiry:
        """
        Update inquiry status
        
        Args:
            inquiry: Inquiry instance
            status: New status
            notes: Optional internal notes
            
        Returns:
            Updated inquiry
        """
        self.validate_workspace_access(inquiry)
        
        inquiry.status = status
        if notes is not None:
            inquiry.notes = notes
        inquiry.save()
        
        return inquiry
    
    @transaction.atomic
    def assign_inquiry(
        self,
        inquiry: Inquiry,
        user_id: Optional[int],
    ) -> Inquiry:
        """
        Assign inquiry to a user
        
        Args:
            inquiry: Inquiry instance
            user_id: User ID to assign to (None to unassign)
            
        Returns:
            Updated inquiry
        """
        self.validate_workspace_access(inquiry)
        
        if user_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            inquiry.assigned_to = User.objects.get(id=user_id)
        else:
            inquiry.assigned_to = None
        
        inquiry.save()
        
        return inquiry
    
    def mark_notification_sent(self, inquiry: Inquiry) -> None:
        """
        Mark inquiry notification as sent
        
        Args:
            inquiry: Inquiry instance
        """
        inquiry.notification_sent = True
        inquiry.notification_sent_at = timezone.now()
        inquiry.save(update_fields=['notification_sent', 'notification_sent_at'])
    
    def get_inquiry_stats(self) -> Dict[str, Any]:
        """
        Get inquiry statistics
        
        Returns:
            Dict with inquiry stats
        """
        from django.db.models import Count
        
        queryset = Inquiry.objects.filter(workspace=self.workspace)
        
        # Stats by status
        status_stats = queryset.values('status').annotate(count=Count('id'))
        
        # Stats by type
        type_stats = queryset.values('inquiry_type').annotate(count=Count('id'))
        
        # Recent unread count
        pending_count = queryset.filter(status='pending').count()
        
        return {
            'total': queryset.count(),
            'pending': pending_count,
            'by_status': {s['status']: s['count'] for s in status_stats},
            'by_type': {t['inquiry_type']: t['count'] for t in type_stats},
        }

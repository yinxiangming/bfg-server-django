"""
BFG Support Module Services

Ticket management service
"""

from typing import Any, Optional
from django.db import transaction
from bfg.core.services import BaseService
from bfg.support.models import Ticket, TicketMessage, TicketPriority
from bfg.common.models import Customer


class TicketService(BaseService):
    """Support ticket management service"""
    
    @transaction.atomic
    def create_ticket(
        self,
        customer: Customer,
        subject: str,
        message: str,
        **kwargs: Any
    ) -> Ticket:
        """
        Create support ticket
        
        Args:
            customer: Customer instance
            subject: Ticket subject
            message: Initial message
            
        Returns:
            Ticket: Created ticket instance
        """
        # Generate ticket number
        import random, string
        from django.utils import timezone
        date_str = timezone.now().strftime('%Y%m%d')
        random_str = ''.join(random.choices(string.digits, k=5))
        ticket_number = f"TKT-{date_str}-{random_str}"
        
        while Ticket.objects.filter(ticket_number=ticket_number).exists():
            random_str = ''.join(random.choices(string.digits, k=5))
            ticket_number = f"TKT-{date_str}-{random_str}"
        
        # Get default priority
        priority = kwargs.get('priority') or TicketPriority.objects.filter(
            workspace=self.workspace,
            is_default=True
        ).first()
        
        ticket = Ticket.objects.create(
            workspace=self.workspace,
            customer=customer,
            ticket_number=ticket_number,
            subject=subject,
            category=kwargs.get('category'),
            priority=priority,
            status='open',
        )
        
        #  Create first message
        TicketMessage.objects.create(
            ticket=ticket,
            sender_type='customer',
            sender_user=customer.user,
            message=message,
        )
        
        return ticket
    
    def add_message(
        self,
        ticket: Ticket,
        message: str,
        sender_type: str = 'staff'
    ) -> TicketMessage:
        """Add message to ticket"""
        ticket_message = TicketMessage.objects.create(
            ticket=ticket,
            sender_type=sender_type,
            sender_user=self.user,
            message=message,
        )
        
        ticket.updated_at = timezone.now()
        ticket.save()
        
        return ticket_message

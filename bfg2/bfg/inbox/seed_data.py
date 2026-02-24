# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.inbox module.
"""

from datetime import timedelta
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .models import Message, MessageTemplate, MessageRecipient, SMSMessage


def clear_data():
    """Clear inbox module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order
    SMSMessage.objects.all().delete()
    MessageRecipient.objects.all().delete()
    Message.objects.all().delete()
    MessageTemplate.objects.all().delete()
    # 3. Invalidate caches (none for inbox)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed inbox module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (admin_user, customers, customer_users, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating inbox module data...'))
    
    # Check if tables exist
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'inbox_%'")
            tables = cursor.fetchall()
            if not tables:
                if stdout:
                    stdout.write(style.WARNING('⚠️  Inbox tables do not exist. Please run migrations first.'))
                return {}
    except Exception:
        if stdout:
            stdout.write(style.WARNING('⚠️  Could not check inbox tables. Please run migrations first.'))
        return {}
    
    admin_user = context.get('admin_user')
    customers = context.get('customers', [])
    customer_users = context.get('customer_users', [])
    
    # Create message templates
    templates = create_message_templates(workspace, stdout, style)
    
    # Create messages
    messages = create_messages(workspace, admin_user, customers, stdout, style)
    
    # Create message recipients
    create_message_recipients(messages, customers, stdout, style)
    
    # Create SMS messages
    create_sms_messages(workspace, customers, stdout, style)
    
    summary = [
        {'label': 'Messages', 'count': Message.objects.count()},
    ]
    return {
        'templates': templates,
        'messages': messages,
        'summary': summary,
    }


def create_message_templates(workspace, stdout=None, style=None):
    """Create generic message templates (order templates are created in shop module)"""
    templates_data = [
        {
            'name': 'Welcome Message',
            'code': 'welcome',
            'event': 'welcome',
            'email_enabled': True,
            'email_subject': 'Welcome to BFG',
            'email_body': 'Welcome {{customer_name}}! Thank you for joining us.',
            'app_message_enabled': True,
            'app_message_title': 'Welcome',
            'app_message_body': 'Welcome to BFG!',
            'language': 'en',
        },
    ]
    templates = []
    for data in templates_data:
        template, created = MessageTemplate.objects.get_or_create(
            workspace=workspace,
            code=data['code'],
            language=data['language'],
            defaults={
                'name': data['name'],
                'event': data['event'],
                'email_enabled': data.get('email_enabled', False),
                'email_subject': data.get('email_subject', ''),
                'email_body': data.get('email_body', ''),
                'app_message_enabled': data.get('app_message_enabled', False),
                'app_message_title': data.get('app_message_title', ''),
                'app_message_body': data.get('app_message_body', ''),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created message template: {template.name}'))
        templates.append(template)
    return templates


def create_messages(workspace, admin_user, customers, stdout=None, style=None):
    """Create messages"""
    from bfg.shop.models import Order
    
    if not customers:
        return []
    
    messages_data = [
        {
            'subject': 'Your order has been shipped',
            'message': 'Your order ORD-001 has been shipped and is on its way.',
            'message_type': 'notification',
            'action_url': '/orders/ORD-001',
            'action_label': 'View Order',
        },
        {
            'subject': 'Payment received',
            'message': 'We have received your payment of $109.99. Thank you!',
            'message_type': 'notification',
            'action_url': '/payments',
            'action_label': 'View Payment',
        },
        {
            'subject': 'Welcome to BFG',
            'message': 'Thank you for joining BFG. We are excited to have you!',
            'message_type': 'announcement',
        },
    ]
    
    messages = []
    orders = Order.objects.filter(workspace=workspace)[:5]
    
    for i, data in enumerate(messages_data * 3):
        customer = customers[i % len(customers)]
        
        # Link to order if available
        related_content_type = None
        related_object_id = None
        if i < len(orders):
            order = orders[i]
            related_content_type = ContentType.objects.get_for_model(Order)
            related_object_id = order.id
        
        message = Message.objects.create(
            workspace=workspace,
            subject=data['subject'],
            message=data['message'],
            message_type=data['message_type'],
            sender=admin_user if i % 2 == 0 else None,
            action_url=data.get('action_url', ''),
            action_label=data.get('action_label', ''),
            related_content_type=related_content_type,
            related_object_id=related_object_id,
            send_email=(i % 2 == 0),
            send_push=(i % 3 == 0),
            created_at=timezone.now() - timedelta(days=i % 10),
        )
        messages.append(message)
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(messages)} messages'))
    return messages


def create_message_recipients(messages, customers, stdout=None, style=None):
    """Create message recipients"""
    if not messages or not customers:
        return
    
    recipients = []
    for i, message in enumerate(messages):
        customer = customers[i % len(customers)]
        is_read = (i % 3 == 0)
        
        recipient = MessageRecipient.objects.create(
            message=message,
            recipient=customer,
            is_read=is_read,
            is_archived=(i % 5 == 0),
            read_at=timezone.now() - timedelta(days=i % 5) if is_read else None,
            delivered_at=message.created_at,
        )
        recipients.append(recipient)
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(recipients)} message recipients'))


def create_sms_messages(workspace, customers, stdout=None, style=None):
    """Create SMS messages"""
    if not customers:
        return
    
    sms_messages = []
    sms_data = [
        {'message': 'Your order has been shipped. Track: https://xmart.com/track/TRK001'},
        {'message': 'Payment of $109.99 received. Thank you!'},
        {'message': 'Your support ticket has been updated. Check your account.'},
    ]
    
    for i, customer in enumerate(customers[:5]):
        data = sms_data[i % len(sms_data)]
        statuses = ['sent', 'delivered', 'pending']
        status = statuses[i % len(statuses)]
        
        sms = SMSMessage.objects.create(
            workspace=workspace,
            customer=customer,
            phone_number=customer.user.phone or '+1-555-0000',
            message=data['message'],
            status=status,
            provider='Twilio',
            provider_id=f'sms_{customer.id}_{i}',
            sent_at=timezone.now() - timedelta(hours=i) if status != 'pending' else None,
            delivered_at=timezone.now() - timedelta(hours=i-1) if status == 'delivered' else None,
            created_at=timezone.now() - timedelta(hours=i+1),
        )
        sms_messages.append(sms)
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(sms_messages)} SMS messages'))


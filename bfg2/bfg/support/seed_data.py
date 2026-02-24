# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.support module.
"""

from datetime import timedelta
from django.utils import timezone
from django.db import IntegrityError
from .models import (
    TicketCategory, TicketPriority, SupportTeam, TicketTag,
    SupportTicket, SupportTicketMessage, TicketAssignment,
    FeedbackCategory, UserFeedback, SLA, KnowledgeCategory, 
    KnowledgeBase, TicketTemplate
)


def clear_data():
    """Clear support module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order
    TicketAssignment.objects.all().delete()
    SupportTicketMessage.objects.all().delete()
    SupportTicket.objects.all().delete()
    TicketTemplate.objects.all().delete()
    TicketTag.objects.all().delete()
    UserFeedback.objects.all().delete()
    FeedbackCategory.objects.all().delete()
    KnowledgeBase.objects.all().delete()
    KnowledgeCategory.objects.all().delete()
    SLA.objects.all().delete()
    SupportTeam.objects.all().delete()
    TicketPriority.objects.all().delete()
    TicketCategory.objects.all().delete()
    # 3. Invalidate caches (none for support)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed support module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context (admin_user, staff_users, customer_users, customers, etc.)
    
    Returns:
        dict: Created data
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating support module data...'))
    
    admin_user = context.get('admin_user')
    staff_users = context.get('staff_users', [])
    customer_users = context.get('customer_users', [])
    customers = context.get('customers', [])
    
    # Create ticket categories
    categories = create_ticket_categories(workspace, stdout, style)
    
    # Create ticket priorities
    priorities = create_ticket_priorities(workspace, stdout, style)
    
    # Create support teams
    teams = create_support_teams(workspace, staff_users, stdout, style)
    
    # Create ticket tags
    tags = create_ticket_tags(workspace, stdout, style)
    
    # Create tickets
    tickets = create_support_tickets(
        workspace, customers, categories, priorities, teams, tags, staff_users, stdout, style
    )
    
    # Create ticket messages
    create_ticket_messages(tickets, staff_users, customer_users, stdout, style)
    
    # Create ticket assignments
    create_ticket_assignments(tickets, staff_users, admin_user, stdout, style)
    
    # Create feedback categories
    feedback_categories = create_feedback_categories(workspace, stdout, style)
    
    # Create user feedback
    create_user_feedback(workspace, customers, feedback_categories, stdout, style)
    
    # Create SLAs
    slas = create_slas(workspace, priorities, stdout, style)
    
    # Create knowledge base categories
    kb_categories = create_knowledge_categories(workspace, stdout, style)
    
    # Create knowledge base articles
    kb_articles = create_knowledge_articles(workspace, kb_categories, stdout, style)
    
    # Create ticket templates
    templates = create_ticket_templates(workspace, categories, stdout, style)
    
    summary = [
        {'label': 'Support Tickets', 'count': SupportTicket.objects.count()},
    ]
    return {
        'categories': categories,
        'priorities': priorities,
        'teams': teams,
        'tags': tags,
        'tickets': tickets,
        'feedback_categories': feedback_categories,
        'slas': slas,
        'kb_categories': kb_categories,
        'kb_articles': kb_articles,
        'templates': templates,
        'summary': summary,
    }


def create_ticket_categories(workspace, stdout=None, style=None):
    """Create ticket categories"""
    categories_data = [
        {'name': 'Technical Support', 'description': 'Technical issues and troubleshooting', 'order': 1},
        {'name': 'Billing', 'description': 'Billing and payment questions', 'order': 2},
        {'name': 'Shipping', 'description': 'Shipping and delivery inquiries', 'order': 3},
        {'name': 'Product Inquiry', 'description': 'Questions about products', 'order': 4},
        {'name': 'Account', 'description': 'Account management issues', 'order': 5},
    ]
    categories = []
    for data in categories_data:
        category, created = TicketCategory.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'description': data['description'],
                'order': data['order'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created ticket category: {category.name}'))
        categories.append(category)
    return categories


def create_ticket_priorities(workspace, stdout=None, style=None):
    """Create ticket priorities"""
    priorities_data = [
        {'name': 'Low', 'level': 1, 'color': '#9E9E9E', 'response_time_hours': 48, 'resolution_time_hours': 120},
        {'name': 'Normal', 'level': 2, 'color': '#2196F3', 'response_time_hours': 24, 'resolution_time_hours': 72},
        {'name': 'High', 'level': 3, 'color': '#FF9800', 'response_time_hours': 12, 'resolution_time_hours': 48},
        {'name': 'Urgent', 'level': 4, 'color': '#F44336', 'response_time_hours': 4, 'resolution_time_hours': 24},
        {'name': 'Critical', 'level': 5, 'color': '#D32F2F', 'response_time_hours': 1, 'resolution_time_hours': 8},
    ]
    priorities = []
    for data in priorities_data:
        priority, created = TicketPriority.objects.get_or_create(
            workspace=workspace,
            level=data['level'],
            defaults={
                'name': data['name'],
                'color': data['color'],
                'response_time_hours': data['response_time_hours'],
                'resolution_time_hours': data['resolution_time_hours'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created ticket priority: {priority.name}'))
        priorities.append(priority)
    return priorities


def create_support_teams(workspace, staff_users, stdout=None, style=None):
    """Create support teams"""
    teams_data = [
        {'name': 'Technical Support Team', 'description': 'Handles technical issues'},
        {'name': 'Customer Service Team', 'description': 'Handles general customer inquiries'},
        {'name': 'Billing Team', 'description': 'Handles billing and payment issues'},
    ]
    teams = []
    for i, data in enumerate(teams_data):
        team, created = SupportTeam.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'description': data['description'],
                'is_active': True,
            }
        )
        if created:
            # Assign staff members to teams
            if i < len(staff_users):
                team.members.add(staff_users[i])
            if i == 0 and len(staff_users) > 0:
                team.members.add(staff_users[0])
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created support team: {team.name}'))
        teams.append(team)
    return teams


def create_ticket_tags(workspace, stdout=None, style=None):
    """Create ticket tags"""
    tags_data = [
        {'name': 'bug', 'color': '#F44336'},
        {'name': 'feature-request', 'color': '#2196F3'},
        {'name': 'billing', 'color': '#4CAF50'},
        {'name': 'shipping', 'color': '#FF9800'},
        {'name': 'urgent', 'color': '#D32F2F'},
        {'name': 'follow-up', 'color': '#9C27B0'},
    ]
    tags = []
    for data in tags_data:
        tag, created = TicketTag.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'color': data['color'],
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created ticket tag: {tag.name}'))
        tags.append(tag)
    return tags


def create_support_tickets(workspace, customers, categories, priorities, teams, tags, staff_users, stdout=None, style=None):
    """Create support tickets"""
    from bfg.shop.models import Order
    
    if not customers:
        return []
    
    tickets = []
    ticket_subjects = [
        'Product not delivered on time',
        'Billing question about invoice',
        'Need help with account setup',
        'Technical issue with website',
        'Shipping address change request',
        'Product quality concern',
        'Refund request',
        'Order cancellation',
        'Payment method not working',
        'Account access problem',
        'Product return inquiry',
        'Shipping tracking question',
        'Discount code not working',
        'Order modification needed',
        'General inquiry',
    ]
    
    # Get some orders for related_order
    orders = Order.objects.filter(workspace=workspace)[:5]
    
    for i, subject in enumerate(ticket_subjects):
        customer = customers[i % len(customers)]
        category = categories[i % len(categories)]
        priority = priorities[min(i % len(priorities), 3)]
        team = teams[i % len(teams)] if teams else None
        assigned_to = staff_users[i % len(staff_users)] if staff_users else None
        
        statuses = ['new', 'open', 'pending', 'on_hold', 'resolved', 'closed']
        status = statuses[i % len(statuses)]
        
        channels = ['web', 'email', 'phone', 'chat']
        channel = channels[i % len(channels)]
        
        ticket_number = f'TKT-{timezone.now().strftime("%Y%m%d")}-{i+1:04d}'
        related_order = orders[i % len(orders)] if orders and i < len(orders) else None
        
        try:
            ticket, created = SupportTicket.objects.get_or_create(
                ticket_number=ticket_number,
                defaults={
                    'workspace': workspace,
                    'customer': customer,
                    'subject': subject,
                    'description': f'Customer inquiry about: {subject}. This is a sample ticket description for testing purposes.',
                    'category': category,
                    'priority': priority,
                    'status': status,
                    'channel': channel,
                    'assigned_to': assigned_to,
                    'team': team,
                    'related_order': related_order,
                    'created_at': timezone.now() - timedelta(days=i % 10),
                }
            )
            if created:
                # Add tags
                if tags:
                    ticket.tags.add(tags[i % len(tags)])
                    if i % 3 == 0 and len(tags) > 1:
                        ticket.tags.add(tags[(i + 1) % len(tags)])
                
                # Set timestamps based on status
                if status in ['resolved', 'closed']:
                    ticket.resolved_at = ticket.created_at + timedelta(hours=24)
                    if status == 'closed':
                        ticket.closed_at = ticket.resolved_at + timedelta(hours=1)
                if status in ['open', 'pending', 'on_hold', 'resolved', 'closed']:
                    ticket.first_response_at = ticket.created_at + timedelta(hours=2)
                ticket.save()
                
                tickets.append(ticket)
        except IntegrityError:
            pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(tickets)} support tickets'))
    return tickets


def create_ticket_messages(tickets, staff_users, customer_users, stdout=None, style=None):
    """Create ticket messages"""
    messages = []
    
    for ticket in tickets[:10]:
        customer = ticket.customer.user
        if customer in customer_users:
            try:
                customer_msg = SupportTicketMessage.objects.create(
                    ticket=ticket,
                    sender=customer,
                    message=ticket.description,
                    is_staff_reply=False,
                    is_internal=False,
                    created_at=ticket.created_at,
                )
                messages.append(customer_msg)
            except IntegrityError:
                pass
        
        if ticket.status != 'new' and staff_users:
            staff = staff_users[ticket.id % len(staff_users)]
            reply_messages = [
                'Thank you for contacting us. We are looking into this issue.',
                'We have received your request and will update you shortly.',
                'I understand your concern. Let me investigate this for you.',
            ]
            try:
                staff_msg = SupportTicketMessage.objects.create(
                    ticket=ticket,
                    sender=staff,
                    message=reply_messages[ticket.id % len(reply_messages)],
                    is_staff_reply=True,
                    is_internal=False,
                    created_at=ticket.created_at + timedelta(hours=2),
                )
                messages.append(staff_msg)
            except IntegrityError:
                pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(messages)} ticket messages'))


def create_ticket_assignments(tickets, staff_users, admin_user, stdout=None, style=None):
    """Create ticket assignment history"""
    assignments = []
    
    for ticket in tickets:
        if ticket.assigned_to:
            try:
                assignment = TicketAssignment.objects.create(
                    ticket=ticket,
                    assigned_to=ticket.assigned_to,
                    assigned_by=admin_user,
                    reason='Initial assignment',
                    assigned_at=ticket.created_at,
                )
                assignments.append(assignment)
            except IntegrityError:
                pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(assignments)} ticket assignments'))


def create_feedback_categories(workspace, stdout=None, style=None):
    """Create feedback categories"""
    categories_data = [
        {'name': 'Website', 'icon': 'mdi:web', 'order': 1},
        {'name': 'Mobile App', 'icon': 'mdi:cellphone', 'order': 2},
        {'name': 'Service', 'icon': 'mdi:headset', 'order': 3},
        {'name': 'Product', 'icon': 'mdi:package-variant', 'order': 4},
        {'name': 'Other', 'icon': 'mdi:dots-horizontal', 'order': 5},
    ]
    categories = []
    for data in categories_data:
        category, created = FeedbackCategory.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'icon': data['icon'],
                'order': data['order'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created feedback category: {category.name}'))
        categories.append(category)
    return categories


def create_user_feedback(workspace, customers, feedback_categories, stdout=None, style=None):
    """Create user feedback"""
    if not customers:
        return
    
    feedback_data = [
        {
            'feedback_type': 'bug',
            'title': 'Login button not working',
            'message': 'The login button on the homepage does not respond when clicked.',
            'page_url': 'https://demo.xmart.com/login',
        },
        {
            'feedback_type': 'suggestion',
            'title': 'Add dark mode',
            'message': 'It would be great to have a dark mode option for the website.',
            'page_url': 'https://demo.xmart.com/settings',
        },
    ]
    
    feedback_types = ['bug', 'suggestion', 'complaint', 'praise', 'other']
    feedbacks = []
    
    for i in range(10):
        customer = customers[i % len(customers)] if customers else None
        category = feedback_categories[i % len(feedback_categories)] if feedback_categories else None
        feedback_type = feedback_types[i % len(feedback_types)]
        data = feedback_data[i % len(feedback_data)]
        
        try:
            feedback = UserFeedback.objects.create(
                workspace=workspace,
                customer=customer,
                feedback_type=feedback_type,
                category=category,
                title=data['title'],
                message=data['message'],
                page_url=data['page_url'],
                browser='Chrome',
                device='Desktop',
                is_reviewed=(i % 3 == 0),
                reviewed_at=timezone.now() - timedelta(days=i % 5) if i % 3 == 0 else None,
                created_at=timezone.now() - timedelta(days=i % 10),
            )
            feedbacks.append(feedback)
        except IntegrityError:
            pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(feedbacks)} user feedback entries'))


def create_slas(workspace, priorities, stdout=None, style=None):
    """Create SLAs"""
    slas_data = [
        {
            'name': 'Standard SLA',
            'description': 'Standard service level agreement for normal priority tickets',
            'first_response_hours': 4,
            'resolution_hours': 48,
            'priority_levels': [1, 2],  # Low, Normal
        },
        {
            'name': 'Premium SLA',
            'description': 'Premium service level agreement for high priority tickets',
            'first_response_hours': 2,
            'resolution_hours': 24,
            'priority_levels': [3, 4],  # High, Urgent
        },
        {
            'name': 'Critical SLA',
            'description': 'Critical service level agreement for critical priority tickets',
            'first_response_hours': 1,
            'resolution_hours': 8,
            'priority_levels': [5],  # Critical
        },
    ]
    
    slas = []
    for data in slas_data:
        priority_levels = data.pop('priority_levels', [])
        sla, created = SLA.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'description': data['description'],
                'first_response_hours': data['first_response_hours'],
                'resolution_hours': data['resolution_hours'],
                'is_active': True,
            }
        )
        if created:
            # Add priorities
            for level in priority_levels:
                priority = next((p for p in priorities if p.level == level), None)
                if priority:
                    sla.priorities.add(priority)
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created SLA: {sla.name}'))
        slas.append(sla)
    
    return slas


def create_knowledge_categories(workspace, stdout=None, style=None):
    """Create knowledge base categories"""
    categories_data = [
        {
            'name': 'Getting Started',
            'slug': 'getting-started',
            'description': 'Basic information to help you get started',
            'icon': 'mdi:rocket',
            'order': 1,
        },
        {
            'name': 'Account Management',
            'slug': 'account-management',
            'description': 'Managing your account settings and profile',
            'icon': 'mdi:account',
            'order': 2,
        },
        {
            'name': 'Shipping & Delivery',
            'slug': 'shipping-delivery',
            'description': 'Information about shipping and delivery',
            'icon': 'mdi:truck',
            'order': 3,
        },
        {
            'name': 'Billing & Payments',
            'slug': 'billing-payments',
            'description': 'Billing, payments, and invoices',
            'icon': 'mdi:credit-card',
            'order': 4,
        },
        {
            'name': 'Troubleshooting',
            'slug': 'troubleshooting',
            'description': 'Common issues and how to resolve them',
            'icon': 'mdi:wrench',
            'order': 5,
        },
    ]
    
    categories = []
    for data in categories_data:
        category, created = KnowledgeCategory.objects.get_or_create(
            workspace=workspace,
            slug=data['slug'],
            defaults={
                'name': data['name'],
                'description': data['description'],
                'icon': data.get('icon', ''),
                'order': data.get('order', 100),
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created knowledge category: {category.name}'))
        categories.append(category)
    
    return categories


def create_knowledge_articles(workspace, categories, stdout=None, style=None):
    """Create knowledge base articles"""
    articles_data = [
        {
            'title': 'How to Create an Account',
            'slug': 'how-to-create-account',
            'content': '<h2>Creating Your Account</h2><p>Follow these simple steps to create your XMart account:</p><ol><li>Visit the registration page</li><li>Fill in your details</li><li>Verify your email</li><li>Start shipping!</li></ol>',
            'keywords': 'account, registration, signup',
            'category_slug': 'getting-started',
        },
        {
            'title': 'How to Track Your Shipment',
            'slug': 'how-to-track-shipment',
            'content': '<h2>Tracking Your Shipment</h2><p>You can track your shipment using the tracking number provided in your confirmation email.</p>',
            'keywords': 'tracking, shipment, delivery',
            'category_slug': 'shipping-delivery',
        },
        {
            'title': 'Payment Methods Accepted',
            'slug': 'payment-methods',
            'content': '<h2>Accepted Payment Methods</h2><p>We accept the following payment methods:</p><ul><li>Credit/Debit Cards</li><li>PayPal</li><li>Bank Transfer</li><li>WeChat Pay</li></ul>',
            'keywords': 'payment, billing, methods',
            'category_slug': 'billing-payments',
        },
        {
            'title': 'Updating Your Profile',
            'slug': 'updating-profile',
            'content': '<h2>Update Your Profile</h2><p>To update your profile information, go to Settings > Profile and make your changes.</p>',
            'keywords': 'profile, settings, account',
            'category_slug': 'account-management',
        },
        {
            'title': 'Common Login Issues',
            'slug': 'common-login-issues',
            'content': '<h2>Troubleshooting Login</h2><p>If you are having trouble logging in, try these steps:</p><ol><li>Check your internet connection</li><li>Verify your credentials</li><li>Reset your password if needed</li><li>Clear browser cache</li></ol>',
            'keywords': 'login, password, troubleshooting',
            'category_slug': 'troubleshooting',
        },
    ]
    
    articles = []
    for data in articles_data:
        category_slug = data.pop('category_slug', None)
        category = next((c for c in categories if c.slug == category_slug), None) if category_slug else None
        
        if not category:
            continue
        
        article, created = KnowledgeBase.objects.get_or_create(
            workspace=workspace,
            slug=data['slug'],
            defaults={
                'title': data['title'],
                'content': data['content'],
                'keywords': data.get('keywords', ''),
                'category': category,
                'is_published': True,
                'is_featured': False,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created knowledge article: {article.title}'))
        articles.append(article)
    
    return articles


def create_ticket_templates(workspace, categories, stdout=None, style=None):
    """Create ticket response templates"""
    templates_data = [
        {
            'name': 'Welcome Response',
            'subject': 'Thank you for contacting us',
            'content': 'Dear Customer,\n\nThank you for reaching out to XMart support. We have received your inquiry and will respond within 24 hours.\n\nBest regards,\nXMart Support Team',
            'category_name': None,
        },
        {
            'name': 'Shipping Delay',
            'subject': 'Regarding your shipment delay',
            'content': 'Dear Customer,\n\nWe apologize for the delay in your shipment. We are working to resolve this issue and will keep you updated.\n\nThank you for your patience.\n\nBest regards,\nXMart Support Team',
            'category_name': 'Shipping',
        },
        {
            'name': 'Refund Request',
            'subject': 'Your refund request',
            'content': 'Dear Customer,\n\nWe have received your refund request. Our team will review it and process within 5-7 business days.\n\nBest regards,\nXMart Support Team',
            'category_name': 'Billing',
        },
        {
            'name': 'Account Issue Resolution',
            'subject': 'Your account issue has been resolved',
            'content': 'Dear Customer,\n\nWe are pleased to inform you that your account issue has been resolved. You should now be able to access all features.\n\nIf you continue to experience any problems, please let us know.\n\nBest regards,\nXMart Support Team',
            'category_name': 'Account',
        },
        {
            'name': 'Technical Support Follow-up',
            'subject': 'Following up on your technical issue',
            'content': 'Dear Customer,\n\nWe wanted to follow up on the technical issue you reported. Have you had a chance to try the solution we suggested?\n\nPlease let us know if you need any further assistance.\n\nBest regards,\nXMart Technical Support',
            'category_name': 'Technical Support',
        },
    ]
    
    templates = []
    for data in templates_data:
        category_name = data.pop('category_name', None)
        category = next((c for c in categories if c.name == category_name), None) if category_name else None
        
        template, created = TicketTemplate.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'subject': data['subject'],
                'content': data['content'],
                'category': category,
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created ticket template: {template.name}'))
        templates.append(template)
    
    return templates


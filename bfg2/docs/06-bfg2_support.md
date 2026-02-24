# BFG2_SUPPORT Module - Customer Support & Ticketing

## Overview

The `bfg2_support` module provides a comprehensive customer support system with ticket management, knowledge base, and SLA tracking.

## Features

- 🎫 **Ticket System** - Create and manage support tickets
- 💬 **Multi-channel Support** - Email, chat, phone integration
- 📚 **Knowledge Base** - Self-service help articles
- ⏱️ **SLA Tracking** - Service level agreement monitoring
- 📋 **Categories & Priorities** - Organized ticket management
- 👥 **Assignment & Escalation** - Ticket routing
- 📊 **Analytics** - Support metrics and reporting
- 📝 **Response Templates** - Quick replies

## Models

### TicketCategory

**Purpose**: Support ticket categorization.

```python
class TicketCategory(models.Model):
    """
    Support ticket category.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    
    # Default assignment
    default_assignee = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    default_priority = models.CharField(max_length=20, default='medium')
    
    # SLA
    sla = models.ForeignKey('SLA', on_delete=models.SET_NULL, null=True, blank=True)
    
    icon = models.CharField(max_length=50, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('workspace', 'slug')
        verbose_name_plural = 'Ticket Categories'
```

---

### TicketPriority

**Purpose**: Customizable ticket priorities.

```python
class TicketPriority(models.Model):
    """
    Ticket priority level (customizable per workspace).
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # SLA impact
    response_hours = models.IntegerField(default=24)
    resolution_hours = models.IntegerField(default=72)
    
    # Display
    color = models.CharField(max_length=7, default='#000000')
    order = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('workspace', 'code')
        verbose_name_plural = 'Ticket Priorities'
```

---

### SupportTicket

**Purpose**: Customer support ticket.

**Migrated from**: `freight/models/support.py`

```python
class SupportTicket(models.Model):
    """
    Customer support ticket.
    """
    STATUS_CHOICES = (
        ('new', 'New'),
        ('open', 'Open'),
        ('pending', 'Pending'),
        ('on_hold', 'On Hold'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    )
    
    CHANNEL_CHOICES = (
        ('web', 'Web Form'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('chat', 'Live Chat'),
        ('social', 'Social Media'),
        ('api', 'API'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    customer = models.ForeignKey('common.Customer', on_delete=models.PROTECT)
    
    # Identification
    ticket_number = models.CharField(max_length=50, unique=True)
    
    # Content
    subject = models.CharField(max_length=255)
    description = models.TextField()
    
    # Classification
    category = models.ForeignKey(TicketCategory, on_delete=models.SET_NULL, null=True, blank=True)
    priority = models.ForeignKey(TicketPriority, on_delete=models.PROTECT)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    
    # Assignment
    assigned_to = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')
    team = models.ForeignKey('SupportTeam', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Source
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='web')
    source_email = models.EmailField(blank=True)
    source_phone = models.CharField(max_length=50, blank=True)
    
    # Related records
    order = models.ForeignKey('bfg2_shop.Order', on_delete=models.SET_NULL, null=True, blank=True)
    consignment = models.ForeignKey('bfg2_delivery.Consignment', on_delete=models.SET_NULL, null=True, blank=True)
    
    # SLA
    sla = models.ForeignKey('SLA', on_delete=models.SET_NULL, null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    
    # SLA breach tracking
    response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    response_breached = models.BooleanField(default=False)
    resolution_breached = models.BooleanField(default=False)
    
    # Satisfaction
    satisfaction_rating = models.IntegerField(null=True, blank=True)  # 1-5
    satisfaction_comment = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Indexes**: `ticket_number`, `workspace + customer`, `status`, `assigned_to`, `created_at`

---

### SupportTicketMessage

**Purpose**: Messages/replies within a ticket.

**Migrated from**: `freight/models/support.py`

```python
class SupportTicketMessage(models.Model):
    """
    Message within a support ticket.
    """
    MESSAGE_TYPE_CHOICES = (
        ('customer', 'Customer Message'),
        ('agent', 'Agent Reply'),
        ('note', 'Internal Note'),
        ('system', 'System Message'),
    )
    
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    
    # Content
    message = models.TextField()
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default='customer')
    
    # Sender
    sender = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    sender_name = models.CharField(max_length=100, blank=True)  # For customer messages
    sender_email = models.EmailField(blank=True)
    
    # Flags
    is_staff_reply = models.BooleanField(default=False)
    is_internal = models.BooleanField(default=False)  # Internal note, not visible to customer
    
    # Attachments
    attachments = models.JSONField(default=list, blank=True)
    # [{"filename": "screenshot.png", "url": "/media/..."}]
    
    # Email tracking
    email_message_id = models.CharField(max_length=255, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
```

---

### TicketAttachment

**Purpose**: File attachments on tickets.

```python
class TicketAttachment(models.Model):
    """
    File attachment for support tickets.
    """
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='attachments')
    message = models.ForeignKey(SupportTicketMessage, on_delete=models.SET_NULL, null=True, blank=True)
    
    file = models.FileField(upload_to='support/attachments/%Y/%m/')
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()  # bytes
    mime_type = models.CharField(max_length=100)
    
    uploaded_by = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
```

---

### SupportTeam

**Purpose**: Support team organization.

```python
class SupportTeam(models.Model):
    """
    Support team.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Members
    members = models.ManyToManyField('common.User', related_name='support_teams')
    team_lead = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Assignment
    email = models.EmailField(blank=True)  # Team email for ticket routing
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### TicketAssignment

**Purpose**: Ticket assignment history and rules.

```python
class TicketAssignment(models.Model):
    """
    Ticket assignment log.
    """
    ACTION_CHOICES = (
        ('assigned', 'Assigned'),
        ('reassigned', 'Reassigned'),
        ('unassigned', 'Unassigned'),
        ('escalated', 'Escalated'),
    )
    
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='assignment_history')
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    
    from_user = models.ForeignKey('common.User', related_name='assignments_from', on_delete=models.SET_NULL, null=True, blank=True)
    to_user = models.ForeignKey('common.User', related_name='assignments_to', on_delete=models.SET_NULL, null=True, blank=True)
    
    reason = models.TextField(blank=True)
    
    created_by = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### SLA

**Purpose**: Service Level Agreement configuration.

```python
class SLA(models.Model):
    """
    Service Level Agreement.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Time targets (in hours)
    first_response_hours = models.IntegerField(default=24)
    resolution_hours = models.IntegerField(default=72)
    
    # Business hours
    uses_business_hours = models.BooleanField(default=True)
    business_hours_start = models.TimeField(default='09:00')
    business_hours_end = models.TimeField(default='17:00')
    business_days = models.JSONField(default=list)  # [1, 2, 3, 4, 5] = Mon-Fri
    
    # Escalation
    escalate_on_breach = models.BooleanField(default=True)
    escalation_team = models.ForeignKey(SupportTeam, on_delete=models.SET_NULL, null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### KnowledgeCategory

**Purpose**: Knowledge base article categorization.

```python
class KnowledgeCategory(models.Model):
    """
    Knowledge base category.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
    
    icon = models.CharField(max_length=50, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    # Language
    language = models.CharField(max_length=10)
    
    class Meta:
        unique_together = ('workspace', 'slug', 'language')
        verbose_name_plural = 'Knowledge Categories'
```

---

### KnowledgeBase

**Purpose**: Help articles and documentation.

```python
class KnowledgeBase(models.Model):
    """
    Knowledge base article.
    """
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    )
    
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    # Content
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    content = models.TextField()
    excerpt = models.TextField(blank=True)
    
    # Organization
    category = models.ForeignKey(KnowledgeCategory, on_delete=models.SET_NULL, null=True, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    
    # SEO
    meta_description = models.TextField(blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Engagement
    view_count = models.IntegerField(default=0)
    helpful_count = models.IntegerField(default=0)
    not_helpful_count = models.IntegerField(default=0)
    
    # Language
    language = models.CharField(max_length=10)
    
    # Publishing
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Author
    author = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('workspace', 'slug', 'language')
```

---

### TicketTemplate

**Purpose**: Canned responses and templates.

```python
class TicketTemplate(models.Model):
    """
    Response template for quick replies.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=100)
    subject = models.CharField(max_length=255, blank=True)
    content = models.TextField()
    
    # Category filter
    categories = models.ManyToManyField(TicketCategory, blank=True)
    
    # Usage
    usage_count = models.IntegerField(default=0)
    
    # Language
    language = models.CharField(max_length=10)
    
    is_active = models.BooleanField(default=True)
    
    created_by = models.ForeignKey('common.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### TicketTag

**Purpose**: Flexible ticket tagging.

```python
class TicketTag(models.Model):
    """
    Ticket tag for flexible organization.
    """
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50)
    color = models.CharField(max_length=7, default='#000000')
    
    class Meta:
        unique_together = ('workspace', 'slug')
```

---

## API Endpoints

### Tickets
- `GET /api/support/tickets/` - List customer tickets
- `GET /api/support/tickets/{ticket_number}/` - Get ticket details
- `POST /api/support/tickets/` - Create new ticket
- `POST /api/support/tickets/{id}/reply/` - Reply to ticket
- `PUT /api/support/tickets/{id}/status/` - Update ticket status
- `POST /api/support/tickets/{id}/rate/` - Rate ticket resolution

### Knowledge Base
- `GET /api/support/kb/` - List articles
- `GET /api/support/kb/{slug}/` - Get article
- `GET /api/support/kb/categories/` - List categories
- `GET /api/support/kb/search/` - Search articles
- `POST /api/support/kb/{id}/helpful/` - Mark article helpful

### Admin
- `GET /api/support/admin/tickets/` - List all tickets (admin)
- `POST /api/support/admin/tickets/{id}/assign/` - Assign ticket
- `GET /api/support/templates/` - Get response templates
- `GET /api/support/stats/` - Support metrics

## Integration with Other Modules

- **bfg2_shop**: Link tickets to orders
- **bfg2_delivery**: Link tickets to consignments
- **common**: User and customer management

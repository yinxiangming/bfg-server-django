# -*- coding: utf-8 -*-
"""
Seed data functions for bfg.common module.
"""

import os
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import (
    Workspace, Customer, CustomerSegment, CustomerTag, Address, StaffRole, StaffMember, EmailConfig, Settings
)
from .utils import get_smtp_config_from_env

# Minimal country list for seed and options API
COUNTRY_LIST = [
    {'code': 'NZ', 'name': 'New Zealand'},
    {'code': 'CN', 'name': 'China'},
    {'code': 'US', 'name': 'United States'},
    {'code': 'KR', 'name': 'South Korea'},
]

User = get_user_model()


def clear_data():
    """Clear common module data. Process: (1) collect cache keys if any, (2) delete in dependency order, (3) invalidate caches if any."""
    # 1. Collect cache keys before delete (this module has no cache)
    # 2. Delete in dependency order
    Address.objects.all().delete()
    CustomerTag.objects.all().delete()
    CustomerSegment.objects.all().delete()
    Customer.objects.all().delete()
    StaffMember.objects.all().delete()
    StaffRole.objects.all().delete()
    # Keep workspace and users for now
    # 3. Invalidate caches (none for common)


def seed_data(workspace, stdout=None, style=None, **context):
    """
    Seed common module data.
    
    Args:
        workspace: Workspace instance
        stdout: Command stdout for logging
        style: Command style for colored output
        context: Additional context from previous modules
    
    Returns:
        dict: Created data including workspace, admin_user, staff_users, customer_users,
        customers, addresses, segments, tags, email_config
    """
    if stdout:
        stdout.write(style.SUCCESS('Creating common module data...'))
    
    # Create users
    admin_user = create_admin_user(workspace, stdout, style)
    staff_users = create_staff_users(workspace, stdout, style)
    customer_users = create_customer_users(workspace, stdout, style)
    
    # Create staff roles and members
    create_staff_roles(workspace, stdout, style)
    create_staff_members(workspace, admin_user, staff_users, stdout, style)
    
    # Create customers
    customers = create_customers(workspace, customer_users, stdout, style)
    
    # Create addresses
    addresses = create_addresses(workspace, customers, stdout, style)
    
    # Create customer segments and tags
    segments = create_customer_segments(workspace, stdout, style)
    tags = create_customer_tags(workspace, customers, stdout, style)
    
    # Create default email config from local env (EMAIL_HOST, etc.)
    email_config = create_email_config(workspace, stdout, style)
    
    # Set workspace site name and description (default: XMart)
    create_workspace_settings(workspace, stdout, style)
    
    summary = [
        {'label': 'Users', 'count': User.objects.count()},
        {'label': 'Customers', 'count': Customer.objects.count()},
        {'label': 'Addresses', 'count': Address.objects.count()},
        {'label': 'Customer Segments', 'count': CustomerSegment.objects.count()},
        {'label': 'Customer Tags', 'count': CustomerTag.objects.count()},
        {'label': 'Email Configs', 'count': EmailConfig.objects.count()},
        {'label': 'Staff Roles', 'count': StaffRole.objects.count()},
        {'label': 'Staff Members', 'count': StaffMember.objects.count()},
    ]
    return {
        'workspace': workspace,
        'admin_user': admin_user,
        'staff_users': staff_users,
        'customer_users': customer_users,
        'customers': customers,
        'addresses': addresses,
        'segments': segments,
        'tags': tags,
        'email_config': email_config,
        'summary': summary,
    }


def create_admin_user(workspace, stdout=None, style=None):
    """Create admin user with password from environment variable and ensure it's workspace admin"""
    # Get admin password from environment variable, default to admin123
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
    
    user, created = User.objects.get_or_create(
        username='admin',
        defaults={
            'email': 'admin@xmart.com',
            'first_name': 'Admin',
            'last_name': 'User',
            'phone': '+1-555-0001',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
            'default_workspace': workspace,
        }
    )
    
    # Ensure admin user has correct properties even if already exists
    updated = False
    if not user.is_superuser:
        user.is_superuser = True
        updated = True
    if not user.is_staff:
        user.is_staff = True
        updated = True
    if not user.is_active:
        user.is_active = True
        updated = True
    if user.default_workspace != workspace:
        user.default_workspace = workspace
        updated = True
    
    # Always set password from environment variable
    user.set_password(admin_password)
    user.save()
    
    if created:
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Created admin user: {user.username}'))
    elif updated:
        if stdout:
            stdout.write(style.SUCCESS(f'✓ Updated admin user: {user.username}'))
    
    return user


def create_staff_users(workspace, stdout=None, style=None):
    """Create staff users"""
    staff_data = [
        {'username': 'warehouse_manager', 'first_name': 'John', 'last_name': 'Smith', 'email': 'john@xmart.com'},
        {'username': 'customer_service', 'first_name': 'Jane', 'last_name': 'Doe', 'email': 'jane@xmart.com'},
        {'username': 'logistics_coord', 'first_name': 'Bob', 'last_name': 'Wilson', 'email': 'bob@xmart.com'},
    ]
    users = []
    for data in staff_data:
        user, created = User.objects.get_or_create(
            username=data['username'],
            defaults={
                **data,
                'phone': '+1-555-0002',
                'is_staff': True,
                'is_active': True,
                'default_workspace': workspace,
            }
        )
        if created:
            user.set_password('staff123')
            user.save()
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created staff user: {user.username}'))
        users.append(user)
    return users


def create_customer_users(workspace, stdout=None, style=None):
    """Create customer users"""
    customer_data = [
        {'username': 'customer1', 'first_name': 'Alice', 'last_name': 'Johnson', 'email': 'alice@example.com'},
        {'username': 'customer2', 'first_name': 'Charlie', 'last_name': 'Brown', 'email': 'charlie@example.com'},
        {'username': 'customer3', 'first_name': 'Diana', 'last_name': 'Prince', 'email': 'diana@example.com'},
        {'username': 'customer4', 'first_name': 'Edward', 'last_name': 'Norton', 'email': 'edward@example.com'},
        {'username': 'customer5', 'first_name': 'Fiona', 'last_name': 'Apple', 'email': 'fiona@example.com'},
    ]
    users = []
    for data in customer_data:
        user, created = User.objects.get_or_create(
            username=data['username'],
            defaults={
                **data,
                'phone': '+1-555-1000',
                'is_active': True,
                'default_workspace': workspace,
            }
        )
        if created:
            user.set_password('customer123')
            user.save()
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created customer user: {user.username}'))
        users.append(user)
    return users


def create_staff_roles(workspace, stdout=None, style=None):
    """Create staff roles for workspace"""
    system_roles = [
        {
            'code': 'admin',
            'name': 'Administrator',
            'description': 'Full access to all features',
            'permissions': {'*': ['*']},
            'is_system': True,
        },
        {
            'code': 'manager',
            'name': 'Manager',
            'description': 'Can manage most features',
            'permissions': {
                'shop': ['*'],
                'delivery': ['*'],
                'web': ['*'],
            },
            'is_system': True,
        },
        {
            'code': 'staff',
            'name': 'Staff',
            'description': 'Basic staff access',
            'permissions': {
                'shop': ['view', 'list'],
                'delivery': ['view', 'list'],
            },
            'is_system': True,
        },
    ]
    
    roles = []
    for role_data in system_roles:
        role, created = StaffRole.objects.get_or_create(
            workspace=workspace,
            code=role_data['code'],
            defaults={
                'name': role_data['name'],
                'description': role_data['description'],
                'permissions': role_data['permissions'],
                'is_system': role_data['is_system'],
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created staff role: {role.name}'))
        roles.append(role)
    return roles


def create_staff_members(workspace, admin_user, staff_users, stdout=None, style=None):
    """Create staff member records"""
    admin_role = StaffRole.objects.get(workspace=workspace, code='admin')
    staff_role = StaffRole.objects.get(workspace=workspace, code='staff')
    
    # Create or update admin staff member - ensure admin user is workspace admin
    admin_staff, created = StaffMember.objects.get_or_create(
        workspace=workspace,
        user=admin_user,
        defaults={
            'role': admin_role,
            'is_active': True,
        }
    )
    
    # Ensure admin user has admin role even if staff member already exists
    if not created:
        if admin_staff.role != admin_role:
            admin_staff.role = admin_role
            admin_staff.is_active = True
            admin_staff.save()
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Updated staff member: {admin_user.username} (admin)'))
        elif stdout:
            stdout.write(style.SUCCESS(f'↻ Staff member already exists: {admin_user.username} (admin)'))
    elif stdout:
        stdout.write(style.SUCCESS(f'✓ Created staff member: {admin_user.username} (admin)'))
    
    # Create staff members for other staff users
    for user in staff_users:
        staff_member, created = StaffMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                'role': staff_role,
                'is_active': True,
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created staff member: {user.username} (staff)'))


def create_customers(workspace, customer_users, stdout=None, style=None):
    """Create customer profiles"""
    customers = []
    for i, user in enumerate(customer_users, 1):
        customer, created = Customer.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                'customer_number': f'CUST-{i:04d}',
                'company_name': f'{user.get_full_name()} Company',
                'credit_limit': Decimal('10000.00'),
                'balance': Decimal('0.00'),
                'is_active': True,
                'is_verified': True,
                'verified_at': timezone.now(),
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created customer: {customer.customer_number}'))
        customers.append(customer)
    return customers


def create_addresses(workspace, customers, stdout=None, style=None):
    """Create addresses for customers"""
    from django.contrib.contenttypes.models import ContentType
    from django.db import IntegrityError
    
    addresses = []
    address_templates = [
        # New Zealand
        {'address_line1': '100 Queen St', 'city': 'Auckland', 'state': 'Auckland', 'postal_code': '1010', 'country': 'NZ'},
        # China
        {'address_line1': '200 Nanjing Rd', 'city': 'Shanghai', 'state': 'Shanghai', 'postal_code': '200000', 'country': 'CN'},
        # United States
        {'address_line1': '300 Pine St', 'city': 'San Francisco', 'state': 'CA', 'postal_code': '94104', 'country': 'US'},
        # South Korea
        {'address_line1': '400 Gangnam-daero', 'city': 'Seoul', 'state': 'Seoul', 'postal_code': '06040', 'country': 'KR'},
    ]
    
    for customer, template in zip(customers, address_templates):
        content_type = ContentType.objects.get_for_model(customer)
        shipping_addr = Address.objects.filter(
            workspace=workspace,
            content_type=content_type,
            object_id=customer.id,
            address_line1=template['address_line1'],
            city=template['city'],
            postal_code=template['postal_code'],
        ).first()
        
        if not shipping_addr:
            try:
                shipping_addr = Address.objects.create(
                    workspace=workspace,
                    content_type=content_type,
                    object_id=customer.id,
                    full_name=customer.user.get_full_name(),
                    phone=customer.user.phone or '+1-555-0000',
                    email=customer.user.email,
                    **template
                )
                addresses.append(shipping_addr)
            except IntegrityError:
                shipping_addr = Address.objects.filter(
                    workspace=workspace,
                    content_type=content_type,
                    object_id=customer.id,
                ).first()
        
        # Billing address
        billing_addr = Address.objects.filter(
            workspace=workspace,
            content_type=content_type,
            object_id=customer.id,
            address_line1=f"{template['address_line1']} (Billing)",
        ).first()
        
        if not billing_addr:
            try:
                billing_addr = Address.objects.create(
                    workspace=workspace,
                    content_type=content_type,
                    object_id=customer.id,
                    full_name=customer.user.get_full_name(),
                    phone=customer.user.phone or '+1-555-0000',
                    email=customer.user.email,
                    address_line1=f"{template['address_line1']} (Billing)",
                    city=template['city'],
                    state=template['state'],
                    postal_code=template['postal_code'],
                    country=template['country'],
                )
                addresses.append(billing_addr)
            except IntegrityError:
                pass
    
    if stdout:
        stdout.write(style.SUCCESS(f'✓ Created {len(addresses)} addresses'))
    return addresses


def create_email_config(workspace, stdout=None, style=None):
    """Create default EmailConfig for workspace from env (EMAIL_HOST, EMAIL_PORT, etc.)."""
    config = get_smtp_config_from_env()
    name = os.environ.get('EMAIL_CONFIG_NAME', 'Default SMTP')
    obj, created = EmailConfig.objects.get_or_create(
        workspace=workspace,
        name=name,
        backend_type='smtp',
        defaults={
            'config': config,
            'is_active': True,
            'is_default': True,
        },
    )
    if created and stdout:
        stdout.write(style.SUCCESS(f'✓ Created email config: {obj.name}'))
    return obj


def create_workspace_settings(workspace, stdout=None, style=None):
    """Create or update Settings for workspace with default site name and description (XMart)."""
    settings_obj, created = Settings.objects.get_or_create(
        workspace=workspace,
        defaults={
            'site_name': 'XMart',
            'site_description': 'XMart demo website',
            'default_language': 'en',
            'default_currency': 'NZD',
        }
    )
    if not created:
        if settings_obj.site_name != 'XMart' or settings_obj.site_description != 'XMart demo website':
            settings_obj.site_name = 'XMart'
            settings_obj.site_description = 'XMart demo website'
            settings_obj.save(update_fields=['site_name', 'site_description'])
    if created and stdout:
        stdout.write(style.SUCCESS('✓ Created workspace settings (site name: XMart)'))
    return settings_obj


def create_customer_segments(workspace, stdout=None, style=None):
    """Create customer segments"""
    segments_data = [
        {
            'name': 'VIP Customers',
            'query': {'balance': {'gte': 5000}},
            'is_active': True,
        },
        {
            'name': 'New Customers',
            'query': {'created_days_ago': {'lte': 30}},
            'is_active': True,
        },
    ]
    segments = []
    for data in segments_data:
        segment, created = CustomerSegment.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
            defaults={
                'query': data['query'],
                'is_active': data['is_active'],
            }
        )
        if created and stdout:
            stdout.write(style.SUCCESS(f'✓ Created customer segment: {segment.name}'))
        segments.append(segment)
    return segments


def create_customer_tags(workspace, customers, stdout=None, style=None):
    """Create customer tags"""
    tags_data = [
        {'name': 'Premium'},
        {'name': 'Wholesale'},
        {'name': 'Reseller'},
    ]
    tags = []
    for data in tags_data:
        tag, created = CustomerTag.objects.get_or_create(
            workspace=workspace,
            name=data['name'],
        )
        if created:
            # Tag first 2 customers with first tag
            if customers and data['name'] == 'Premium':
                tag.customers.add(*customers[:2])
            if stdout:
                stdout.write(style.SUCCESS(f'✓ Created customer tag: {tag.name}'))
        tags.append(tag)
    return tags


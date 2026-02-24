# -*- coding: utf-8 -*-
"""
BFG Shop Module Signal Handlers
Initialize shop-related data structures when workspace is created
"""

from typing import Any, Dict
from bfg.core.events import global_dispatcher

import logging
logger = logging.getLogger(__name__)


def on_workspace_created(event_data: Dict[str, Any]):
    """
    Initialize shop and customer service roles when workspace is created.
    Listens to 'workspace.created' event from WorkspaceService.
    """
    workspace = event_data.get('data', {}).get('workspace')
    if not workspace:
        return
    
    try:
        from bfg.common.utils import create_staff_roles
        
        logger.info(f"Initializing shop roles for workspace: {workspace.name}")
        
        shop_roles = [
            {
                'code': 'store_admin',
                'name': 'Store Administrator',
                'description': 'Manage store settings, products, and orders',
                'permissions': {
                    'shop.store': ['read', 'update'],
                    'shop.product': ['create', 'read', 'update', 'delete'],
                    'shop.category': ['create', 'read', 'update', 'delete'],
                    'shop.order': ['read', 'update'],
                    'delivery.consignment': ['create', 'read', 'update'],
                },
                'is_system': True,
            },
            {
                'code': 'warehouse_manager',
                'name': 'Warehouse Manager',
                'description': 'Manage inventory and shipments',
                'permissions': {
                    'delivery.warehouse': ['read', 'update'],
                    'delivery.manifest': ['create', 'read', 'update'],
                    'delivery.consignment': ['create', 'read', 'update'],
                    'shop.inventory': ['read', 'update'],
                },
                'is_system': True,
            },
            {
                'code': 'customer_service',
                'name': 'Customer Service',
                'description': 'Handle customer inquiries and support',
                'permissions': {
                    'shop.order': ['read'],
                    'support.ticket': ['create', 'read', 'update'],
                    'common.customer': ['read'],
                },
                'is_system': True,
            },
        ]
        
        created_count = create_staff_roles(workspace, shop_roles)
        logger.info(f"Created {created_count} shop role(s) for {workspace.name}")
        
    except Exception as e:
        logger.error(f"Failed to initialize shop roles for workspace {workspace.id}: {e}", exc_info=True)


# Register event listener
global_dispatcher.listen('workspace.created', on_workspace_created)

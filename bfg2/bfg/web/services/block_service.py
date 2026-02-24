"""
BFG Web Module Services

Block validation and data resolution service for Page Builder
"""

from typing import Any, Dict, List, Optional
from django.db.models import QuerySet
from bfg.core.services import BaseService
from bfg.web.models import Post, Category


# Block type schemas for validation
BLOCK_SCHEMAS = {
    'hero_carousel_v1': {
        'settings': {
            'autoPlay': {'type': 'boolean', 'default': True},
            'interval': {'type': 'integer', 'default': 5000},
            'showArrows': {'type': 'boolean', 'default': True},
            'showDots': {'type': 'boolean', 'default': True},
        },
        'data': {
            'slides': {'type': 'array', 'required': True},
        }
    },
    'hero_video_v1': {
        'settings': {
            'autoPlay': {'type': 'boolean', 'default': True},
            'muted': {'type': 'boolean', 'default': True},
            'loop': {'type': 'boolean', 'default': True},
        },
        'data': {
            'videoUrl': {'type': 'string', 'required': True},
            'title': {'type': 'object'},
            'subtitle': {'type': 'object'},
        }
    },
    'category_grid_v1': {
        'settings': {
            'columns': {'type': 'integer', 'default': 4},
            'showDescription': {'type': 'boolean', 'default': False},
        },
        'data': {
            'source': {'type': 'string', 'default': 'all'},  # 'all' | 'selected'
            'categoryIds': {'type': 'array'},
            'contentType': {'type': 'string'},  # Optional filter
        }
    },
    'banner_grid_v1': {
        'settings': {
            'layout': {'type': 'string', 'default': '2x2'},  # '2x2' | '1+2' | '3x1'
        },
        'data': {
            'banners': {'type': 'array', 'required': True},
        }
    },
    'post_list_v1': {
        'settings': {
            'layout': {'type': 'string', 'default': 'grid'},  # 'grid' | 'list'
            'columns': {'type': 'integer', 'default': 3},
            'showExcerpt': {'type': 'boolean', 'default': True},
            'showImage': {'type': 'boolean', 'default': True},
        },
        'data': {
            'source': {'type': 'string', 'default': 'latest'},  # 'latest' | 'category' | 'manual'
            'contentType': {'type': 'string'},  # Content type filter (case/project/post/faq)
            'categorySlug': {'type': 'string'},
            'postIds': {'type': 'array'},
            'limit': {'type': 'integer', 'default': 6},
            'orderBy': {'type': 'string', 'default': '-published_at'},
        }
    },
    'case_list_v1': {
        'settings': {
            'layout': {'type': 'string', 'default': 'card'},
            'columns': {'type': 'integer', 'default': 3},
        },
        'data': {
            'source': {'type': 'string', 'default': 'latest'},
            'contentType': {'type': 'string', 'default': 'case'},
            'categorySlug': {'type': 'string'},
            'postIds': {'type': 'array'},
            'limit': {'type': 'integer', 'default': 6},
            'orderBy': {'type': 'string', 'default': '-published_at'},
        }
    },
    'project_grid_v1': {
        'settings': {
            'columns': {'type': 'integer', 'default': 3},
            'showTechStack': {'type': 'boolean', 'default': True},
        },
        'data': {
            'source': {'type': 'string', 'default': 'latest'},
            'contentType': {'type': 'string', 'default': 'project'},
            'categorySlug': {'type': 'string'},
            'postIds': {'type': 'array'},
            'limit': {'type': 'integer', 'default': 6},
            'orderBy': {'type': 'string', 'default': '-published_at'},
        }
    },
    'faq_list_v1': {
        'settings': {
            'expandFirst': {'type': 'boolean', 'default': True},
        },
        'data': {
            'source': {'type': 'string', 'default': 'latest'},
            'contentType': {'type': 'string', 'default': 'faq'},
            'categorySlug': {'type': 'string'},
            'postIds': {'type': 'array'},
            'limit': {'type': 'integer', 'default': 10},
        }
    },
    'text_block_v1': {
        'settings': {
            'align': {'type': 'string', 'default': 'left'},
            'maxWidth': {'type': 'string', 'default': '800px'},
        },
        'data': {
            'content': {'type': 'object', 'required': True},  # Multilingual: {en: "...", zh: "..."}
        }
    },
    'cta_block_v1': {
        'settings': {
            'variant': {'type': 'string', 'default': 'primary'},  # 'primary' | 'outline'
            'size': {'type': 'string', 'default': 'medium'},
        },
        'data': {
            'title': {'type': 'object'},
            'description': {'type': 'object'},
            'buttonText': {'type': 'object'},
            'buttonLink': {'type': 'string'},
            'secondaryButtonText': {'type': 'object'},
            'secondaryButtonLink': {'type': 'string'},
            'backgroundImage': {'type': 'string'},
        }
    },
    'contact_form_v1': {
        'settings': {
            'inquiryType': {'type': 'string', 'default': 'inquiry'},
            'showPhone': {'type': 'boolean', 'default': True},
        },
        'data': {
            'title': {'type': 'object'},
            'description': {'type': 'object'},
            'customFields': {'type': 'array'},  # Additional form fields
        }
    },
    'section_v1': {
        'settings': {},
        'data': {
            'width': {'type': 'string', 'default': 'container'},  # 'container' | 'full'
            'children': {'type': 'array'},  # nested BlockConfig[]
        }
    },
}

# Block types that require dynamic data resolution
DYNAMIC_BLOCK_TYPES = {
    'post_list_v1',
    'case_list_v1',
    'project_grid_v1',
    'faq_list_v1',
    'category_grid_v1',
}


class BlockService(BaseService):
    """
    Block management service
    
    Handles block validation and dynamic data resolution for Page Builder
    """
    
    def validate_block(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a single block against its schema
        
        Args:
            block: Block configuration dict
            
        Returns:
            Dict with 'valid' bool and 'errors' list
        """
        errors = []
        
        block_type = block.get('type')
        if not block_type:
            errors.append("Block type is required")
            return {'valid': False, 'errors': errors}
        
        if block_type not in BLOCK_SCHEMAS:
            # Unknown block type - allow but warn
            return {'valid': True, 'errors': [], 'warnings': [f"Unknown block type: {block_type}"]}
        
        schema = BLOCK_SCHEMAS[block_type]
        
        # Validate required data fields
        data = block.get('data', {})
        for field, field_schema in schema.get('data', {}).items():
            if field_schema.get('required') and field not in data:
                errors.append(f"Required field '{field}' is missing in data")
        
        return {'valid': len(errors) == 0, 'errors': errors}
    
    def validate_blocks(self, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate all blocks in a page
        
        Args:
            blocks: List of block configurations
            
        Returns:
            Dict with 'valid' bool and 'errors' dict keyed by block id
        """
        all_valid = True
        block_errors = {}
        
        for block in blocks:
            block_id = block.get('id', 'unknown')
            result = self.validate_block(block)
            if not result['valid']:
                all_valid = False
                block_errors[block_id] = result['errors']
        
        return {'valid': all_valid, 'errors': block_errors}
    
    def resolve_block_data(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve dynamic data for a block
        
        Args:
            block: Block configuration dict
            
        Returns:
            Block with resolved data added
        """
        block_type = block.get('type', '')

        if block_type == 'section_v1':
            data = block.get('data') or {}
            children = data.get('children') or []
            block = dict(block)
            block['data'] = dict(data)
            block['data']['children'] = self.resolve_all_blocks(children)
            return block

        if block_type in DYNAMIC_BLOCK_TYPES:
            if block_type == 'category_grid_v1':
                return self._resolve_category_grid(block)
            else:
                # All post-based blocks use the same resolver
                return self._resolve_post_list(block)
        
        return block
    
    def resolve_all_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Resolve dynamic data for all blocks in a page
        
        Args:
            blocks: List of block configurations
            
        Returns:
            List of blocks with resolved data
        """
        resolved = []
        for block in blocks:
            resolved.append(self.resolve_block_data(block))
        return resolved
    
    def _resolve_post_list(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generic resolver for post-based blocks (case_list, project_grid, post_list, faq_list)
        """
        from bfg.web.serializers import PostListSerializer
        
        data = block.get('data', {})
        source = data.get('source', 'latest')
        
        queryset = Post.objects.filter(
            workspace=self.workspace,
            status='published'
        ).select_related('category', 'author')
        
        # Filter by content type if specified (not hardcoded - from config)
        content_type = data.get('contentType')
        if content_type:
            queryset = queryset.filter(category__content_type_name=content_type)
        
        # Filter by data source
        if source == 'category':
            category_slug = data.get('categorySlug')
            if category_slug:
                queryset = queryset.filter(category__slug=category_slug)
        elif source == 'manual':
            post_ids = data.get('postIds', [])
            if post_ids:
                queryset = queryset.filter(id__in=post_ids)
        
        # Order and limit
        order_by = data.get('orderBy', '-published_at')
        limit = data.get('limit', 6)
        queryset = queryset.order_by(order_by)[:limit]
        
        # Add resolved data to block
        block['resolvedData'] = PostListSerializer(queryset, many=True).data
        return block
    
    def _resolve_category_grid(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolver for category grid blocks
        """
        from bfg.web.serializers import CategorySerializer
        
        data = block.get('data', {})
        source = data.get('source', 'all')
        
        queryset = Category.objects.filter(
            workspace=self.workspace,
            is_active=True
        )
        
        # Filter by content type if specified
        content_type = data.get('contentType')
        if content_type:
            queryset = queryset.filter(content_type_name=content_type)
        
        # Filter by selected IDs if manual selection
        if source == 'selected':
            category_ids = data.get('categoryIds', [])
            if category_ids:
                queryset = queryset.filter(id__in=category_ids)
        
        queryset = queryset.order_by('order', 'name')
        
        block['resolvedData'] = CategorySerializer(queryset, many=True).data
        return block
    
    def get_available_block_types(self) -> List[Dict[str, Any]]:
        """
        Get list of available block types with their schemas
        
        Returns:
            List of block type definitions
        """
        block_types = []
        for block_type, schema in BLOCK_SCHEMAS.items():
            block_types.append({
                'type': block_type,
                'settings_schema': schema.get('settings', {}),
                'data_schema': schema.get('data', {}),
            })
        return block_types

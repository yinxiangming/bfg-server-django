"""
BFG Web Module

Category schema templates for quick creation of common content types
"""

from django.utils.translation import gettext_lazy as _


CATEGORY_SCHEMA_TEMPLATES = {
    'case': {
        'name': 'Industry Case',
        'name_zh': '行业案例',
        'content_type_name': 'case',
        'icon': 'briefcase',
        'description': 'Showcase customer success stories and case studies',
        'description_zh': '展示客户成功案例和行业案例',
        'fields_schema': {
            'client_name': {
                'type': 'string',
                'required': True,
                'label': 'Client Name',
                'label_zh': '客户名称',
                'description': 'Name of the client or company'
            },
            'industry': {
                'type': 'select',
                'required': True,
                'label': 'Industry',
                'label_zh': '所属行业',
                'options': [
                    {'label': '制造业', 'label_en': 'Manufacturing', 'value': 'manufacturing'},
                    {'label': '零售业', 'label_en': 'Retail', 'value': 'retail'},
                    {'label': '金融业', 'label_en': 'Finance', 'value': 'finance'},
                    {'label': '医疗健康', 'label_en': 'Healthcare', 'value': 'healthcare'},
                    {'label': '教育', 'label_en': 'Education', 'value': 'education'},
                    {'label': '科技', 'label_en': 'Technology', 'value': 'technology'},
                    {'label': '物流', 'label_en': 'Logistics', 'value': 'logistics'},
                    {'label': '其他', 'label_en': 'Other', 'value': 'other'},
                ]
            },
            'project_duration': {
                'type': 'string',
                'label': 'Project Duration',
                'label_zh': '项目周期',
                'description': 'How long the project lasted'
            },
            'achievements': {
                'type': 'text',
                'label': 'Key Achievements',
                'label_zh': '成效数据',
                'description': 'Key results and achievements'
            },
            'client_logo': {
                'type': 'image',
                'label': 'Client Logo',
                'label_zh': '客户Logo',
            },
        }
    },
    'project': {
        'name': 'Project',
        'name_zh': '项目',
        'content_type_name': 'project',
        'icon': 'folder',
        'description': 'Technical projects and portfolio items',
        'description_zh': '技术项目和作品集',
        'fields_schema': {
            'tech_stack': {
                'type': 'string',
                'label': 'Technology Stack',
                'label_zh': '技术栈',
                'description': 'Technologies used in the project'
            },
            'team_size': {
                'type': 'integer',
                'label': 'Team Size',
                'label_zh': '团队规模',
            },
            'project_status': {
                'type': 'select',
                'label': 'Project Status',
                'label_zh': '项目状态',
                'options': [
                    {'label': '进行中', 'label_en': 'Ongoing', 'value': 'ongoing'},
                    {'label': '已完成', 'label_en': 'Completed', 'value': 'completed'},
                    {'label': '已暂停', 'label_en': 'Paused', 'value': 'paused'},
                ]
            },
            'demo_url': {
                'type': 'string',
                'label': 'Demo URL',
                'label_zh': '演示链接',
            },
            'github_url': {
                'type': 'string',
                'label': 'GitHub URL',
                'label_zh': 'GitHub 链接',
            },
        }
    },
    'service': {
        'name': 'Service',
        'name_zh': '服务',
        'content_type_name': 'service',
        'icon': 'tool',
        'description': 'Services offered to customers',
        'description_zh': '提供给客户的服务',
        'fields_schema': {
            'price_range': {
                'type': 'string',
                'label': 'Price Range',
                'label_zh': '价格区间',
            },
            'duration': {
                'type': 'string',
                'label': 'Service Duration',
                'label_zh': '服务时长',
            },
            'is_popular': {
                'type': 'boolean',
                'default': False,
                'label': 'Featured Service',
                'label_zh': '热门服务',
            },
            'booking_enabled': {
                'type': 'boolean',
                'default': True,
                'label': 'Booking Enabled',
                'label_zh': '开启预约',
            },
        }
    },
    'faq': {
        'name': 'FAQ',
        'name_zh': '常见问题',
        'content_type_name': 'faq',
        'icon': 'help-circle',
        'description': 'Frequently asked questions',
        'description_zh': '常见问题解答',
        'fields_schema': {}  # FAQ uses title as question, content as answer
    },
    'news': {
        'name': 'News',
        'name_zh': '新闻动态',
        'content_type_name': 'news',
        'icon': 'newspaper',
        'description': 'Company news and updates',
        'description_zh': '公司新闻和动态',
        'fields_schema': {
            'source': {
                'type': 'string',
                'label': 'News Source',
                'label_zh': '来源',
            },
            'external_url': {
                'type': 'string',
                'label': 'External URL',
                'label_zh': '外部链接',
            },
        }
    },
    'team': {
        'name': 'Team Member',
        'name_zh': '团队成员',
        'content_type_name': 'team',
        'icon': 'users',
        'description': 'Team member profiles',
        'description_zh': '团队成员介绍',
        'fields_schema': {
            'position': {
                'type': 'string',
                'required': True,
                'label': 'Position',
                'label_zh': '职位',
            },
            'email': {
                'type': 'string',
                'label': 'Email',
                'label_zh': '邮箱',
            },
            'linkedin': {
                'type': 'string',
                'label': 'LinkedIn',
                'label_zh': 'LinkedIn 链接',
            },
            'order': {
                'type': 'integer',
                'default': 100,
                'label': 'Display Order',
                'label_zh': '显示顺序',
            },
        }
    },
    'testimonial': {
        'name': 'Testimonial',
        'name_zh': '客户评价',
        'content_type_name': 'testimonial',
        'icon': 'message-square',
        'description': 'Customer testimonials and reviews',
        'description_zh': '客户评价和推荐',
        'fields_schema': {
            'author_name': {
                'type': 'string',
                'required': True,
                'label': 'Author Name',
                'label_zh': '评价人',
            },
            'author_title': {
                'type': 'string',
                'label': 'Author Title',
                'label_zh': '职位/头衔',
            },
            'company': {
                'type': 'string',
                'label': 'Company',
                'label_zh': '公司',
            },
            'rating': {
                'type': 'integer',
                'label': 'Rating (1-5)',
                'label_zh': '评分 (1-5)',
            },
            'avatar': {
                'type': 'image',
                'label': 'Avatar',
                'label_zh': '头像',
            },
        }
    },
}


def get_template(template_key: str) -> dict:
    """
    Get a category template by key
    
    Args:
        template_key: Template key (case, project, service, etc.)
        
    Returns:
        Template dict or None
    """
    return CATEGORY_SCHEMA_TEMPLATES.get(template_key)


def get_all_templates() -> list:
    """
    Get all available templates as a list
    
    Returns:
        List of template summaries
    """
    templates = []
    for key, template in CATEGORY_SCHEMA_TEMPLATES.items():
        templates.append({
            'key': key,
            'name': template['name'],
            'name_zh': template.get('name_zh', ''),
            'content_type_name': template['content_type_name'],
            'icon': template.get('icon', ''),
            'description': template.get('description', ''),
            'description_zh': template.get('description_zh', ''),
            'fields_count': len(template.get('fields_schema', {})),
        })
    return templates

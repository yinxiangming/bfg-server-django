"""
Product category smart collection rule schema.
"""

import json
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from bfg.core.schema_convert import pydantic_model_to_form_schema


class CategoryRuleModel(BaseModel):
    """Single rule entry for ProductCategory.rules."""

    column: str = Field(
        description='Product attribute or price/weight column',
        json_schema_extra={'placeholder': 'price'},
    )
    relation: str = Field(
        description='Comparison operator (e.g. greater_than, equals)',
        json_schema_extra={'placeholder': 'greater_than'},
    )
    condition: str = Field(
        description='Comparison value (string stored)',
        json_schema_extra={'placeholder': '100'},
    )


class ProductCategoryRulesModel(BaseModel):
    """Wrapper used for validation."""

    model_config = ConfigDict(extra='allow')

    rules: List[CategoryRuleModel] = Field(
        default_factory=list,
        description='List of smart collection rules',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 4,
            'placeholder': '[{"column":"price","relation":"greater_than","condition":"100"}]',
        },
    )


class CategoryRulesFormModel(BaseModel):
    """Form schema representation that treats rules as a JSON textarea."""

    rules: str = Field(
        default='[]',
        description='JSON array for ProductCategory.rules',
        json_schema_extra={
            'form_type': 'textarea',
            'rows': 4,
            'placeholder': '[{"column":"price","relation":"greater_than","condition":"100"}]',
        },
    )


def prepare_category_rules_value(value):
    """Convert textarea JSON string to Python list."""
    if value is None or value == '':
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        raw = value.strip() or '[]'
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"rules: invalid JSON ({exc})") from exc
        if not isinstance(parsed, list):
            raise ValueError('rules: must be a JSON array')
        return parsed
    raise ValueError('rules: must be a list or JSON string')


_CATEGORY_RULES_FORM_SCHEMA = pydantic_model_to_form_schema(
    CategoryRulesFormModel,
    title='Product Category Rules',
)


def get_category_rules_form_schema():
    """Return cached SchemaForm definition for ProductCategory rules."""
    return _CATEGORY_RULES_FORM_SCHEMA


def apply_rules_to_product_queryset(queryset, rules, rule_match_type='all'):
    """
    Apply CategoryRuleModel-style rules to a Product queryset (shared logic for
    ProductCategory and CampaignDisplay). Returns filtered queryset.
    """
    if not rules:
        return queryset
    from decimal import Decimal
    from django.db.models import Q

    q_list = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        col = (r.get('column') or '').strip()
        rel = (r.get('relation') or 'equals').strip()
        cond = (r.get('condition') or '').strip()
        if not col:
            continue
        try:
            if col == 'id':
                if rel == 'equals':
                    val = int(cond)
                    q_list.append(Q(pk=val))
                elif rel in ('in', 'in_list'):
                    vals = [int(x.strip()) for x in cond.split(',') if x.strip()]
                    if vals:
                        q_list.append(Q(pk__in=vals))
            elif col == 'category_id':
                if rel == 'equals':
                    val = int(cond)
                    q_list.append(Q(categories__id=val))
                elif rel in ('in', 'in_list'):
                    vals = [int(x.strip()) for x in cond.split(',') if x.strip()]
                    if vals:
                        q_list.append(Q(categories__id__in=vals))
            elif col == 'price':
                val = Decimal(cond)
                if rel in ('greater_than', 'gt'):
                    q_list.append(Q(price__gt=val))
                elif rel in ('greater_than_or_equal', 'gte'):
                    q_list.append(Q(price__gte=val))
                elif rel in ('less_than', 'lt'):
                    q_list.append(Q(price__lt=val))
                elif rel in ('less_than_or_equal', 'lte'):
                    q_list.append(Q(price__lte=val))
                elif rel == 'equals':
                    q_list.append(Q(price=val))
        except (ValueError, TypeError, Exception):
            continue
    if not q_list:
        return queryset
    if rule_match_type == 'any':
        combined = q_list[0]
        for q in q_list[1:]:
            combined = combined | q
        return queryset.filter(combined).distinct()
    return queryset.filter(*q_list).distinct()

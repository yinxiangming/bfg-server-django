# -*- coding: utf-8 -*-
"""
Condition Engine for BFG
Provides extensible condition evaluation with AND/OR logic and pluggable field providers.
"""

from typing import Any, Dict, List, Optional
from decimal import Decimal


class FieldProvider:
    """
    Base class for field providers.
    Business modules extend this to register their own condition fields.
    """
    
    def get_available_fields(self) -> Dict[str, str]:
        """
        Return available fields provided by this provider.
        
        Returns:
            dict: {field_name: description}
        
        Example:
            {
                'is_new': 'Whether customer is new (registered < 30 days)',
                'tier': 'Customer tier (standard/silver/gold/vip)',
            }
        """
        raise NotImplementedError("Subclasses must implement get_available_fields()")
    
    def get_field_value(self, field_name: str, context: Dict[str, Any]) -> Any:
        """
        Get field value from context.
        
        Args:
            field_name: Field name (without prefix)
            context: Full evaluation context
        
        Returns:
            Field value
        
        Example:
            # For CustomerFieldProvider with prefix 'customer'
            # field_name = 'is_new'
            # Returns: True/False based on customer.created_at
        """
        raise NotImplementedError("Subclasses must implement get_field_value()")


class ConditionEngine:
    """
    Condition evaluation engine.
    Supports AND/OR logic, nested conditions, and extensible fields via FieldProvider.
    """
    
    def __init__(self):
        self._field_providers: Dict[str, FieldProvider] = {}
    
    def register_provider(self, prefix: str, provider: FieldProvider):
        """
        Register a field provider.
        
        Args:
            prefix: Field prefix (e.g., 'customer', 'freight', 'product')
            provider: FieldProvider instance
        
        Example:
            engine.register_provider('customer', CustomerFieldProvider())
            # Now supports fields: customer.is_new, customer.tier, etc.
        """
        if not isinstance(provider, FieldProvider):
            raise TypeError(f"Provider must be instance of FieldProvider, got {type(provider)}")
        
        self._field_providers[prefix] = provider
    
    def evaluate(self, condition_config: Optional[Dict], context: Dict[str, Any]) -> bool:
        """
        Evaluate condition configuration.
        
        Args:
            condition_config: Condition configuration dict or None
                {
                    "operator": "AND",  # or "OR"
                    "rules": [
                        {"field": "customer.is_new", "operator": "==", "value": True},
                        {"field": "freight.volume", "operator": ">=", "value": 5.0}
                    ]
                }
            context: Evaluation context containing all necessary data
        
        Returns:
            bool: Whether condition is satisfied
        """
        if condition_config is None:
            return True  # No condition always matches
        
        operator = condition_config.get('operator', 'AND')
        rules = condition_config.get('rules', [])
        
        if not rules:
            return True  # Empty rules always match
        
        if operator == 'AND':
            return all(self._evaluate_rule(rule, context) for rule in rules)
        elif operator == 'OR':
            return any(self._evaluate_rule(rule, context) for rule in rules)
        else:
            raise ValueError(f"Unknown operator: {operator}. Must be 'AND' or 'OR'")
    
    def _evaluate_rule(self, rule: Dict, context: Dict[str, Any]) -> bool:
        """
        Evaluate a single rule.
        Supports nested conditions.
        """
        # Nested condition (has 'operator' key)
        if 'operator' in rule:
            return self.evaluate(rule, context)
        
        # Leaf condition
        field = rule.get('field')
        op = rule.get('operator')
        expected_value = rule.get('value')
        
        if not field or not op:
            raise ValueError(f"Rule must have 'field' and 'operator': {rule}")
        
        # Get actual value from context
        actual_value = self._get_field_value(field, context)
        
        # Perform comparison
        return self._compare(actual_value, op, expected_value)
    
    def _get_field_value(self, field_path: str, context: Dict[str, Any]) -> Any:
        """
        Get field value from context, supporting field providers.
        
        Args:
            field_path: Field path like 'customer.is_new' or 'volume'
            context: Context dict
        
        Returns:
            Field value
        """
        # Check if field has prefix (e.g., customer.is_new)
        if '.' in field_path:
            prefix, field_name = field_path.split('.', 1)
            
            # Find corresponding field provider
            provider = self._field_providers.get(prefix)
            if provider:
                return provider.get_field_value(field_name, context)
            
            # No provider, try nested dict access
            parts = field_path.split('.')
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return None
            return value
        
        # Direct access from context top level
        return context.get(field_path)
    
    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        """
        Perform comparison operation.
        
        Args:
            actual: Actual value from context
            operator: Comparison operator
            expected: Expected value from condition
        
        Returns:
            bool: Comparison result
        """
        if actual is None:
            return False
        
        # Type conversion: ensure Decimal comparison works correctly
        if isinstance(expected, (int, float)) and isinstance(actual, Decimal):
            expected = Decimal(str(expected))
        elif isinstance(actual, (int, float)) and isinstance(expected, Decimal):
            actual = Decimal(str(actual))
        
        # Perform comparison
        if operator == '==':
            return actual == expected
        elif operator == '!=':
            return actual != expected
        elif operator == '>':
            return actual > expected
        elif operator == '>=':
            return actual >= expected
        elif operator == '<':
            return actual < expected
        elif operator == '<=':
            return actual <= expected
        elif operator == 'in':
            return actual in expected
        elif operator == 'not_in':
            return actual not in expected
        elif operator == 'contains':
            return expected in actual
        else:
            raise ValueError(f"Unknown operator: {operator}")
    
    def get_all_available_fields(self) -> Dict[str, Dict[str, str]]:
        """
        Get all registered available fields.
        Useful for documentation and UI generation.
        
        Returns:
            dict: {prefix: {field_name: description}}
        
        Example:
            {
                'customer': {
                    'is_new': 'Whether customer is new',
                    'tier': 'Customer tier'
                },
                'freight': {
                    'volume': 'Freight volume (m³)',
                    'weight': 'Freight weight (kg)'
                }
            }
        """
        result = {}
        for prefix, provider in self._field_providers.items():
            result[prefix] = provider.get_available_fields()
        return result


# Global singleton instance
_condition_engine: Optional[ConditionEngine] = None


def get_condition_engine() -> ConditionEngine:
    """
    Get global condition engine instance.
    
    Returns:
        ConditionEngine: Global singleton
    """
    global _condition_engine
    if _condition_engine is None:
        _condition_engine = ConditionEngine()
    return _condition_engine

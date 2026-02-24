"""
Generic conversion from Pydantic BaseModel to client-facing schema formats.

- ConfigSchema: Record<fieldName, { type, required?, description?, sensitive?, default? }>
  Used by client SchemaConfigEditor (e.g. carrier/gateway config).
- FormSchema: { title, fields: [ { field, label, type, required?, helperText?, defaultValue? }, ... ] }
  Used by client SchemaForm.
"""

import json
from typing import Any, Dict, List, Type, get_args, get_origin

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError


def _is_json_serializable(value: Any) -> bool:
    """Return True if value is JSON-serializable (avoids PydanticUndefined etc.)."""
    if value is None:
        return True
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


# Pydantic annotation -> client ConfigSchema type (SchemaConfigEditor supports string|number|integer|boolean)
_TYPE_MAP = {
    str: 'string',
    int: 'integer',
    float: 'number',
    bool: 'boolean',
}


def _resolve_annotation(annotation: Any) -> Any:
    """Resolve Optional / Union / Literal to a single type for schema."""
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        for a in args:
            if a is type(None):
                continue
            return a  # first non-None
    return annotation


def _annotation_to_type(annotation: Any) -> str:
    """Map Pydantic field annotation to client schema type string."""
    ann = _resolve_annotation(annotation)
    if ann in _TYPE_MAP:
        return _TYPE_MAP[ann]
    # Literal values -> string
    return 'string'


def validation_error_to_message(exc: PydanticValidationError) -> str:
    """Convert Pydantic ValidationError to a short message for API/serializer."""
    errs = exc.errors()
    if not errs:
        return str(exc)
    first = errs[0]
    msg = first.get('msg', str(exc))
    loc = first.get('loc', ())
    path = '.'.join(str(x) for x in loc)
    return f"{path}: {msg}" if path else msg


def _field_name_to_label(name: str) -> str:
    """Convert snake_case field name to Title Case label."""
    return name.replace('_', ' ').strip().title() or name


def pydantic_model_to_config_schema(model_class: Type[BaseModel]) -> Dict[str, Dict[str, Any]]:
    """
    Convert a Pydantic model class to ConfigSchema format for client SchemaConfigEditor.

    Returns: { field_name: { type, required?, description?, sensitive?, default? }, ... }
    """
    out: Dict[str, Dict[str, Any]] = {}
    for name, field in model_class.model_fields.items():
        ann = field.annotation
        schema_type = _annotation_to_type(ann)
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        if extra.get('config_type'):
            schema_type = extra['config_type']
        entry: Dict[str, Any] = {
            'type': schema_type,
            'required': field.is_required(),
            'description': field.description or '',
        }
        if field.default is not None and not field.is_required() and _is_json_serializable(field.default):
            entry['default'] = field.default
        # Optional: mark sensitive from Field(description='...') or a convention
        if extra:
            if extra.get('sensitive'):
                entry['sensitive'] = True
            if 'options' in extra:
                entry['options'] = extra['options']
        out[name] = entry
    return out


def pydantic_model_to_form_schema(
    model_class: Type[BaseModel],
    title: str = '',
) -> Dict[str, Any]:
    """
    Convert a Pydantic model class to FormSchema format for client SchemaForm.

    Returns: { title, fields: [ { field, label, type, required?, helperText?, defaultValue? }, ... ] }
    Client FormField type: field, label, type (FieldType), required?, helperText?, defaultValue?
    """
    fields_list: List[Dict[str, Any]] = []
    for name, field in model_class.model_fields.items():
        ann = field.annotation
        schema_type = _annotation_to_type(ann)
        # Client FormSchema uses 'number' for both int and float
        if schema_type == 'integer':
            schema_type = 'number'
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        form_type = extra.get('form_type', schema_type)
        form_field: Dict[str, Any] = {
            'field': name,
            'label': field.description or _field_name_to_label(name),
            'type': form_type,
            'required': field.is_required(),
        }
        if field.description:
            form_field['helperText'] = field.description
        if field.default is not None and not field.is_required() and _is_json_serializable(field.default):
            form_field['defaultValue'] = field.default
        if extra:
            if 'options' in extra:
                form_field['options'] = extra['options']
            if 'placeholder' in extra:
                form_field['placeholder'] = extra['placeholder']
            if extra.get('newline'):
                form_field['newline'] = True
            if extra.get('full_width'):
                form_field['fullWidth'] = True
            if 'rows' in extra:
                form_field['rows'] = extra['rows']
        fields_list.append(form_field)
    return {
        'title': title or model_class.__name__.replace('Model', '').replace('_', ' ').title(),
        'fields': fields_list,
    }

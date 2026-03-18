# -*- coding: utf-8 -*-
"""
API tool catalog for Agent: build OpenAI tools from OpenAPI schema with an allowlist,
and execute allowed operations via internal request (workspace + auth preserved).
"""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Path prefixes allowed for agent (common, shop, delivery, support, finance).
# Paths under api/v1/ without a prefix are flat (orders, customers, etc.).
ALLOWED_PATH_PREFIXES = (
    "/api/v1/customers",
    "/api/v1/addresses",
    "/api/v1/orders",
    "/api/v1/products",
    "/api/v1/categories",
    "/api/v1/variants",
    "/api/v1/stores",
    "/api/v1/consignments",
    "/api/v1/carriers",
    "/api/v1/warehouses",
    "/api/v1/manifests",
    "/api/v1/support/tickets",
    "/api/v1/support/options",
    "/api/v1/invoices",
    "/api/v1/payments",
    "/api/v1/wallets",
    "/api/v1/withdrawal-requests",
    "/api/v1/me/",
    "/api/v1/options",
    "/api/v1/countries",
)

# Exclude auth, schema, agent, web, store (storefront), and dangerous/bulk.
EXCLUDED_PATH_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/agent/",
    "/api/schema",
    "/api/docs",
    "/api/redoc",
    "/api/v1/web/",
    "/api/v1/store/",  # storefront
)

# Methods to expose as tools.
ALLOWED_METHODS = ("get", "post", "patch", "put", "delete")


def _sanitize_tool_name(name: str) -> str:
    """OpenAI function names: letters, numbers, underscores, hyphens only."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return name or "api_call"


def _openapi_params_to_properties(parameters: List[Dict], request_body: Optional[Dict]) -> Tuple[Dict[str, Any], List[str]]:
    """Convert OpenAPI parameters + requestBody to OpenAI function properties and required list."""
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for p in parameters or []:
        if p.get("in") in ("query", "path", "header"):
            name = p.get("name")
            if not name:
                continue
            schema = p.get("schema") or {}
            desc = p.get("description") or ""
            properties[name] = {
                "type": schema.get("type", "string"),
                "description": desc,
            }
            if p.get("required"):
                required.append(name)
    if request_body:
        content = request_body.get("content") or {}
        json_media = content.get("application/json") or content.get("application/json; charset=utf-8")
        if json_media and isinstance(json_media.get("schema"), dict):
            body_schema = json_media["schema"]
            ref = body_schema.get("$ref")
            if ref:
                # We do not resolve $ref here; use a generic body object.
                properties["body"] = {
                    "type": "object",
                    "description": "JSON body for the request",
                }
                required.append("body")
            else:
                props = body_schema.get("properties") or {}
                for k, v in props.items():
                    if isinstance(v, dict):
                        properties[k] = {
                            "type": v.get("type", "string"),
                            "description": v.get("description", ""),
                        }
                for r in body_schema.get("required") or []:
                    if r not in required:
                        required.append(r)
    return properties, required


def _get_schema(request: Optional[Any] = None) -> Dict[str, Any]:
    """Get OpenAPI schema from drf_spectacular (request optional for permission context)."""
    try:
        from drf_spectacular.generators import SchemaGenerator
        generator = SchemaGenerator()
        return generator.get_schema(request=request, public=True) or {}
    except Exception as e:
        logger.warning("Failed to get OpenAPI schema: %s", e)
        return {}


def _path_allowed(path: str) -> bool:
    if not path.startswith("/api/v1/"):
        return False
    for exc in EXCLUDED_PATH_PREFIXES:
        if path.startswith(exc.rstrip("/")) or (exc.endswith("/") and path.startswith(exc)):
            return False
    for allowed in ALLOWED_PATH_PREFIXES:
        if path == allowed or path.startswith(allowed + "/"):
            return True
    return False


def build_api_tools_from_schema(schema: Dict[str, Any]) -> Tuple[List[Dict], Dict[str, Dict]]:
    """
    Build OpenAI tools list and tool_name -> op_spec from OpenAPI schema.
    op_spec: { "path": str, "method": str, "path_params": [str], "query_params": [str], "body_keys": [str] }
    """
    tools: List[Dict] = []
    tool_specs: Dict[str, Dict] = {}
    paths = schema.get("paths") or {}
    for raw_path, path_item in paths.items():
        path = ("/" + raw_path) if raw_path and not raw_path.startswith("/") else raw_path
        if not _path_allowed(path):
            continue
        for method in ALLOWED_METHODS:
            op = (path_item or {}).get(method)
            if not op or not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or f"{method}_{path.replace('/', '_').strip('_')}"
            tool_name = _sanitize_tool_name(op_id)
            if tool_name in tool_specs:
                tool_name = _sanitize_tool_name(op_id + "_" + method)
            if tool_name in tool_specs:
                continue
            parameters = op.get("parameters") or []
            request_body = op.get("requestBody")
            path_params = [p["name"] for p in parameters if p.get("in") == "path"]
            query_params = [p["name"] for p in parameters if p.get("in") == "query"]
            body_keys: List[str] = []
            if request_body:
                content = request_body.get("content") or {}
                json_media = content.get("application/json") or content.get("application/json; charset=utf-8")
                if json_media and isinstance(json_media.get("schema"), dict):
                    body_schema = json_media["schema"]
                    if body_schema.get("$ref"):
                        body_keys = ["body"]
                    else:
                        body_keys = list((body_schema.get("properties") or {}).keys())
            properties, required = _openapi_params_to_properties(parameters, request_body)
            description = (op.get("summary") or op.get("description") or f"{method.upper()} {path}").strip()
            if len(description) > 300:
                description = description[:297] + "..."
            tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
            tool_specs[tool_name] = {
                "path": path,
                "method": method.upper(),
                "path_params": path_params,
                "query_params": query_params,
                "body_keys": body_keys,
            }
    return tools, tool_specs


def get_api_tools(request: Optional[Any] = None) -> Tuple[List[Dict], Dict[str, Dict]]:
    """Get OpenAI tools and tool_specs for allowed API operations (schema loaded once per call)."""
    schema = _get_schema(request)
    return build_api_tools_from_schema(schema)


def execute_api_tool(
    request: Any,
    tool_name: str,
    tool_specs: Dict[str, Dict],
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute an API tool by dispatching an internal request to the same API.
    request must have user, auth, and workspace (X-Workspace-ID). Returns { "success", "data" } or { "success": False, "error" }.
    """
    spec = tool_specs.get(tool_name)
    if not spec:
        return {"success": False, "error": f"Unknown API tool: {tool_name}"}
    path_template = spec["path"]
    method = spec["method"]
    path_params = spec.get("path_params") or []
    query_params = spec.get("query_params") or []
    body_keys = spec.get("body_keys") or []

    # Build path: substitute {pk}, {id}, etc.
    path = path_template
    for param in path_params:
        value = arguments.get(param)
        if value is None:
            return {"success": False, "error": f"Missing path parameter: {param}"}
        path = path.replace("{" + param + "}", str(value))
    if "{" in path:
        return {"success": False, "error": f"Missing path parameters for {path}"}

    # Build query string
    query_dict: Dict[str, str] = {}
    for q in query_params:
        if q in arguments and arguments[q] is not None:
            query_dict[q] = str(arguments[q])
    query_string = "&".join(f"{k}={v}" for k, v in sorted(query_dict.items())) if query_dict else ""

    # Build body for POST/PATCH/PUT
    body = None
    if method in ("POST", "PUT", "PATCH") and body_keys:
        if "body" in arguments and arguments["body"] is not None:
            body = arguments["body"] if isinstance(arguments["body"], dict) else {}
        else:
            body = {k: arguments[k] for k in body_keys if k in arguments and arguments[k] is not None}

    from django.test import RequestFactory
    from django.urls import resolve

    factory = RequestFactory()
    full_path = path + ("?" + query_string if query_string else "")
    if method == "GET":
        req = factory.get(full_path)
    elif method == "POST":
        req = factory.post(
            path, data=json.dumps(body or {}), content_type="application/json"
        )
    elif method == "PATCH":
        req = factory.patch(
            path, data=json.dumps(body or {}), content_type="application/json"
        )
    elif method == "PUT":
        req = factory.put(
            path, data=json.dumps(body or {}), content_type="application/json"
        )
    elif method == "DELETE":
        req = factory.delete(full_path)
    else:
        return {"success": False, "error": f"Unsupported method: {method}"}

    req.user = getattr(request, "user", None)
    req.workspace = getattr(request, "workspace", None)
    if hasattr(request, "auth") and request.auth is not None:
        req.auth = request.auth
    if req.workspace:
        req.META["HTTP_X_WORKSPACE_ID"] = str(req.workspace.id)

    try:
        match = resolve(path)
        view_func = match.func
        view_kwargs = copy.copy(match.kwargs)
        response = view_func(req, **view_kwargs)
    except Exception as e:
        logger.exception("API tool %s failed", tool_name)
        return {"success": False, "error": str(e)}

    try:
        if hasattr(response, "data"):
            data = response.data
        elif hasattr(response, "content"):
            try:
                data = json.loads(response.content.decode("utf-8"))
            except Exception:
                data = {"content": response.content.decode("utf-8", errors="replace")}
        else:
            data = {"status_code": getattr(response, "status_code", None)}
    except Exception:
        data = {}

    status_code = getattr(response, "status_code", 200)
    if 200 <= status_code < 300:
        return {"success": True, "data": data}
    return {
        "success": False,
        "error": data.get("detail", data.get("error", str(data))),
        "data": data,
    }

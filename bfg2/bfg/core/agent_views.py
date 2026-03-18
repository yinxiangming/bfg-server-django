# -*- coding: utf-8 -*-
"""
Agent API views: GET capabilities (permission-filtered), POST execute (permission-checked), POST chat (OpenAI + tools).
API tools (from OpenAPI allowlist) are primary; manual capability wrappers are fallback for high-risk/multi-step ops.
"""
import json
import logging
import os
import re
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import StreamingHttpResponse

from bfg.core.agent import AgentCapabilityRegistry, AgentCapability, _FakeView
from bfg.core.api_tool_catalog import get_api_tools, execute_api_tool

logger = logging.getLogger(__name__)

# OpenAI API allows max 128 tools per request
OPENAI_MAX_TOOLS = 128

# Category keywords for filtering API tools by name/description (lowercase)
TOOL_CATEGORY_KEYWORDS = {
    "order": ["order", "orders"],
    "customer": ["customer", "customers", "address", "addresses"],
    "product": ["product", "products", "variant", "variants", "categor", "category"],
    "ticket": ["ticket", "tickets", "support"],
    "invoice": ["invoice", "invoices"],
    "payment": ["payment", "payments", "wallet", "wallets", "refund"],
    "delivery": ["delivery", "consignment", "consignments", "carrier", "carriers", "ship", "manifest", "warehouse", "freight", "tracking"],
    "settings": ["settings", "workspace", "options", "countries"],
}

ALLOWED_CATEGORIES = list(TOOL_CATEGORY_KEYWORDS.keys())


def _infer_tool_categories_with_llm(messages, client, selector_model: str):
    """
    Use a cheap model to infer which resource categories are relevant to the conversation.
    Returns a list of category names (e.g. ["order", "customer"]) or empty on failure.
    """
    if not messages:
        return []
    user_text = " ".join(
        (m.get("content") or "")
        for m in messages
        if (m.get("role") or "").strip().lower() == "user"
        and isinstance(m.get("content"), str)
    ).strip()
    if not user_text:
        return []
    prompt = (
        "Based on the user message below, select which resource types are needed to answer or act. "
        "Reply with a JSON array of strings only, choosing from this exact list: "
        + ", ".join(ALLOWED_CATEGORIES)
        + ". Include only relevant types. Example: [\"order\", \"customer\"].\n\nUser: "
        + user_text[:1500]
    )
    try:
        resp = client.chat.completions.create(
            model=selector_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        content = (resp.choices[0].message.content or "").strip()
        # Extract JSON array (handle markdown code blocks)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return [c for c in parsed if isinstance(c, str) and c in ALLOWED_CATEGORIES]
        return []
    except Exception as e:
        logger.warning("Tool category inference failed: %s", e)
        return []


def _filter_tools_by_categories(tools, tool_name_to_capability_id, categories, max_tools=OPENAI_MAX_TOOLS):
    """
    Keep all manual (capability) tools; keep API tools whose name/description matches any of the
    given categories. Cap total at max_tools. If categories is empty, keep manual + first N API tools.
    """
    manual = [t for t in tools if t["function"]["name"] in tool_name_to_capability_id]
    api_tools = [t for t in tools if t["function"]["name"] not in tool_name_to_capability_id]
    budget = max_tools - len(manual)
    if budget <= 0 or not api_tools:
        return manual[:max_tools] if len(manual) > max_tools else manual

    if not categories:
        return manual + api_tools[:budget]

    keywords = set()
    for c in categories:
        keywords.update(TOOL_CATEGORY_KEYWORDS.get(c, []))

    def matches(t):
        name = (t.get("function") or {}).get("name") or ""
        desc = (t.get("function") or {}).get("description") or ""
        combined = f"{name} {desc}".lower()
        return any(kw in combined for kw in keywords)

    selected_api = [t for t in api_tools if matches(t)]
    if len(selected_api) > budget:
        selected_api = selected_api[:budget]
    return manual + selected_api


def _tool_name_from_capability_id(capability_id: str) -> str:
    """
    Convert internal capability id to a valid OpenAI tool name.

    OpenAI function names may only contain letters, numbers, underscores, and hyphens.
    """
    tool_name = capability_id.replace(".", "_")
    tool_name = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name)
    return tool_name or "tool"


def _openai_tools_from_capabilities(capabilities):
    """Build OpenAI tools array and name mapping from capability list."""
    tools = []
    tool_name_to_capability_id = {}
    for cap in capabilities:
        tool_name = _tool_name_from_capability_id(cap.id)
        tool_name_to_capability_id[tool_name] = cap.id
        tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": cap.description,
                "parameters": {
                    "type": "object",
                    "properties": cap.input_schema.get("properties", {}),
                    "required": cap.input_schema.get("required", []),
                },
            },
        })
    return tools, tool_name_to_capability_id


def _user_has_permission_for_capability(request, capability: AgentCapability) -> bool:
    """Return True if request.user has required_permission for this capability."""
    if not capability.required_permission:
        return True
    view = _FakeView(capability.required_permission)
    return all(
        perm().has_permission(request, view)
        for perm in capability.required_permission
    )


def _merged_tools_and_mappings(request):
    """
    Return (openai_tools_list, tool_name_to_capability_id, api_tool_specs).
    API tools first, then manual capability tools. Only capability tools have tool_name_to_capability_id;
    API tools are executed via api_tool_specs.
    """
    api_tools, api_tool_specs = get_api_tools(request)
    capabilities = AgentCapabilityRegistry.list_all(request)
    manual_tools, tool_name_to_capability_id = _openai_tools_from_capabilities(capabilities)
    # API tool names must not clash with manual tool names (operationId vs capability id).
    combined_tools = api_tools + manual_tools
    return combined_tools, tool_name_to_capability_id, api_tool_specs


class AgentCapabilitiesView(APIView):
    """
    GET /api/v1/agent/capabilities/
    Returns capabilities the current user is allowed to execute (id, name, description, app_label, input_schema).
    Query: ?format=openai_tools to return LLM tools array (API tools + manual capabilities).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        capabilities = AgentCapabilityRegistry.list_all(request)
        format_type = (request.query_params.get("format") or "").strip().lower()

        if format_type == "openai_tools":
            tools, _, _ = _merged_tools_and_mappings(request)
            return Response({"tools": tools})

        return Response({
            "capabilities": [c.to_public_dict() for c in capabilities],
        })


class AgentExecuteView(APIView):
    """
    POST /api/v1/agent/execute/
    Body: { "capability_id": "delivery.ship_order", "arguments": { "order_id": 123, ... } }
    Validates capability exists, user has permission, arguments match input_schema, then calls handler.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        capability_id = (request.data.get("capability_id") or "").strip()
        arguments = request.data.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return Response(
                    {"detail": "arguments must be a valid JSON object"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return Response(
                {"detail": "arguments must be an object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not capability_id:
            return Response(
                {"detail": "capability_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        capability = AgentCapabilityRegistry.get(capability_id)
        if not capability:
            return Response(
                {"detail": f"Unknown capability: {capability_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _user_has_permission_for_capability(request, capability):
            return Response(
                {"detail": "You do not have permission to execute this capability."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Simple schema check: required fields present
        schema = capability.input_schema or {}
        required = schema.get("required", [])
        for key in required:
            if key not in arguments:
                return Response(
                    {"detail": f"Missing required argument: {key}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            result = capability.handler(request, **arguments)
            if not isinstance(result, dict):
                result = {"success": True, "data": result}
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Agent execute %s failed", capability_id)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AgentChatView(APIView):
    """
    POST /api/v1/agent/chat/
    Body: { messages: [{ role, content }], workspace_id?: number }
    Uses OpenAI chat completions with capabilities as tools; executes tool_calls and returns reply + tool_calls_made.
    """
    permission_classes = [IsAuthenticated]
    max_tool_rounds = 5

    def _ensure_workspace(self, request):
        """Optionally override request.workspace from body workspace_id (staff check)."""
        workspace_id = request.data.get("workspace_id")
        if workspace_id is None:
            return
        from bfg.common.models import Workspace, StaffMember
        try:
            wid = int(workspace_id)
        except (TypeError, ValueError):
            return
        try:
            workspace = Workspace.objects.get(id=wid, is_active=True)
        except Workspace.DoesNotExist:
            return
        if not request.user.is_superuser and not StaffMember.objects.filter(
            workspace=workspace, user=request.user, is_active=True
        ).exists():
            return
        request.workspace = workspace

    def post(self, request):
        self._ensure_workspace(request)
        workspace = getattr(request, "workspace", None)
        if not workspace:
            return Response(
                {"detail": "Workspace is required. Set X-Workspace-ID header or workspace_id in body."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        messages = request.data.get("messages")
        if not isinstance(messages, list) or not messages:
            return Response(
                {"detail": "messages array is required (e.g. [{ role: 'user', content: '...' }])."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return Response(
                {"detail": "OpenAI is not configured (OPENAI_API_KEY)."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        selector_model = os.environ.get("OPENAI_TOOL_SELECTOR_MODEL", "gpt-4o-mini")

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
        except ImportError:
            return Response(
                {"detail": "openai package not installed."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        tools, tool_name_to_capability_id, api_tool_specs = _merged_tools_and_mappings(request)
        categories = _infer_tool_categories_with_llm(messages, client, selector_model)
        tools = _filter_tools_by_categories(
            tools, tool_name_to_capability_id, categories, OPENAI_MAX_TOOLS
        )
        capabilities = AgentCapabilityRegistry.list_all(request)
        cap_by_id = {c.id: c for c in capabilities}

        # Build system message; inject context_url so the model knows current page (e.g. order id from /orders/13/edit).
        system_content = (
            "You are an internal workspace AI assistant. Analyze the user's request from the "
            "conversation. Use tools only when they are needed to complete the task. "
            "Never claim to have executed an action unless a tool call succeeded. "
            "If required details are missing, ask a concise follow-up question. "
            "Never guess internal IDs from business identifiers. "
            "If the user provides an order number, SKU, code, or similar business identifier, "
            "resolve it via tools first instead of converting it into a numeric ID."
        )
        context_url = (request.data.get("context_url") or "").strip()
        if context_url:
            system_content += (
                "\n\nContext: The user opened this chat from the following page. Use it to resolve "
                "implicit references (e.g. .../orders/13/edit means the current order id is 13; "
                ".../tickets/5 or .../support/tickets/5 means the current ticket id is 5).\nPage URL: "
            ) + context_url
        openai_messages = [{"role": "system", "content": system_content}]
        for m in messages:
            role = (m.get("role") or "user").strip().lower()
            content = m.get("content")
            if content is None:
                content = ""
            if role not in ("system", "user", "assistant"):
                role = "user"
            openai_messages.append({"role": role, "content": str(content)})

        stream_requested = request.data.get("stream") is True
        if stream_requested:
            return self._stream_chat(
                request, client, model, openai_messages, tools,
                tool_name_to_capability_id, api_tool_specs, cap_by_id,
            )

        tool_calls_made = []
        round_count = 0
        reply = ""

        while round_count < self.max_tool_rounds:
            kwargs = {"model": model, "messages": openai_messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0] if response.choices else None
            if not choice:
                break
            msg = choice.message
            if not msg.content and not getattr(msg, "tool_calls", None):
                break
            if msg.content:
                reply = (msg.content or "").strip()
            openai_messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": getattr(msg, "tool_calls", None) or [],
            })
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                break
            for tc in tool_calls:
                tool_name = getattr(tc, "function", None) and getattr(tc.function, "name", None) or ""
                args_str = getattr(tc.function, "arguments", None) or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                if tool_name in api_tool_specs:
                    result = execute_api_tool(request, tool_name, api_tool_specs, args)
                    tool_calls_made.append({
                        "capability_id": None,
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": result,
                    })
                else:
                    capability_id = tool_name_to_capability_id.get(tool_name, "")
                    cap = cap_by_id.get(capability_id)
                    if not cap:
                        result = {"success": False, "error": f"Unknown capability for tool: {tool_name}"}
                    elif not _user_has_permission_for_capability(request, cap):
                        result = {"success": False, "error": "Permission denied"}
                    else:
                        try:
                            result = cap.handler(request, **args)
                            if not isinstance(result, dict):
                                result = {"result": result}
                        except Exception as e:
                            logger.exception("Agent chat tool %s failed", tool_name)
                            result = {"success": False, "error": str(e)}
                    tool_calls_made.append({
                        "capability_id": cap.id if cap else capability_id,
                        "tool_name": tool_name,
                        "arguments": args,
                        "result": result,
                    })
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": getattr(tc, "id", ""),
                    "content": json.dumps(result, default=str),
                })
            round_count += 1

        return Response({
            "reply": reply,
            "tool_calls_made": tool_calls_made,
        }, status=status.HTTP_200_OK)

    def _stream_chat(
        self, request, client, model, openai_messages, tools,
        tool_name_to_capability_id, api_tool_specs, cap_by_id,
    ):
        """Return StreamingHttpResponse with SSE: content deltas, tool_names, done."""

        def sse(data):
            return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")

        def gen():
            nonlocal openai_messages
            tool_names_all = []
            tool_results_all = []  # list of {"name", "success", "error"} for frontend to show errors
            round_count = 0
            while round_count < self.max_tool_rounds:
                kwargs = {"model": model, "messages": openai_messages, "stream": True}
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                stream = client.chat.completions.create(**kwargs)
                content_parts = []
                tool_calls_accum = {}
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        content_parts.append(delta.content)
                        yield sse({"type": "content", "delta": delta.content})
                    if getattr(delta, "tool_calls", None):
                        for tc in delta.tool_calls:
                            idx = getattr(tc, "index", None)
                            if idx is None:
                                continue
                            if idx not in tool_calls_accum:
                                tool_calls_accum[idx] = {"id": "", "name": "", "arguments": ""}
                            if getattr(tc, "id", None):
                                tool_calls_accum[idx]["id"] = tc.id
                            if getattr(tc, "function", None):
                                if getattr(tc.function, "name", None):
                                    tool_calls_accum[idx]["name"] = tc.function.name
                                if getattr(tc.function, "arguments", None):
                                    tool_calls_accum[idx]["arguments"] += tc.function.arguments
                full_content = "".join(content_parts)
                tool_calls_list = [tool_calls_accum[i] for i in sorted(tool_calls_accum.keys())]
                openai_messages.append({
                    "role": "assistant",
                    "content": full_content,
                    "tool_calls": [
                        {"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": t["arguments"]}}
                        for t in tool_calls_list
                    ] if tool_calls_list else [],
                })
                if not tool_calls_list:
                    yield sse({"type": "done", "reply": full_content.strip(), "tool_names": tool_names_all, "tool_results": tool_results_all})
                    return
                names_this_round = [t.get("name") or "" for t in tool_calls_list]
                tool_names_all.extend(names_this_round)
                yield sse({"type": "tool_names", "names": names_this_round})
                for tc in tool_calls_list:
                    tool_name = tc.get("name") or ""
                    args_str = tc.get("arguments") or "{}"
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = {}
                    if tool_name in api_tool_specs:
                        result = execute_api_tool(request, tool_name, api_tool_specs, args)
                    else:
                        capability_id = tool_name_to_capability_id.get(tool_name, "")
                        cap = cap_by_id.get(capability_id)
                        if not cap:
                            result = {"success": False, "error": f"Unknown capability for tool: {tool_name}"}
                        elif not _user_has_permission_for_capability(request, cap):
                            result = {"success": False, "error": "Permission denied"}
                        else:
                            try:
                                result = cap.handler(request, **args)
                                if not isinstance(result, dict):
                                    result = {"result": result}
                            except Exception as e:
                                logger.exception("Agent chat tool %s failed", tool_name)
                                result = {"success": False, "error": str(e)}
                    success = result.get("success", True) if isinstance(result, dict) else True
                    err_msg = result.get("error") if isinstance(result, dict) else None
                    tool_results_all.append({"name": tool_name, "success": success, "error": err_msg})
                    yield sse({"type": "tool_result", "name": tool_name, "success": success, "error": err_msg})
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result, default=str),
                    })
                round_count += 1
            yield sse({"type": "done", "reply": "", "tool_names": tool_names_all, "tool_results": tool_results_all})

        return StreamingHttpResponse(
            gen(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

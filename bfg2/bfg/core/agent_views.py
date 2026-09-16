# -*- coding: utf-8 -*-
"""
Agent API views: GET capabilities (permission-filtered), POST execute (permission-checked), POST chat (OpenAI + tools).
API tools (from OpenAPI allowlist) are primary; manual capability wrappers are fallback for high-risk/multi-step ops.

Chat spends a vendor's money, so it is metered: the workspace is asked once,
before anything is sent, whether it may spend at all, and every model call that
comes back is counted in ``ai.<model>.input``, ``ai.<model>.input_cached`` and
``ai.<model>.output``. See "What the assistant spends" below.
"""
import json
import logging
import os
import re
from collections.abc import Mapping
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import StreamingHttpResponse

from bfg.common.extensions.permissions import EXTENSION_DISABLED
from bfg.core.agent import AgentCapabilityRegistry, AgentCapability, _FakeView
from bfg.core.api_tool_catalog import get_api_tools, execute_api_tool

logger = logging.getLogger(__name__)

# OpenAI API allows max 128 tools per request
OPENAI_MAX_TOOLS = 128

# Returned with 402 once a workspace has run up its month's points. A code as well
# as a message so that a client can recognise this case and offer to raise the cap,
# rather than having to match on wording it did not choose.
USAGE_CAP_REACHED = "usage_cap_reached"

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


# ── What the assistant spends ────────────────────────────────────────────────
#
# Every model call is billed, so every model call is counted. Tokens are metered
# per model and per kind, because that is how they are priced — an output token
# costs several times an input one, and an input token the vendor served from its
# prompt cache costs a fraction of a fresh one. One call therefore records up to
# three meters, named for the model that was asked:
#
#     ai.<model>.input          tokens sent, less any the vendor served from cache
#     ai.<model>.input_cached   tokens the vendor served from its prompt cache
#     ai.<model>.output         tokens generated
#
# ``<model>`` is the model id actually requested, lowercased: a deployment that
# moves to another model starts filling another set of meters, and the old prices
# stay attached to the calls that were made at them.


def _token_meters(model: str):
    """The input, cached-input and output meter names for ``model``."""
    name = (model or "").strip().lower()
    return f"ai.{name}.input", f"ai.{name}.input_cached", f"ai.{name}.output"


def _metering():
    """The metering client, or ``None`` where this deployment has no billing.

    Imported here rather than at the top of the module. ``bfg.core`` is installed
    by every deployment; ``bfg.platform``, which owns what a workspace may spend,
    is not, and importing its models on a deployment that leaves that app out
    would take the whole assistant API down with it. A deployment without it
    bills nobody, so the assistant runs unmetered rather than not at all.
    """
    try:
        from bfg.platform import metering
    except Exception:  # pragma: no cover - only a deployment without the app hits this
        return None
    return metering


def _may_spend_on_model(workspace, model: str) -> bool:
    """Whether ``workspace`` may make a paid call to ``model`` right now.

    Asked once per request, before anything is sent. The cap is on the workspace
    rather than on any one meter, so asking again for the cached-input meter, for
    the selector model, or between the rounds of a single answer would only get
    the same answer at the price of another query — and stopping halfway through
    an answer would leave the assistant having run tools it never reports on.

    A request with no workspace bound is not refused: there is nobody to bill, so
    there is no cap to have reached, and an assistant that stopped working
    wherever billing does not apply would be worse than an unbilled call.
    """
    if workspace is None:
        return True
    metering = _metering()
    if metering is None:
        return True
    return metering.allowed(workspace, _token_meters(model)[0])


def _usage_cap_response():
    """The 402 a caller gets once its workspace has spent the month's points."""
    return Response(
        {
            "code": USAGE_CAP_REACHED,
            "detail": (
                "This workspace has used all of this month's AI allowance. The assistant "
                "works again when the allowance resets at the start of next month, or as "
                "soon as the monthly usage cap is raised."
            ),
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _field(obj, name):
    """``name`` off ``obj``, whether it holds attributes or keys, or None.

    Both, because what arrives here is whatever the installed client returns: a
    model object from the OpenAI package, or a plain dict from a gateway that
    hands the JSON straight back.
    """
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _tokens(value) -> int:
    """``value`` as a token count: whole, never negative, 0 when it is not a number."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


def _token_counts(response):
    """Fresh input, cached input and output tokens ``response`` reports, or None.

    None when the response carries no usage at all, which is what a stream asked
    for without usage, an error object, or a gateway that drops the field looks
    like. Nothing is billed for a call whose cost was never reported: a guess
    would end up on somebody's invoice.

    ``prompt_tokens`` counts cached and fresh input together, so the cached half
    is taken out of it — a vendor that reports no ``prompt_tokens_details`` leaves
    every input token counted as fresh, which is the more expensive reading and
    the only one its response supports. More cached than sent is nonsense from the
    vendor, and capped rather than trusted: a negative count would not be an
    overcharge but a refund, taking usage off somebody's bill.
    """
    usage = _field(response, "usage")
    if usage is None:
        return None
    prompt = _tokens(_field(usage, "prompt_tokens"))
    cached = min(_tokens(_field(_field(usage, "prompt_tokens_details"), "cached_tokens")), prompt)
    return prompt - cached, cached, _tokens(_field(usage, "completion_tokens"))


def _meter_tokens(workspace, model: str, response) -> None:
    """Record what a finished call to ``model`` used against ``workspace``.

    Called once the vendor has answered, so what is billed is what was delivered,
    and never before, so a call that failed is not charged for. Nothing here may
    raise: the money is already spent, and failing the request now would lose the
    answer as well as the money. ``metering.meter`` swallows its own failures;
    reading the usage off an object of a shape this code did not choose is guarded
    here for the same reason.
    """
    if workspace is None:
        return
    metering = _metering()
    if metering is None:
        return
    try:
        counts = _token_counts(response)
    except Exception:
        logger.exception("Could not read the token usage of a %s call", model)
        return
    if counts is None:
        return
    for meter_name, tokens in zip(_token_meters(model), counts):
        # A meter with nothing to count is left alone rather than recorded as
        # zero: a call with no cached input should not put a row on the bill.
        if tokens:
            metering.meter(workspace, meter_name, tokens)


def _infer_tool_categories_with_llm(messages, client, selector_model: str, workspace=None):
    """
    Use a cheap model to infer which resource categories are relevant to the conversation.
    Returns a list of category names (e.g. ["order", "customer"]) or empty on failure.

    The selector is a paid call of its own and is metered as one, under its own
    model's meters — it is usually a cheaper model than the one that answers, and
    a deployment reading its bill should see the two apart. ``workspace`` is who
    pays; without one the call is still made and simply not counted.
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
        # Before the reply is read, not after: the tokens were spent whether or
        # not what came back is the JSON array this asked for.
        _meter_tokens(workspace, selector_model, resp)
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
    Validates capability exists, user has permission, the workspace can use it, arguments match input_schema,
    then calls handler.
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

        if not AgentCapabilityRegistry.workspace_can_use(request, capability):
            return Response(
                {
                    "code": EXTENSION_DISABLED,
                    "detail": f"{capability_id} belongs to an extension that is not enabled for this workspace.",
                },
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
        # After _ensure_workspace, never before: a staff member may answer for
        # another of their workspaces, and the one that pays for the call has to
        # be the one the call is made for.
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

        # Before the client exists, so that a workspace over its cap costs nothing
        # at all: no selector call, no answer, nothing to meter afterwards.
        if not _may_spend_on_model(workspace, model):
            return _usage_cap_response()

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
        except ImportError:
            return Response(
                {"detail": "openai package not installed."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        tools, tool_name_to_capability_id, api_tool_specs = _merged_tools_and_mappings(request)
        categories = _infer_tool_categories_with_llm(messages, client, selector_model, workspace)
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
                tool_name_to_capability_id, api_tool_specs, cap_by_id, workspace,
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
            # Every round is a call of its own and costs its own tokens, so each
            # is metered as it comes back rather than the answer being counted
            # once at the end — a round that raises has still been paid for by
            # the rounds before it.
            _meter_tokens(workspace, model, response)
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
        tool_name_to_capability_id, api_tool_specs, cap_by_id, workspace=None,
    ):
        """Return StreamingHttpResponse with SSE: content deltas, tool_names, done.

        A streamed answer costs the same as one returned in a single response and
        is metered the same way, which is why it asks for ``stream_options``: a
        stream reports its tokens only in a final chunk, and only when asked. A
        vendor that ignores the option leaves the usage unreported, and an
        unreported call is not billed rather than guessed at.
        """

        def sse(data):
            return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")

        def gen():
            nonlocal openai_messages
            tool_names_all = []
            tool_results_all = []  # list of {"name", "success", "error"} for frontend to show errors
            round_count = 0
            while round_count < self.max_tool_rounds:
                kwargs = {
                    "model": model,
                    "messages": openai_messages,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                stream = client.chat.completions.create(**kwargs)
                content_parts = []
                tool_calls_accum = {}
                for chunk in stream:
                    # The usage chunk is the last one and carries no choices, so
                    # it has to be read before the loop skips it.
                    if _field(chunk, "usage") is not None:
                        _meter_tokens(workspace, model, chunk)
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

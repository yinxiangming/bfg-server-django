"""The assistant's model calls: asked for once before spending, counted after.

No request leaves the machine — the ``openai`` package is replaced by a fake whose
replies each test writes itself, which is also how a response missing the fields
this code reads is arranged.
"""

import sys
import types
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from bfg.common.models import Workspace
from bfg.core import agent_views
from bfg.core.agent import AgentCapabilityRegistry
from bfg.core.agent_views import AgentChatView
from bfg.platform.models import MeterPrice, UsageRecord, WorkspacePlatformProfile

User = get_user_model()

# Mixed case on purpose: the meters are named for the model in lower case, so a
# deployment does not end up with two sets of meters for one model.
ANSWER_MODEL = "Test-Model-1"
SELECTOR_MODEL = "Selector-Model"

ANSWER_INPUT, ANSWER_CACHED, ANSWER_OUTPUT = agent_views._token_meters(ANSWER_MODEL)
SELECTOR_INPUT, SELECTOR_CACHED, SELECTOR_OUTPUT = agent_views._token_meters(SELECTOR_MODEL)


# ── the deployment around the view ───────────────────────────────────


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name="Assistant", slug="assistant-ws", is_active=True)


@pytest.fixture(autouse=True)
def prices(db):
    """A dollar per million tokens at no margin, so a token is a millionth of a point."""
    for meter in (
        ANSWER_INPUT, ANSWER_CACHED, ANSWER_OUTPUT,
        SELECTOR_INPUT, SELECTOR_CACHED, SELECTOR_OUTPUT,
    ):
        MeterPrice.objects.create(
            meter=meter,
            vendor_cost=Decimal("1"),
            unit_size=1_000_000,
            margin=Decimal("0"),
            effective_from=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
        )


@pytest.fixture(autouse=True)
def no_tools(monkeypatch):
    """Nothing here is about which tools the model is offered, so it is offered none."""
    monkeypatch.setattr(agent_views, "_merged_tools_and_mappings", lambda request: ([], {}, {}))
    monkeypatch.setattr(AgentCapabilityRegistry, "list_all", staticmethod(lambda request: []))


class FakeCompletions:
    """Stands in for ``client.chat.completions``, handing back prepared replies."""

    def __init__(self):
        self.calls = []
        self.replies = []

    def expect(self, *replies):
        self.replies.extend(replies)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.replies:
            raise AssertionError(f"the view made an unexpected model call: {kwargs.get('model')}")
        reply = self.replies.pop(0)
        return reply() if callable(reply) else reply


@pytest.fixture
def openai(monkeypatch):
    completions = FakeCompletions()
    module = types.ModuleType("openai")
    module.OpenAI = lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    # The view imports openai inside the request, so replacing the module is
    # enough and no deployment needs the real package installed to run this.
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", ANSWER_MODEL)
    monkeypatch.setenv("OPENAI_TOOL_SELECTOR_MODEL", SELECTOR_MODEL)
    return completions


# ── the shapes a vendor answers in ───────────────────────────────────


def usage(prompt, completion, cached=None):
    """A usage object; ``cached=None`` leaves out the field entirely, as vendors do."""
    fields = {"prompt_tokens": prompt, "completion_tokens": completion}
    if cached is not None:
        fields["prompt_tokens_details"] = SimpleNamespace(cached_tokens=cached)
    return SimpleNamespace(**fields)


def answer(content="All done.", tokens=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    reply = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    if tokens is not None:
        reply.usage = tokens
    return reply


def selection(categories='["order"]', tokens=None):
    return answer(content=categories, tokens=tokens if tokens is not None else usage(10, 5))


def tool_call(name="orders_count"):
    return SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments="{}"))


def chunk(content=None, tokens=None):
    """One streamed chunk: content, or the usage chunk that ends a stream."""
    if content is None:
        return SimpleNamespace(choices=[], usage=tokens)
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def chat(workspace, **body):
    body.setdefault("messages", [{"role": "user", "content": "how many orders today?"}])
    request = APIRequestFactory().post("/", body, format="json")
    request.workspace = workspace
    force_authenticate(request, user=User(username="staff"))
    return AgentChatView.as_view()(request)


def metered():
    """Every meter recorded so far, and how much of it."""
    return {
        record.meter: record.quantity
        for record in UsageRecord.all_objects.all()
    }


# ── counting a finished call ─────────────────────────────────────────


def test_a_finished_call_is_metered_as_input_cached_input_and_output(workspace, openai):
    openai.expect(
        selection(tokens=usage(10, 5)),
        answer(tokens=usage(prompt=100, completion=20, cached=40)),
    )

    response = chat(workspace)

    assert response.status_code == 200
    assert metered() == {
        # The 40 tokens the vendor served from its cache are counted as cached
        # and taken out of the fresh input, not billed twice.
        ANSWER_INPUT: Decimal("60"),
        ANSWER_CACHED: Decimal("40"),
        ANSWER_OUTPUT: Decimal("20"),
        # The selector is a call of its own, under its own model's meters.
        SELECTOR_INPUT: Decimal("10"),
        SELECTOR_OUTPUT: Decimal("5"),
    }


def test_tokens_are_priced_at_the_meters_own_price(workspace, openai):
    openai.expect(selection(), answer(tokens=usage(prompt=1_000_000, completion=0)))

    chat(workspace)

    record = UsageRecord.all_objects.get(meter=ANSWER_INPUT)
    assert record.points == Decimal("1.00000000")


def test_input_is_counted_whole_when_the_vendor_reports_no_cache(workspace, openai):
    openai.expect(selection(), answer(tokens=usage(prompt=100, completion=20)))

    chat(workspace)

    assert metered()[ANSWER_INPUT] == Decimal("100")
    # Nothing was cached, so nothing is recorded against the cached meter.
    assert ANSWER_CACHED not in metered()


def test_more_cached_input_than_input_is_capped_rather_than_refunded(workspace, openai):
    openai.expect(selection(), answer(tokens=usage(prompt=10, completion=2, cached=50)))

    chat(workspace)

    # Nonsense from the vendor, but never a negative quantity: that would take
    # usage back off the bill.
    assert ANSWER_INPUT not in metered()
    assert metered()[ANSWER_CACHED] == Decimal("10")


def test_a_reply_that_reports_no_usage_is_not_billed_but_is_still_answered(workspace, openai):
    openai.expect(selection(), answer(content="All done."))

    response = chat(workspace)

    assert response.status_code == 200
    assert response.data["reply"] == "All done."
    assert ANSWER_INPUT not in metered()


def test_usage_reported_as_plain_json_is_read_too(workspace, openai):
    # A gateway that hands the vendor's JSON back unchanged, rather than the
    # model objects the OpenAI package builds.
    reply = answer()
    reply.usage = {"prompt_tokens": 30, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 10}}
    openai.expect(selection(), reply)

    chat(workspace)

    assert metered()[ANSWER_INPUT] == Decimal("20")
    assert metered()[ANSWER_CACHED] == Decimal("10")


def test_usage_that_cannot_be_read_is_logged_rather_than_losing_the_answer(workspace, openai, caplog):
    class Unreadable:
        @property
        def prompt_tokens(self):
            raise RuntimeError("this field is a landmine")

    openai.expect(selection(), answer(tokens=Unreadable()))

    response = chat(workspace)

    assert response.status_code == 200
    assert response.data["reply"] == "All done."
    assert ANSWER_INPUT not in metered()
    assert "Could not read the token usage" in caplog.text


def test_the_selector_is_metered_even_when_its_reply_makes_no_sense(workspace, openai):
    openai.expect(selection(categories="not json at all"), answer(tokens=usage(1, 1)))

    chat(workspace)

    # The tokens were spent whether or not the reply could be used.
    assert metered()[SELECTOR_INPUT] == Decimal("10")
    assert metered()[SELECTOR_OUTPUT] == Decimal("5")


def test_every_round_of_one_answer_is_metered(workspace, openai):
    openai.expect(
        selection(),
        answer(content="", tokens=usage(prompt=50, completion=10), tool_calls=[tool_call()]),
        answer(tokens=usage(prompt=80, completion=6)),
    )

    chat(workspace)

    assert metered()[ANSWER_INPUT] == Decimal("130")
    assert metered()[ANSWER_OUTPUT] == Decimal("16")


# ── asking before spending ───────────────────────────────────────────


def test_a_workspace_over_its_cap_is_refused_before_anything_is_sent(workspace, openai):
    WorkspacePlatformProfile.objects.create(workspace=workspace, monthly_usage_cap_points=Decimal("1"))
    # Two million tokens at a dollar a million: two points against a cap of one.
    agent_views._metering().meter(workspace, ANSWER_INPUT, 2_000_000)

    response = chat(workspace)

    assert response.status_code == 402
    assert response.data["code"] == "usage_cap_reached"
    assert "month" in response.data["detail"]
    # Not the selector call either: over the cap, the request costs nothing.
    assert openai.calls == []


def test_the_cap_is_asked_about_once_and_about_the_model_that_answers(workspace, openai, monkeypatch):
    asked = []
    monkeypatch.setattr(agent_views._metering(), "allowed", lambda ws, meter: asked.append((ws, meter)) or True)
    openai.expect(selection(), answer(tokens=usage(1, 1)))

    chat(workspace)

    assert asked == [(workspace, ANSWER_INPUT)]


def test_nothing_is_refused_or_counted_without_a_workspace(db, openai):
    # The chat endpoint insists on a workspace, but the pieces it is built from
    # are reachable from anywhere, and an unbillable call is made, not blocked.
    assert agent_views._may_spend_on_model(None, ANSWER_MODEL) is True

    client = sys.modules["openai"].OpenAI()
    openai.expect(selection())
    messages = [{"role": "user", "content": "how many orders?"}]

    categories = agent_views._infer_tool_categories_with_llm(messages, client, SELECTOR_MODEL, None)

    assert categories == ["order"]
    assert metered() == {}


def test_a_request_without_a_workspace_is_still_a_bad_request(db, openai):
    response = chat(None)

    assert response.status_code == 400
    assert openai.calls == []


# ── streaming ────────────────────────────────────────────────────────


def test_a_streamed_answer_asks_for_its_tokens_and_counts_them(workspace, openai):
    openai.expect(
        selection(),
        [
            chunk(content="All "),
            chunk(content="done."),
            chunk(tokens=usage(prompt=70, completion=12, cached=20)),
        ],
    )

    response = chat(workspace, stream=True)
    body = b"".join(response.streaming_content).decode()

    assert "All done." in body
    assert openai.calls[-1]["stream_options"] == {"include_usage": True}
    assert metered()[ANSWER_INPUT] == Decimal("50")
    assert metered()[ANSWER_CACHED] == Decimal("20")
    assert metered()[ANSWER_OUTPUT] == Decimal("12")


def test_a_stream_that_reports_no_usage_still_answers(workspace, openai):
    openai.expect(selection(), [chunk(content="All done.")])

    response = chat(workspace, stream=True)
    body = b"".join(response.streaming_content).decode()

    assert "All done." in body
    assert ANSWER_INPUT not in metered()


# ── naming ───────────────────────────────────────────────────────────


def test_meters_are_named_for_the_model_in_lower_case():
    assert agent_views._token_meters("GPT-4o-Mini") == (
        "ai.gpt-4o-mini.input",
        "ai.gpt-4o-mini.input_cached",
        "ai.gpt-4o-mini.output",
    )


# A deployment that installs bfg.core but not bfg.platform has nothing to bill
# with, so the assistant has to run unmetered rather than refuse to import.


def test_a_call_is_allowed_when_there_is_nothing_to_meter_with(monkeypatch):
    monkeypatch.setattr(agent_views, "_metering", lambda: None)

    assert agent_views._may_spend_on_model(object(), "gpt-4o-mini") is True


def test_usage_is_not_recorded_when_there_is_nothing_to_meter_with(monkeypatch):
    monkeypatch.setattr(agent_views, "_metering", lambda: None)

    # It reads nothing off the response and raises nothing: with no metering
    # client there is nowhere to record a call, so the whole thing is a no-op.
    assert agent_views._meter_tokens(object(), "gpt-4o-mini", None) is None

from contextlib import contextmanager

import pytest

from bfg.delivery.extension_signals import (
    consignment_status_update_exclusions,
    excluded_consignment_ids,
)
from bfg.finance.operation_contexts import (
    finance_operation_context,
    finance_operation_contexts,
)


def test_finance_contexts_enter_in_stable_receiver_order():
    events = []

    @contextmanager
    def context(name):
        events.append(f"enter:{name}")
        try:
            yield
        finally:
            events.append(f"exit:{name}")

    def z_receiver(sender, **kwargs):
        return context("z")

    def a_receiver(sender, **kwargs):
        return context("a")

    finance_operation_contexts.connect(z_receiver, weak=False)
    finance_operation_contexts.connect(a_receiver, weak=False)
    try:
        with finance_operation_context(object(), "payment.finalize"):
            events.append("operation")
    finally:
        finance_operation_contexts.disconnect(z_receiver)
        finance_operation_contexts.disconnect(a_receiver)

    assert events == ["enter:a", "enter:z", "operation", "exit:z", "exit:a"]


def test_finance_context_rejects_async_and_invalid_receivers():
    async def async_receiver(sender, **kwargs):
        return None

    with pytest.raises(TypeError, match="must be synchronous"):
        finance_operation_contexts.connect(async_receiver)

    def invalid_receiver(sender, **kwargs):
        return object()

    finance_operation_contexts.connect(invalid_receiver, weak=False)
    try:
        with pytest.raises(TypeError, match="context manager"):
            with finance_operation_context(object(), "refund.prepare"):
                pass
    finally:
        finance_operation_contexts.disconnect(invalid_receiver)


def test_finance_context_cannot_suppress_operation_failure():
    events = []

    class SuppressingContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            events.append((exc_type, str(exc_value)))
            return True

    def receiver(sender, **kwargs):
        return SuppressingContext()

    finance_operation_contexts.connect(receiver, weak=False)
    try:
        with pytest.raises(RuntimeError, match="settlement failed"):
            with finance_operation_context(object(), "payment.finalize"):
                raise RuntimeError("settlement failed")
    finally:
        finance_operation_contexts.disconnect(receiver)

    assert events == [(RuntimeError, "settlement failed")]


def test_delivery_exclusions_are_immutable_scoped_and_strict():
    observed = {}

    def receiver(sender, **kwargs):
        observed.update(kwargs)
        return [2]

    consignment_status_update_exclusions.connect(receiver, weak=False)
    try:
        assert excluded_consignment_ids(
            workspace="workspace", candidate_ids=(1, 2), new_state="PAID",
        ) == {2}
    finally:
        consignment_status_update_exclusions.disconnect(receiver)

    assert observed["candidate_ids"] == (1, 2)

    class QueryLike:
        def __iter__(self):
            raise AssertionError("query-like candidates must not be consumed")

    for malformed in ([1, 2], QueryLike(), (1, object())):
        with pytest.raises(TypeError, match="candidate_ids"):
            excluded_consignment_ids(
                workspace="workspace", candidate_ids=malformed, new_state="PAID",
            )

    def outside(sender, **kwargs):
        return [3]

    consignment_status_update_exclusions.connect(outside, weak=False)
    try:
        with pytest.raises(ValueError, match="outside the candidates"):
            excluded_consignment_ids(
                workspace="workspace", candidate_ids=(1, 2), new_state="PAID",
            )
    finally:
        consignment_status_update_exclusions.disconnect(outside)

    def failed(sender, **kwargs):
        raise RuntimeError("extension callback failed")

    consignment_status_update_exclusions.connect(failed, weak=False)
    try:
        with pytest.raises(RuntimeError, match="extension callback failed"):
            excluded_consignment_ids(
                workspace="workspace", candidate_ids=(1, 2), new_state="PAID",
            )
    finally:
        consignment_status_update_exclusions.disconnect(failed)

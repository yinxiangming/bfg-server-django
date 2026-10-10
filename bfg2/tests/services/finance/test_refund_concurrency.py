"""PostgreSQL regression coverage for refund row-lock ordering."""

import queue
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.db import close_old_connections, connection, transaction

from bfg.common.models import Customer, User, Workspace
from bfg.finance.models import (
    Currency,
    Payment,
    PaymentGateway,
    Refund,
    Transaction,
)
from bfg.finance.services.payment_service import PaymentService


def _backend_pid():
    connection.ensure_connection()
    raw_connection = connection.connection
    if hasattr(raw_connection, "get_backend_pid"):
        return raw_connection.get_backend_pid()
    return raw_connection.info.backend_pid


def _wait_until_lock_wait(pid, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                [pid],
            )
            row = cursor.fetchone()
        if row and row[0] == "Lock":
            return
        time.sleep(0.05)
    raise AssertionError(f"Database backend {pid} did not wait for the held Payment lock")


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Requires PostgreSQL row locks and pg_stat_activity",
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_refund_prepare_and_finalize_lock_payment_before_refund():
    """A queued prepare must not deadlock with finalization or duplicate its ledger row."""
    workspace = Workspace.objects.create(
        name="Refund lock order",
        slug="refund-lock-order",
        is_active=True,
    )
    user = User.objects.create_user(
        username="refund-lock-user",
        email="refund-lock-user@example.test",
        password="x",
    )
    customer = Customer.objects.create(
        workspace=workspace,
        user=user,
        is_active=True,
    )
    currency = Currency.objects.create(
        code="NZD",
        name="New Zealand dollar",
        symbol="$",
    )
    gateway = PaymentGateway.objects.create(
        workspace=workspace,
        name="Refund lock gateway",
        gateway_type="custom",
        config={},
        test_config={},
    )
    payment = Payment.all_objects.create(
        workspace=workspace,
        customer=customer,
        currency=currency,
        gateway=gateway,
        gateway_display_name=gateway.name,
        gateway_type=gateway.gateway_type,
        payment_number="PAY-REFUND-LOCK",
        amount=Decimal("10.00"),
        status="completed",
    )
    refund = Refund.objects.create(
        payment=payment,
        idempotency_key="refund-lock-key",
        amount=Decimal("3.00"),
        reason="Lock order",
        status="processing",
        gateway_refund_id="gateway-refund-lock",
        created_by=user,
    )
    pids = queue.Queue()

    def run(role):
        close_old_connections()
        try:
            pids.put((role, _backend_pid()))
            thread_workspace = Workspace.objects.get(pk=workspace.pk)
            thread_user = User.objects.get(pk=user.pk)
            service = PaymentService(workspace=thread_workspace, user=thread_user)
            if role == "prepare":
                return service.create_refund(
                    Payment.all_objects.get(pk=payment.pk),
                    refund.amount,
                    refund.reason,
                    idempotency_key=refund.idempotency_key,
                )
            return service._finalize_confirmed_refund(
                refund.pk,
                refund.gateway_refund_id,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        with transaction.atomic():
            Payment.all_objects.select_for_update().get(pk=payment.pk)

            prepare_future = pool.submit(run, "prepare")
            prepare_role, prepare_pid = pids.get(timeout=10)
            assert prepare_role == "prepare"
            _wait_until_lock_wait(prepare_pid)

            finalize_future = pool.submit(run, "finalize")
            finalize_role, finalize_pid = pids.get(timeout=10)
            assert finalize_role == "finalize"
            _wait_until_lock_wait(finalize_pid)

        results = [
            prepare_future.result(timeout=30),
            finalize_future.result(timeout=30),
        ]

    assert [item.status for item in results] == ["completed", "completed"]
    refund.refresh_from_db()
    assert refund.status == "completed"
    assert Refund.objects.filter(
        payment=payment,
        idempotency_key="refund-lock-key",
    ).count() == 1
    assert Transaction.objects.filter(
        payment=payment,
        transaction_type="refund",
    ).count() == 1

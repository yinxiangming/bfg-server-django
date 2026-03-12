# -*- coding: utf-8 -*-
"""
Unit tests for WalletService.
"""

import pytest
from decimal import Decimal

from django.contrib.auth import get_user_model
from bfg.common.models import Workspace, Customer
from bfg.finance.models import Wallet, Currency, Transaction
from bfg.finance.exceptions import InsufficientFunds
from bfg.finance.services import WalletService
from bfg.core.exceptions import PermissionDenied

User = get_user_model()


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        name="Test Workspace",
        slug="test-workspace",
    )


@pytest.fixture
def other_workspace(db):
    return Workspace.objects.create(
        name="Other Workspace",
        slug="other-workspace",
    )


@pytest.fixture
def currency(db):
    return Currency.objects.create(
        code="NZD",
        name="New Zealand Dollar",
        symbol="NZ$",
        decimal_places=2,
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def customer(workspace, user):
    return Customer.objects.create(
        workspace=workspace,
        user=user,
        company_name="Test Customer",
    )


@pytest.fixture
def wallet_service(workspace, user):
    return WalletService(workspace=workspace, user=user)


@pytest.mark.django_db
class TestWalletServiceGetOrCreateWallet:
    """Tests for WalletService.get_or_create_wallet."""

    def test_creates_wallet_when_none_exists(self, wallet_service, customer, currency):
        assert Wallet.objects.filter(workspace=wallet_service.workspace, customer=customer).count() == 0
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        assert wallet.workspace_id == wallet_service.workspace.id
        assert wallet.customer_id == customer.id
        assert wallet.currency_id == currency.id
        assert wallet.cash_balance == Decimal("0")
        assert wallet.credit_balance == Decimal("0")
        assert wallet.credit_limit == Decimal("0")

    def test_returns_existing_wallet(self, wallet_service, customer, currency):
        existing = Wallet.objects.create(
            workspace=wallet_service.workspace,
            customer=customer,
            currency=currency,
            cash_balance=Decimal("100.00"),
            credit_balance=Decimal("0"),
            credit_limit=Decimal("0"),
        )
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        assert wallet.id == existing.id
        assert wallet.cash_balance == Decimal("100.00")

    def test_default_currency_nzd(self, wallet_service, customer, currency):
        wallet = wallet_service.get_or_create_wallet(customer)
        assert wallet.currency.code == "NZD"

    def test_default_currency_fallback_when_no_nzd(self, wallet_service, customer, db):
        Currency.objects.create(code="USD", name="US Dollar", symbol="$", decimal_places=2)
        wallet = wallet_service.get_or_create_wallet(customer)
        assert wallet.currency.code == "USD"

    def test_raises_when_no_currency_available(self, wallet_service, customer, db):
        Currency.objects.all().delete()
        with pytest.raises(ValueError, match="No currency available"):
            wallet_service.get_or_create_wallet(customer)

    def test_raises_when_customer_from_different_workspace(
        self, wallet_service, customer, other_workspace, currency, user
    ):
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
        )
        other_customer = Customer.objects.create(
            workspace=other_workspace,
            user=other_user,
            company_name="Other Customer",
        )
        with pytest.raises(PermissionDenied, match="different workspace"):
            wallet_service.get_or_create_wallet(other_customer, currency=currency)


@pytest.mark.django_db
class TestWalletServiceRecordWalletTransaction:
    """Tests for WalletService.record_wallet_transaction."""

    def test_credit_cash_updates_balance(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        txn = wallet_service.record_wallet_transaction(
            wallet,
            amount=Decimal("50.00"),
            balance_type="cash",
            transaction_type="credit",
            source_type="test",
            source_id=1,
            description="Test credit",
            created_by=user,
        )
        assert txn.amount == Decimal("50.00")
        assert txn.balance_type == "cash"
        assert txn.transaction_type == "credit"
        assert txn.tx_status == "completed"
        wallet.refresh_from_db()
        assert wallet.cash_balance == Decimal("50.00")

    def test_debit_cash_updates_balance(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        wallet_service.record_wallet_transaction(
            wallet,
            amount=Decimal("100.00"),
            balance_type="cash",
            transaction_type="credit",
            created_by=user,
        )
        txn = wallet_service.record_wallet_transaction(
            wallet,
            amount=Decimal("-30.00"),
            balance_type="cash",
            transaction_type="debit",
            created_by=user,
        )
        wallet.refresh_from_db()
        assert wallet.cash_balance == Decimal("70.00")
        assert txn.amount == Decimal("-30.00")

    def test_insufficient_cash_raises(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        with pytest.raises(InsufficientFunds, match="Insufficient.*cash"):
            wallet_service.record_wallet_transaction(
                wallet,
                amount=Decimal("-50.00"),
                balance_type="cash",
                transaction_type="debit",
                created_by=user,
            )

    def test_insufficient_credit_raises(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        with pytest.raises(InsufficientFunds, match="Insufficient.*credit"):
            wallet_service.record_wallet_transaction(
                wallet,
                amount=Decimal("-10.00"),
                balance_type="credit",
                transaction_type="debit",
                created_by=user,
            )

    def test_credit_balance_type_updates_credit(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        wallet_service.record_wallet_transaction(
            wallet,
            amount=Decimal("25.00"),
            balance_type="credit",
            transaction_type="reward",
            created_by=user,
        )
        wallet.refresh_from_db()
        assert wallet.credit_balance == Decimal("25.00")
        assert wallet.cash_balance == Decimal("0")

    def test_invalid_balance_type_raises(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        with pytest.raises(ValueError, match="balance_type must be 'cash' or 'credit'"):
            wallet_service.record_wallet_transaction(
                wallet,
                amount=Decimal("10.00"),
                balance_type="invalid",
                transaction_type="credit",
                created_by=user,
            )

    def test_wallet_from_different_workspace_raises(
        self, workspace, other_workspace, customer, currency, user
    ):
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
        )
        other_customer = Customer.objects.create(
            workspace=other_workspace,
            user=other_user,
            company_name="Other",
        )
        wallet_other = Wallet.objects.create(
            workspace=other_workspace,
            customer=other_customer,
            currency=currency,
            cash_balance=Decimal("0"),
            credit_balance=Decimal("0"),
            credit_limit=Decimal("0"),
        )
        svc = WalletService(workspace=workspace, user=user)
        with pytest.raises(PermissionDenied, match="different workspace"):
            svc.record_wallet_transaction(
                wallet_other,
                amount=Decimal("10.00"),
                balance_type="cash",
                transaction_type="credit",
                created_by=user,
            )

    def test_created_by_defaults_to_service_user(self, wallet_service, customer, currency, user):
        wallet = wallet_service.get_or_create_wallet(customer, currency=currency)
        txn = wallet_service.record_wallet_transaction(
            wallet,
            amount=Decimal("5.00"),
            balance_type="cash",
            transaction_type="credit",
        )
        assert txn.created_by_id == user.id

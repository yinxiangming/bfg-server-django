"""
BFG Finance Module Services

Wallet get/create and balance transaction recording.
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from bfg.core.services import BaseService
from bfg.finance.exceptions import InsufficientFunds
from bfg.finance.models import Wallet, Currency, Transaction
from bfg.common.models import Customer


class WalletService(BaseService):
    """
    Wallet lifecycle and balance operations.
    Use this instead of direct Wallet/Transaction model access for credits/debits.
    """

    def get_or_create_wallet(
        self,
        customer: Customer,
        currency=None,
    ) -> Wallet:
        """
        Get or create Wallet for (workspace, customer).
        Default currency: NZD or first available.
        """
        self.validate_workspace_access(customer)
        if currency is None:
            currency = (
                Currency.objects.filter(code='NZD').first()
                or Currency.objects.first()
            )
        if not currency:
            raise ValueError("No currency available for wallet creation")
        wallet, _ = Wallet.objects.get_or_create(
            workspace=self.workspace,
            customer=customer,
            defaults={
                'cash_balance': Decimal('0'),
                'credit_balance': Decimal('0'),
                'credit_limit': Decimal('0'),
                'currency': currency,
            },
        )
        return wallet

    @transaction.atomic
    def record_wallet_transaction(
        self,
        wallet: Wallet,
        amount: Decimal,
        balance_type: str,
        transaction_type: str,
        source_type: str = '',
        source_id: int = None,
        description: str = '',
        created_by=None,
    ) -> Transaction:
        """
        Create a wallet Transaction and update wallet balance.
        amount: positive for credit, negative for debit.
        balance_type: 'cash' or 'credit'.
        """
        self.validate_workspace_access(wallet)
        if balance_type not in ('cash', 'credit'):
            raise ValueError("balance_type must be 'cash' or 'credit'")
        if amount < 0:
            balance = wallet.cash_balance if balance_type == 'cash' else wallet.credit_balance
            if balance + amount < 0:
                raise InsufficientFunds(
                    f"Insufficient {balance_type} balance: have {balance}, need {-amount}"
                )
        created_by = created_by or getattr(self, 'user', None)
        txn = Transaction.objects.create(
            workspace=self.workspace,
            customer=wallet.customer,
            transaction_type=transaction_type,
            amount=amount,
            currency=wallet.currency,
            wallet=wallet,
            balance_type=balance_type,
            tx_status='completed',
            source_type=source_type or '',
            source_id=source_id,
            description=description or f'{transaction_type}',
            created_by=created_by,
        )
        if balance_type == 'cash':
            wallet.cash_balance += amount
            wallet.save(update_fields=['cash_balance', 'updated_at'])
        else:
            wallet.credit_balance += amount
            wallet.save(update_fields=['credit_balance', 'updated_at'])
        return txn

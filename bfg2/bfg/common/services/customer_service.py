"""
BFG Common Module Services

Customer management service
"""

from typing import Union, Optional, Any, Dict
from decimal import Decimal
from django.db import transaction
from bfg.core.services import BaseService
from bfg.common.exceptions import CustomerNotFound
from bfg.common.models import Customer, User, Workspace


class CustomerService(BaseService):
    """
    Customer management service
    
    Handles customer profile creation and management
    """
    
    @transaction.atomic
    def create_customer(
        self, 
        user: Union[User, int], 
        workspace: Workspace, 
        **customer_data: Any
    ) -> Customer:
        """
        Create customer profile for user
        
        Args:
            user: User instance or user ID
            workspace: Workspace instance
            **customer_data: Additional customer fields
            
        Returns:
            Customer: Created customer instance
        """
        if isinstance(user, int):
            user = User.objects.get(id=user)
        
        # Check if customer already exists
        existing = Customer.objects.filter(
            workspace=workspace,
            user=user
        ).first()
        
        if existing:
            return existing
        
        # Create customer
        customer = Customer.objects.create(
            workspace=workspace,
            user=user,
            company_name=customer_data.get('company_name', ''),
            tax_number=customer_data.get('tax_number', ''),
            is_active=customer_data.get('is_active', True),
        )
        
        # Emit customer created event
        self.emit_event('customer.created', {'customer': customer})
        
        return customer
    
    def get_customer(self, customer_id: int) -> Customer:
        """
        Get customer by ID
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Customer: Customer instance
            
        Raises:
            CustomerNotFound: If customer doesn't exist
        """
        try:
            customer = Customer.objects.select_related('user', 'workspace').get(
                id=customer_id
            )
            self.validate_workspace_access(customer)
            return customer
        except Customer.DoesNotExist:
            raise CustomerNotFound(f"Customer with ID {customer_id} not found")
    
    def get_customer_by_user(self, user: User, workspace: Workspace) -> Optional[Customer]:
        """
        Get customer profile for user in workspace
        
        Args:
            user: User instance
            workspace: Workspace instance
            
        Returns:
            Customer or None: Customer instance if exists
        """
        return Customer.objects.filter(
            workspace=workspace,
            user=user,
            is_active=True
        ).first()
    
    def update_customer(self, customer: Customer, **kwargs: Any) -> Customer:
        """
        Update customer information
        
        Args:
            customer: Customer instance
            **kwargs: Fields to update
            
        Returns:
            Customer: Updated customer instance
        """
        self.validate_workspace_access(customer)
        
        for key, value in kwargs.items():
            if hasattr(customer, key) and key not in ['id', 'workspace', 'user']:
                setattr(customer, key, value)
        
        customer.save()
        return customer
    
    def deactivate_customer(self, customer: Customer) -> Customer:
        """
        Deactivate customer
        
        Args:
            customer: Customer instance
            
        Returns:
            Customer: Updated customer instance
        """
        self.validate_workspace_access(customer)
        
        customer.is_active = False
        customer.save()
        
        return customer
    
    def get_wallet(self, customer: Customer) -> Dict[str, Any]:
        """
        Get customer wallet information
        
        Args:
            customer: Customer instance
            
        Returns:
            dict: Wallet information with balance, credit_limit, and currency
        """
        self.validate_workspace_access(customer)
        
        # Check if finance module is available
        try:
            from bfg.finance.models import Wallet, Currency
        except ImportError:
            # Fallback to customer balance if finance module not available
            return {
                'balance': float(customer.balance or 0),
                'credit_limit': float(customer.credit_limit or 0),
                'currency': 'NZD'
            }
        
        # Get or create wallet for customer
        wallet, _ = Wallet.objects.get_or_create(
            customer=customer,
            defaults={
                'balance': customer.balance or Decimal('0'),
                'credit_limit': customer.credit_limit or Decimal('0'),
                'currency': Currency.objects.filter(code='NZD').first() or Currency.objects.first()
            }
        )
        
        return {
            'balance': float(wallet.balance),
            'credit_limit': float(wallet.credit_limit),
            'currency': wallet.currency.code if wallet.currency else 'NZD'
        }
    
    @transaction.atomic
    def topup_wallet(
        self, 
        customer: Customer, 
        amount: Union[float, str, Decimal], 
        note: str = 'Manual top-up by admin',
        user: Optional[User] = None
    ) -> Dict[str, Any]:
        """
        Top up customer wallet
        
        Args:
            customer: Customer instance
            amount: Amount to top up
            note: Transaction note
            user: User performing the top-up (for transaction record)
            
        Returns:
            dict: Updated wallet information
            
        Raises:
            ValueError: If amount is invalid
        """
        self.validate_workspace_access(customer)
        
        # Validate amount
        try:
            amount_decimal = Decimal(str(amount))
        except (ValueError, TypeError):
            raise ValueError('Invalid amount')
        
        if amount_decimal <= 0:
            raise ValueError('Amount must be greater than 0')
        
        # Check if finance module is available
        try:
            from bfg.finance.models import Wallet, Currency, Transaction
        except ImportError:
            # Fallback: update customer balance directly
            customer.balance = (customer.balance or Decimal('0')) + amount_decimal
            customer.save(update_fields=['balance'])
            return {
                'balance': float(customer.balance),
                'credit_limit': float(customer.credit_limit or 0),
                'currency': 'NZD'
            }
        
        # Get or create wallet
        wallet, created = Wallet.objects.get_or_create(
            customer=customer,
            defaults={
                'balance': customer.balance or Decimal('0'),
                'credit_limit': customer.credit_limit or Decimal('0'),
                'currency': Currency.objects.filter(code='NZD').first() or Currency.objects.first()
            }
        )
        
        # Update wallet balance
        wallet.balance += amount_decimal
        wallet.save()
        
        # Create transaction record
        try:
            # Get the user performing the top-up
            topup_user = user or self.user
            
            # Build notes with operator information
            notes_parts = [note] if note else []
            if topup_user:
                user_display = topup_user.get_full_name() if hasattr(topup_user, 'get_full_name') and topup_user.get_full_name() else topup_user.username
                notes_parts.append(f'Operated by: {user_display}')
            
            transaction_notes = '\n'.join(notes_parts)
            
            Transaction.objects.create(
                workspace=self.workspace,
                customer=customer,
                amount=amount_decimal,
                transaction_type='credit',
                currency=wallet.currency,
                description=note,
                notes=transaction_notes,
                created_by=topup_user
            )
        except Exception:
            # If transaction creation fails, just continue
            pass
        
        return {
            'balance': float(wallet.balance),
            'credit_limit': float(wallet.credit_limit),
            'currency': wallet.currency.code if wallet.currency else 'NZD'
        }
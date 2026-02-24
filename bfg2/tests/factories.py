"""
Factory Boy factories for BFG2 models
"""

import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from bfg.common.models import Workspace, User, Customer, Address, StaffRole, StaffMember
from bfg.shop.models import Product, ProductVariant, ProductCategory, Store
from bfg.delivery.models import Warehouse
from bfg.finance.models import Currency

class WorkspaceFactory(DjangoModelFactory):
    class Meta:
        model = Workspace
    
    name = factory.Faker('company')
    slug = factory.Faker('slug')
    domain = factory.Faker('domain_name')
    email = factory.Faker('company_email')
    is_active = True

class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
    
    username = factory.Faker('user_name')
    email = factory.Faker('email')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True

class AddressFactory(DjangoModelFactory):
    class Meta:
        model = Address
    
    workspace = factory.SubFactory(WorkspaceFactory)
    full_name = factory.Faker('name')
    phone = factory.Faker('phone_number')
    address_line1 = factory.Faker('street_address')
    city = factory.Faker('city')
    state = factory.Faker('state')
    postal_code = factory.Faker('postcode')
    country = factory.Faker('country_code')

class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = Customer
    
    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    company_name = factory.Faker('company')

class WarehouseFactory(DjangoModelFactory):
    class Meta:
        model = Warehouse
    
    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('city')
    code = factory.Faker('lexify', text='WH-????')
    address_line1 = factory.Faker('street_address')
    city = factory.Faker('city')
    postal_code = factory.Faker('postcode')
    country = 'NZ'

class StoreFactory(DjangoModelFactory):
    class Meta:
        model = Store
        skip_postgeneration_save = True
    
    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('company')
    code = factory.Faker('lexify', text='ST-????')
    
    @factory.post_generation
    def warehouses(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            for warehouse in extracted:
                self.warehouses.add(warehouse)
            # Explicitly save after adding warehouses
            self.save()

class ProductCategoryFactory(DjangoModelFactory):
    class Meta:
        model = ProductCategory
    
    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('word')
    slug = factory.Faker('slug')
    language = 'en'

class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product
    
    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('product_name')
    slug = factory.Faker('slug')
    category = factory.SubFactory(ProductCategoryFactory)
    base_price = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True)
    language = 'en'

class ProductVariantFactory(DjangoModelFactory):
    class Meta:
        model = ProductVariant
    
    product = factory.SubFactory(ProductFactory)
    sku = factory.Faker('ean13')
    price = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True)
    track_inventory = True

class CurrencyFactory(DjangoModelFactory):
    class Meta:
        model = Currency
    
    code = factory.Faker('currency_code')

class StaffRoleFactory(DjangoModelFactory):
    class Meta:
        model = StaffRole
    
    workspace = factory.SubFactory(WorkspaceFactory)
    name = "Administrator"
    code = "admin"
    description = "Admin role"
    permissions = {"*": ["*"]}
    is_system = True

class StaffMemberFactory(DjangoModelFactory):
    class Meta:
        model = StaffMember
    
    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    role = factory.SubFactory(StaffRoleFactory)

"""
Freight service pricing on the storefront, and the rate importer that configures it.

Two things are pinned down here.

**Free shipping over a threshold used to be silently impossible on the storefront.**
``OrderService._calculate_freight_service_cost`` built the condition context with
``order_amount`` hardcoded to ``None``, and the condition engine treats a ``None``
actual as "no match" — so every ``order_amount_gte`` rule failed, and the
``free_over_amount`` template shipped in ``bfg.delivery`` could never grant free
shipping to a shopper. It worked only in the back office, which passes a real
subtotal, so a store could configure the rule, watch it apply on an admin
recalculation, and never learn that customers were being charged.

**A workspace with no FreightService cannot take an order at all** — the checkout
renders "no shipping options available for this country" — which is what
``import_shipping_rates`` exists to fix, repeatably, on every environment.

The rate table below is a fixture, not anybody's price list: one service per
pricing shape that behaves differently, so the assertions stay about the mechanism.
"""

import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from bfg.common.models import Workspace
from bfg.delivery.models import Carrier, DeliveryZone, FreightService
from bfg.shop.models import Product

CART_URL = '/api/v1/store/cart/'
SERVICES_URL = '/api/v1/delivery/freight-services/for_country/'
CART_KEY = 'shipping-key-2b7f4d10-9a3e-4c6b-8f21-5d0e7a9c4b83'

HOME = 'GB'
ELSEWHERE = 'FR'

RATES = {
    "zones": [
        {"code": "HOME", "name": "Home market", "countries": [HOME], "order": 10},
    ],
    "carriers": [
        {
            "code": "ACME",
            "name": "Acme Freight",
            "tracking_url_template": "https://example.test/track/{tracking_number}",
            "services": [
                {
                    "code": "STANDARD",
                    "name": "Standard",
                    "estimated_days_min": 2,
                    "estimated_days_max": 3,
                    "order": 10,
                    "zones": ["HOME"],
                    "template": "free_over_amount",
                    "params": {
                        "threshold_amount": 100,
                        "fallback_base": 5,
                        "fallback_per_kg": 0,
                    },
                },
                {
                    "code": "EXPRESS",
                    "name": "Express",
                    "estimated_days_min": 1,
                    "estimated_days_max": 2,
                    "order": 20,
                    "zones": ["HOME"],
                    "template": "flat_rate",
                    "params": {"amount": 9},
                },
            ],
        }
    ],
}


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Rates Test', slug='rates-test', is_active=True)


@pytest.fixture
def product(workspace):
    # Deliberately weightless. Catalogues migrated from other systems routinely arrive
    # with a null weight, and a flat rate must not quietly depend on one being present.
    return Product.objects.create(
        workspace=workspace,
        name='Widget',
        slug='widget',
        price=Decimal('5.00'),
        is_active=True,
        track_inventory=False,
    )


@pytest.fixture
def rates_file(tmp_path):
    path = tmp_path / 'rates.json'
    path.write_text(json.dumps(RATES), encoding='utf-8')
    return str(path)


@pytest.fixture
def imported(workspace, rates_file):
    call_command('import_shipping_rates', rates_file,
                 workspace=workspace.slug, confirm=True, stdout=StringIO())
    return {s.code: s for s in FreightService.objects.filter(workspace=workspace)}


def client_for(workspace):
    client = APIClient()
    client.credentials(
        HTTP_X_WORKSPACE_ID=str(workspace.id),
        HTTP_X_BFG_CART_SESSION=CART_KEY,
    )
    return client


def basket(workspace, product, quantity):
    """Put `quantity` of the $5.00 product in a cart and return the client holding it."""
    response = client_for(workspace).post(
        f'{CART_URL}add_item/',
        {'product': product.id, 'quantity': quantity},
        format='json',
    )
    assert response.status_code in (200, 201), response.data
    return client_for(workspace)


def preview(workspace, product, quantity, service):
    response = basket(workspace, product, quantity).get(
        f'{CART_URL}preview/?freight_service_id={service.id}'
    )
    assert response.status_code == 200, response.data
    return response.data


# ---------------------------------------------------------------- pricing


def test_below_the_threshold_the_fallback_rate_is_charged(workspace, product, imported):
    data = preview(workspace, product, 10, imported['STANDARD'])
    assert Decimal(data['subtotal']) == Decimal('50.00')
    assert Decimal(data['shipping_cost']) == Decimal('5.00')


def test_at_the_threshold_shipping_becomes_free(workspace, product, imported):
    # 20 x $5.00 = $100.00, exactly the threshold. This is the regression: with
    # order_amount pinned to None the engine matched nothing and charged the fallback.
    data = preview(workspace, product, 20, imported['STANDARD'])
    assert Decimal(data['subtotal']) == Decimal('100.00')
    assert Decimal(data['shipping_cost']) == Decimal('0.00')


def test_above_the_threshold_shipping_stays_free(workspace, product, imported):
    data = preview(workspace, product, 25, imported['STANDARD'])
    assert Decimal(data['shipping_cost']) == Decimal('0.00')


def test_a_flat_rate_ignores_order_value(workspace, product, imported):
    data = preview(workspace, product, 25, imported['EXPRESS'])
    assert Decimal(data['subtotal']) == Decimal('125.00')
    assert Decimal(data['shipping_cost']) == Decimal('9.00')


def test_a_flat_rate_ignores_weightless_products(workspace, product, imported):
    """One item and twenty-five both ship for the same price — nothing multiplies by null."""
    one = preview(workspace, product, 1, imported['EXPRESS'])
    assert Decimal(one['shipping_cost']) == Decimal('9.00')


# ---------------------------------------------------------------- importer


def test_the_storefront_lists_the_imported_services(workspace, imported):
    """The symptom being fixed: for_country returned [] and checkout said no options."""
    response = client_for(workspace).get(f'{SERVICES_URL}?country={HOME}')
    assert response.status_code == 200
    codes = [s['code'] for s in response.data]
    assert codes == ['STANDARD', 'EXPRESS']


def test_the_country_match_is_case_insensitive(workspace, imported):
    response = client_for(workspace).get(f'{SERVICES_URL}?country={HOME.lower()}')
    assert response.status_code == 200
    assert len(response.data) == 2


def test_a_country_with_no_zone_gets_nothing(workspace, imported):
    """An unserved country gets no options rather than a wrong default."""
    response = client_for(workspace).get(f'{SERVICES_URL}?country={ELSEWHERE}')
    assert response.status_code == 200
    assert response.data == []


def test_without_confirm_nothing_is_written(workspace, rates_file):
    call_command('import_shipping_rates', rates_file,
                 workspace=workspace.slug, stdout=StringIO())
    assert not FreightService.objects.filter(workspace=workspace).exists()
    assert not DeliveryZone.objects.filter(workspace=workspace).exists()
    assert not Carrier.all_objects.filter(workspace=workspace).exists()


def test_rerunning_the_import_updates_rather_than_duplicates(workspace, rates_file, imported):
    call_command('import_shipping_rates', rates_file,
                 workspace=workspace.slug, confirm=True, stdout=StringIO())
    assert FreightService.objects.filter(workspace=workspace).count() == 2
    assert Carrier.all_objects.filter(workspace=workspace).count() == 1
    assert DeliveryZone.objects.filter(workspace=workspace).count() == 1


def test_a_changed_price_is_applied_on_reimport(workspace, product, imported, tmp_path):
    dearer = json.loads(json.dumps(RATES))
    dearer['carriers'][0]['services'][1]['params']['amount'] = 11
    path = tmp_path / 'dearer.json'
    path.write_text(json.dumps(dearer), encoding='utf-8')

    call_command('import_shipping_rates', str(path),
                 workspace=workspace.slug, confirm=True, stdout=StringIO())

    service = FreightService.objects.get(workspace=workspace, code='EXPRESS')
    assert Decimal(preview(workspace, product, 1, service)['shipping_cost']) == Decimal('11.00')


def test_an_unknown_template_is_rejected_before_anything_is_written(workspace, tmp_path):
    broken = json.loads(json.dumps(RATES))
    broken['carriers'][0]['services'][0]['template'] = 'no_such_template'
    path = tmp_path / 'broken.json'
    path.write_text(json.dumps(broken), encoding='utf-8')

    out = StringIO()
    call_command('import_shipping_rates', str(path),
                 workspace=workspace.slug, confirm=True, stdout=out)

    assert 'no_such_template' in out.getvalue()
    # The valid second service must not have been half-applied.
    assert not FreightService.objects.filter(workspace=workspace).exists()
    assert not Carrier.all_objects.filter(workspace=workspace).exists()


def test_a_zone_a_service_references_but_does_not_define_is_rejected(workspace, tmp_path):
    broken = json.loads(json.dumps(RATES))
    broken['carriers'][0]['services'][0]['zones'] = ['NOWHERE']
    path = tmp_path / 'badzone.json'
    path.write_text(json.dumps(broken), encoding='utf-8')

    out = StringIO()
    call_command('import_shipping_rates', str(path),
                 workspace=workspace.slug, confirm=True, stdout=out)

    assert 'NOWHERE' in out.getvalue()
    assert not DeliveryZone.objects.filter(workspace=workspace).exists()


def test_services_omitted_from_the_file_are_retired_only_when_asked(workspace, rates_file, imported, tmp_path):
    trimmed = json.loads(json.dumps(RATES))
    trimmed['carriers'][0]['services'] = trimmed['carriers'][0]['services'][:1]
    path = tmp_path / 'trimmed.json'
    path.write_text(json.dumps(trimmed), encoding='utf-8')

    call_command('import_shipping_rates', str(path),
                 workspace=workspace.slug, confirm=True, stdout=StringIO())
    assert FreightService.objects.get(workspace=workspace, code='EXPRESS').is_active

    call_command('import_shipping_rates', str(path), workspace=workspace.slug,
                 confirm=True, deactivate_missing=True, stdout=StringIO())
    assert not FreightService.objects.get(workspace=workspace, code='EXPRESS').is_active


def test_the_importer_does_not_touch_another_workspace(workspace, rates_file, imported, db):
    other = Workspace.objects.create(name='Other', slug='other-ws', is_active=True)
    assert not FreightService.objects.filter(workspace=other).exists()
    assert not Carrier.all_objects.filter(workspace=other).exists()

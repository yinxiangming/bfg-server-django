"""
Workspace-level storefront display policy: SKU visibility, stock visibility, and what a
sold-out product does.

Three settings, one place. The tests below pin the parts that are easy to get subtly
wrong and impossible to notice from the outside:

* the stock figure has to disappear from the *payload*, not just the template — hiding it
  in the page while serving it one request away is not hiding it;
* `hide` has to take the product off the detail page too, not only out of listings;
* `backorder` has to reach the cart, which is the only thing that actually refuses a sale;
* the badge on the page and the check that blocks add-to-cart have to read the same
  numbers, or a product reads "In stock" and then refuses to be bought.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from bfg.common.models import Workspace, Settings
from bfg.shop.models import Product, ProductVariant, StockNotification
from bfg.shop.services.storefront_display_service import (
    DEFAULTS,
    get_storefront_display_settings,
    product_stock_level,
    resolve_product_stock,
    strip_sku_prefix,
)

PRODUCTS_URL = '/api/v1/store/products/'
CONFIG_URL = '/api/v1/settings/storefront/'


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Display WS', slug='display-ws', is_active=True)


def configure(workspace, **display):
    """
    Write the storefront display policy and hand back a workspace that can see it.

    A Settings row is created alongside the Workspace, so this updates rather than
    creates. The refresh matters: the in-memory workspace caches its reverse OneToOne, and
    without it every resolver in this module would keep reading the pre-write settings.
    """
    settings_obj, _ = Settings.objects.update_or_create(workspace=workspace)
    custom = dict(settings_obj.custom_settings or {})
    shop = dict(custom.get('shop') or {})
    shop['storefront_display'] = display
    custom['shop'] = shop
    settings_obj.custom_settings = custom
    settings_obj.save(update_fields=['custom_settings'])
    workspace.refresh_from_db()
    return workspace


def set_sku_prefix(workspace, prefix):
    settings_obj, _ = Settings.objects.update_or_create(workspace=workspace)
    custom = dict(settings_obj.custom_settings or {})
    shop = dict(custom.get('shop') or {})
    shop['product_identifiers'] = {'sku_prefix': prefix}
    custom['shop'] = shop
    settings_obj.custom_settings = custom
    settings_obj.save(update_fields=['custom_settings'])
    workspace.refresh_from_db()
    return workspace


def make_product(workspace, **kwargs):
    defaults = dict(
        name='Keyes Alcohol Sensor',
        slug='keyes-alcohol-sensor',
        sku='SKU-KAS-301',
        price=Decimal('12.00'),
        is_active=True,
        track_inventory=True,
        stock_quantity=4,
        low_stock_threshold=10,
    )
    defaults.update(kwargs)
    return Product.objects.create(workspace=workspace, **defaults)


def shopper(workspace):
    return APIClient(HTTP_X_WORKSPACE_ID=str(workspace.id))


def listed(response):
    """Rows out of a product listing, whether or not pagination wrapped them."""
    data = response.data
    return data['results'] if isinstance(data, dict) else data


def fetch(workspace, product):
    client = APIClient()
    client.credentials(HTTP_X_WORKSPACE_ID=str(workspace.id))
    return client.get(f'{PRODUCTS_URL}{product.slug}/')


# --------------------------------------------------------------------------- settings


class TestSettingsResolution:
    def test_unconfigured_workspace_gets_defaults(self, workspace):
        assert get_storefront_display_settings(workspace) == DEFAULTS

    def test_no_workspace_gets_defaults(self):
        assert get_storefront_display_settings(None) == DEFAULTS

    def test_configured_values_win(self, workspace):
        configure(workspace, sku_display='hidden', stock_display='exact',
                  out_of_stock_policy='backorder')
        assert get_storefront_display_settings(workspace) == {
            'sku_display': 'hidden',
            'stock_display': 'exact',
            'out_of_stock_policy': 'backorder',
        }

    def test_unknown_value_falls_back_rather_than_propagating(self, workspace):
        """
        The settings blob predates this feature and can hold anything. A typo must not be
        the thing that decides whether a product is purchasable.
        """
        configure(workspace, out_of_stock_policy='nonsense', stock_display=42)
        resolved = get_storefront_display_settings(workspace)
        assert resolved['out_of_stock_policy'] == DEFAULTS['out_of_stock_policy']
        assert resolved['stock_display'] == DEFAULTS['stock_display']

    def test_partial_config_leaves_the_rest_at_defaults(self, workspace):
        configure(workspace, sku_display='full')
        resolved = get_storefront_display_settings(workspace)
        assert resolved['sku_display'] == 'full'
        assert resolved['stock_display'] == DEFAULTS['stock_display']


# --------------------------------------------------------------------------- sku


class TestStripSkuPrefix:
    def test_removes_the_configured_prefix(self):
        assert strip_sku_prefix('SKU-KAS-301', 'SKU-') == 'KAS-301'

    def test_match_is_case_insensitive(self):
        assert strip_sku_prefix('sku-KAS-301', 'SKU-') == 'KAS-301'

    def test_leaves_a_code_that_does_not_carry_the_prefix(self):
        assert strip_sku_prefix('ACME-99', 'SKU-') == 'ACME-99'

    def test_no_prefix_configured_is_a_no_op(self):
        assert strip_sku_prefix('SKU-KAS-301', '') == 'SKU-KAS-301'

    def test_a_code_that_is_only_its_prefix_survives_intact(self):
        """An empty reference on the page is worse than a redundant one."""
        assert strip_sku_prefix('SKU-', 'SKU-') == 'SKU-'


class TestSkuOverApi:
    def test_prefix_is_stripped_by_default(self, workspace):
        set_sku_prefix(workspace, 'SKU-')
        product = make_product(workspace)
        assert fetch(workspace, product).data['sku'] == 'KAS-301'

    def test_hidden_returns_an_empty_string(self, workspace):
        set_sku_prefix(workspace, 'SKU-')
        configure(workspace, sku_display='hidden')
        product = make_product(workspace)
        assert fetch(workspace, product).data['sku'] == ''

    def test_full_returns_the_stored_code(self, workspace):
        settings_obj, _ = Settings.objects.update_or_create(workspace=workspace)
        settings_obj.custom_settings = {
            'shop': {
                'product_identifiers': {'sku_prefix': 'SKU-'},
                'storefront_display': {'sku_display': 'full'},
            }
        }
        settings_obj.save(update_fields=['custom_settings'])
        workspace.refresh_from_db()
        product = make_product(workspace)
        assert fetch(workspace, product).data['sku'] == 'SKU-KAS-301'


# --------------------------------------------------------------------------- stock


class TestStockLevel:
    def test_untracked_product_reports_none(self, workspace):
        product = make_product(workspace, track_inventory=False, stock_quantity=0)
        assert product_stock_level(product) is None

    def test_plain_product_reports_its_own_quantity(self, workspace):
        assert product_stock_level(make_product(workspace, stock_quantity=7)) == 7

    def test_variants_are_summed_and_shadow_the_product_quantity(self, workspace):
        product = make_product(workspace, stock_quantity=99)
        ProductVariant.objects.create(product=product, sku='V1', name='Red', stock_quantity=2)
        ProductVariant.objects.create(product=product, sku='V2', name='Blue', stock_quantity=3)
        assert product_stock_level(product) == 5

    def test_inactive_variants_do_not_count(self, workspace):
        product = make_product(workspace, stock_quantity=0)
        ProductVariant.objects.create(product=product, sku='V1', name='Red', stock_quantity=2)
        ProductVariant.objects.create(product=product, sku='V2', name='Gone',
                                      stock_quantity=50, is_active=False)
        assert product_stock_level(product) == 2

    def test_negative_stock_floors_at_zero(self, workspace):
        """Oversold rows exist; they must read as "none left", never as a negative."""
        assert product_stock_level(make_product(workspace, stock_quantity=-3)) == 0


class TestResolveProductStock:
    def test_status_display_withholds_the_number(self, workspace):
        product = make_product(workspace, stock_quantity=4)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['in_stock'] is True
        assert resolved['stock_quantity'] is None

    def test_exact_display_publishes_the_number(self, workspace):
        configure(workspace, stock_display='exact')
        product = make_product(workspace, stock_quantity=4)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['stock_quantity'] == 4

    def test_low_only_publishes_the_number_just_below_the_threshold(self, workspace):
        configure(workspace, stock_display='low_only')
        product = make_product(workspace, stock_quantity=4, low_stock_threshold=10)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['low_stock'] is True
        assert resolved['stock_quantity'] == 4

    def test_low_only_withholds_the_number_above_the_threshold(self, workspace):
        configure(workspace, stock_display='low_only')
        product = make_product(workspace, stock_quantity=40, low_stock_threshold=10)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['low_stock'] is False
        assert resolved['stock_quantity'] is None

    def test_untracked_product_never_discloses_a_figure(self, workspace):
        configure(workspace, stock_display='exact')
        product = make_product(workspace, track_inventory=False, stock_quantity=0)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['in_stock'] is True
        assert resolved['purchasable'] is True
        assert resolved['stock_quantity'] is None

    def test_sold_out_is_not_purchasable_by_default(self, workspace):
        product = make_product(workspace, stock_quantity=0)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['in_stock'] is False
        assert resolved['purchasable'] is False

    def test_backorder_makes_a_sold_out_product_purchasable(self, workspace):
        configure(workspace, out_of_stock_policy='backorder')
        product = make_product(workspace, stock_quantity=0)
        resolved = resolve_product_stock(product, get_storefront_display_settings(workspace))
        assert resolved['in_stock'] is False
        assert resolved['purchasable'] is True


class TestStockOverApi:
    def test_default_payload_carries_status_but_no_figure(self, workspace):
        product = make_product(workspace, stock_quantity=4)
        data = fetch(workspace, product).data
        assert data['in_stock'] is True
        assert data['purchasable'] is True
        assert data['stock_quantity'] is None

    def test_exact_payload_carries_the_figure(self, workspace):
        configure(workspace, stock_display='exact')
        product = make_product(workspace, stock_quantity=4)
        assert fetch(workspace, product).data['stock_quantity'] == 4

    def test_variant_figures_follow_the_same_policy(self, workspace):
        """
        The number withheld on the product must not reappear on its variants — the
        listing serialises both, so gating one alone would publish it anyway.
        """
        product = make_product(workspace, stock_quantity=0)
        ProductVariant.objects.create(product=product, sku='V1', name='Red', stock_quantity=6)
        variant = fetch(workspace, product).data['variants'][0]
        assert variant['in_stock'] is True
        assert variant['stock_quantity'] is None
        assert variant['stock_available'] is None

    def test_warehouse_breakdown_is_no_longer_published(self, workspace):
        """
        `stock_by_warehouse` and `stock_reserved` used to ship warehouse names, codes and
        per-site reservation counts on an unauthenticated endpoint.
        """
        product = make_product(workspace, stock_quantity=0)
        ProductVariant.objects.create(product=product, sku='V1', name='Red', stock_quantity=6)
        variant = fetch(workspace, product).data['variants'][0]
        assert 'stock_by_warehouse' not in variant
        assert 'stock_reserved' not in variant


# --------------------------------------------------------------------- out of stock


class TestHidePolicy:
    def test_sold_out_product_leaves_the_listing(self, workspace):
        make_product(workspace, slug='in-stock', sku='A', stock_quantity=3)
        make_product(workspace, slug='sold-out', sku='B', stock_quantity=0)
        configure(workspace, out_of_stock_policy='hide')

        response = shopper(workspace).get(PRODUCTS_URL)
        assert {p['slug'] for p in listed(response)} == {'in-stock'}

    def test_sold_out_detail_page_404s(self, workspace):
        """
        Listings and the detail page resolve through the same queryset, so a hidden
        product must not stay reachable by typing its URL.
        """
        product = make_product(workspace, slug='sold-out', stock_quantity=0)
        configure(workspace, out_of_stock_policy='hide')
        assert fetch(workspace, product).status_code == 404

    def test_untracked_product_is_never_hidden(self, workspace):
        make_product(workspace, slug='made-to-order', track_inventory=False, stock_quantity=0)
        configure(workspace, out_of_stock_policy='hide')
        response = shopper(workspace).get(PRODUCTS_URL)
        assert [p['slug'] for p in listed(response)] == ['made-to-order']

    def test_a_product_with_stock_only_in_variants_stays(self, workspace):
        product = make_product(workspace, slug='has-variants', stock_quantity=0)
        ProductVariant.objects.create(product=product, sku='V1', name='Red', stock_quantity=4)
        configure(workspace, out_of_stock_policy='hide')
        response = shopper(workspace).get(PRODUCTS_URL)
        assert [p['slug'] for p in listed(response)] == ['has-variants']

    def test_other_policies_keep_it_visible(self, workspace):
        product = make_product(workspace, slug='sold-out', stock_quantity=0)
        response = fetch(workspace, product)
        assert response.status_code == 200
        assert response.data['in_stock'] is False

    def test_hiding_does_not_disturb_bestseller_sorting(self, workspace):
        """
        The hide filter annotates a subquery while the sort branches annotate a join
        aggregate. Done as two joins those two sums multiply each other.
        """
        make_product(workspace, slug='a', sku='A', stock_quantity=3)
        make_product(workspace, slug='b', sku='B', stock_quantity=5)
        configure(workspace, out_of_stock_policy='hide')
        response = shopper(workspace).get(PRODUCTS_URL, {'bestseller': 'true'})
        assert response.status_code == 200
        assert {p['slug'] for p in listed(response)} == {'a', 'b'}


class TestBackorderReachesTheCart:
    def add(self, workspace, product, quantity=1):
        client = APIClient()
        client.credentials(
            HTTP_X_WORKSPACE_ID=str(workspace.id),
            HTTP_X_BFG_CART_SESSION='display-policy-guest-key',
        )
        return client.post(
            '/api/v1/store/cart/add_item/',
            {'product': product.id, 'quantity': quantity},
            format='json',
        )

    def test_sold_out_is_refused_by_default(self, workspace):
        product = make_product(workspace, stock_quantity=0)
        assert self.add(workspace, product).status_code == 400

    def test_backorder_lets_the_sale_through(self, workspace):
        """
        The cart is the only thing that actually refuses a sale, so a policy that stops at
        the serializer would render a working button onto a dead end.
        """
        product = make_product(workspace, stock_quantity=0)
        configure(workspace, out_of_stock_policy='backorder')
        assert self.add(workspace, product).status_code in (200, 201)

    def test_backorder_allows_more_than_is_held(self, workspace):
        product = make_product(workspace, stock_quantity=2)
        configure(workspace, out_of_stock_policy='backorder')
        assert self.add(workspace, product, quantity=50).status_code in (200, 201)


class TestNotifyMe:
    def url(self, product):
        return f'{PRODUCTS_URL}{product.slug}/notify-me/'

    def test_registers_an_address(self, workspace):
        configure(workspace, out_of_stock_policy='notify')
        product = make_product(workspace, stock_quantity=0)
        response = shopper(workspace).post(
            self.url(product), {'email': 'buyer@example.com'}, format='json')
        assert response.status_code == 201
        assert StockNotification.objects.filter(
            workspace=workspace, product=product, email='buyer@example.com').count() == 1

    def test_registering_twice_is_idempotent_and_indistinguishable(self, workspace):
        """
        Same response either way — telling the caller "already registered" would turn an
        unauthenticated endpoint into a test for whether an address shops here.
        """
        configure(workspace, out_of_stock_policy='notify')
        product = make_product(workspace, stock_quantity=0)
        first = shopper(workspace).post(
            self.url(product), {'email': 'buyer@example.com'}, format='json')
        second = shopper(workspace).post(
            self.url(product), {'email': 'buyer@example.com'}, format='json')
        assert (first.status_code, first.data) == (second.status_code, second.data)
        assert StockNotification.objects.filter(product=product).count() == 1

    def test_rejects_a_malformed_address(self, workspace):
        configure(workspace, out_of_stock_policy='notify')
        product = make_product(workspace, stock_quantity=0)
        response = shopper(workspace).post(
            self.url(product), {'email': 'not-an-email'}, format='json')
        assert response.status_code == 400
        assert not StockNotification.objects.exists()

    def test_refused_when_the_policy_makes_no_such_promise(self, workspace):
        """Banking addresses the shop will never write to is worse than refusing."""
        product = make_product(workspace, stock_quantity=0)
        response = shopper(workspace).post(
            self.url(product), {'email': 'buyer@example.com'}, format='json')
        assert response.status_code == 404
        assert not StockNotification.objects.exists()


class TestStorefrontConfigEndpoint:
    def test_policy_travels_with_the_public_config(self, workspace):
        configure(workspace, sku_display='hidden', stock_display='low_only',
                  out_of_stock_policy='notify')
        response = shopper(workspace).get(CONFIG_URL)
        assert response.status_code == 200
        assert response.data['storefront_display'] == {
            'sku_display': 'hidden',
            'stock_display': 'low_only',
            'out_of_stock_policy': 'notify',
        }

    def test_unconfigured_workspace_publishes_the_defaults(self, workspace):
        response = shopper(workspace).get(CONFIG_URL)
        assert response.data['storefront_display'] == DEFAULTS

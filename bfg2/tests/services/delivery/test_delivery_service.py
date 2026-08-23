from decimal import Decimal
from types import SimpleNamespace

from bfg.delivery.services.delivery_service import DeliveryService


def test_address_to_dict_includes_coordinates():
    service = DeliveryService(workspace=None, user=None)
    address = SimpleNamespace(
        full_name="A",
        company="",
        address_line1="l1",
        address_line2="",
        city="c",
        state="s",
        postal_code="p",
        country="NZ",
        phone="1",
        email="e",
        latitude=Decimal("1.2"),
        longitude=Decimal("3.4"),
    )
    result = service._address_to_dict(address)
    assert result["latitude"] == 1.2
    assert result["longitude"] == 3.4


def test_address_to_dict_falls_back_to_the_workspace_country(db):
    """
    A blank country used to become a fixed code — the market the platform's first tenant
    sold in — so every other workspace had its freight quoted from the wrong country
    without anything failing. It now comes from the workspace that owns the address.
    """
    from bfg.common.models import Settings, Workspace

    workspace = Workspace.objects.create(name='AU Shop', slug='au-shop', is_active=True)
    Settings.objects.update_or_create(workspace=workspace, defaults={'country': 'AU'})
    workspace.refresh_from_db()  # the auto-created Settings row is cached on the instance

    service = DeliveryService(workspace=workspace, user=None)
    address = SimpleNamespace(
        full_name="A", company="", address_line1="l1", address_line2="",
        city="c", state="", postal_code="p", country="", phone="1", email="e",
        latitude=None, longitude=None,
    )

    assert service._address_to_dict(address)["country"] == "AU"


def test_address_to_dict_keeps_the_address_country_when_it_has_one(db):
    from bfg.common.models import Settings, Workspace

    workspace = Workspace.objects.create(name='AU Shop 2', slug='au-shop-2', is_active=True)
    Settings.objects.update_or_create(workspace=workspace, defaults={'country': 'AU'})
    workspace.refresh_from_db()  # the auto-created Settings row is cached on the instance

    service = DeliveryService(workspace=workspace, user=None)
    address = SimpleNamespace(
        full_name="A", company="", address_line1="l1", address_line2="",
        city="c", state="", postal_code="p", country="JP", phone="1", email="e",
        latitude=None, longitude=None,
    )

    assert service._address_to_dict(address)["country"] == "JP"


def test_a_carrier_plugin_falls_back_to_its_own_workspaces_country(db):
    """
    Plugins substituted a fixed country for an address that arrived without one. The
    property is exercised through a stand-in rather than a real plugin instance because
    it reads nothing but `self.carrier` — building a plugin would drag in carrier-type
    validation and live credentials for no extra coverage.
    """
    from bfg.common.models import Settings, Workspace
    from bfg.delivery.carriers.base import BaseCarrierPlugin

    workspace = Workspace.objects.create(name='JP Shop', slug='jp-shop', is_active=True)
    Settings.objects.update_or_create(workspace=workspace, defaults={'country': 'JP'})
    workspace.refresh_from_db()  # the auto-created Settings row is cached on the instance

    stand_in = SimpleNamespace(carrier=SimpleNamespace(workspace=workspace))
    assert BaseCarrierPlugin.default_country.fget(stand_in) == 'JP'


def test_a_carrier_plugin_invents_nothing_when_the_workspace_has_no_country(db):
    from bfg.common.models import Workspace
    from bfg.delivery.carriers.base import BaseCarrierPlugin

    workspace = Workspace.objects.create(name='Unset', slug='unset-country', is_active=True)
    stand_in = SimpleNamespace(carrier=SimpleNamespace(workspace=workspace))
    assert BaseCarrierPlugin.default_country.fget(stand_in) == ''

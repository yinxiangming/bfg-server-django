from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from bfg.common.models import Settings, StaffMember, Workspace, WorkspaceDomain
from bfg.common.services.workspace_service import WorkspaceService
from bfg.finance.models import Currency
from bfg.shop.models import Store
from bfg.web.models import Page, Site

User = get_user_model()


def provision(**kwargs):
    out = StringIO()
    args = []
    for key, value in kwargs.items():
        flag = '--' + key.replace('_', '-')
        if value is True:
            args.append(flag)
        else:
            args.extend([flag, str(value)])
    call_command('provision_workspace', *args, stdout=out)
    return out.getvalue()


def test_provision_creates_every_row_a_storefront_needs(db):
    User.objects.create_user(username='prov-admin', password='x', is_superuser=True)

    provision(
        slug='prov-shop', name='Prov Shop', domain='prov.example.test',
        country='NZ', currency='NZD', language='zh-hans', languages='zh-hans,en',
        admin_user='prov-admin', seed_home=True,
    )

    workspace = Workspace.objects.get(slug='prov-shop')
    settings_obj = Settings.objects.get(workspace=workspace)
    assert (settings_obj.country, settings_obj.default_currency, settings_obj.default_language) == (
        'NZ', 'NZD', 'zh-hans',
    )
    assert settings_obj.supported_languages == ['zh-hans', 'en']

    # Without this row OrderService invoices in whatever currency sorts first.
    assert Currency.objects.filter(code='NZD', is_active=True).exists()
    # Without a Store, /store/cart/default_store/ 404s and checkout cannot complete.
    assert Store.all_objects.filter(workspace=workspace, is_active=True).count() == 1
    assert StaffMember.all_objects.filter(workspace=workspace, is_active=True).exists()

    assert workspace.domains.filter(
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        is_primary=True,
        hostname='prov.example.test',
    ).exists()

    site = Site.all_objects.get(workspace=workspace, domain='prov.example.test')
    # The category endpoint filters on the Site language; en here would return nothing.
    assert site.default_language == 'zh-hans'
    assert site.is_default

    home = Page.objects.get(workspace=workspace, slug='home')
    assert home.status == 'published'
    assert [block['type'] for block in home.blocks] == ['hero_carousel_v1', 'section_v1']


def test_provision_is_idempotent(db):
    User.objects.create_user(username='idem-admin', password='x', is_superuser=True)
    kwargs = dict(
        slug='idem-shop', name='Idem Shop', domain='idem.example.test',
        country='NZ', currency='NZD', language='en', admin_user='idem-admin', seed_home=True,
    )

    provision(**kwargs)
    provision(**kwargs)

    workspace = Workspace.objects.get(slug='idem-shop')
    assert Store.all_objects.filter(workspace=workspace).count() == 1
    assert Site.all_objects.filter(workspace=workspace).count() == 1
    assert Page.objects.filter(workspace=workspace, slug='home').count() == 1
    assert StaffMember.all_objects.filter(workspace=workspace).count() == 1


def test_dry_run_writes_nothing(db):
    provision(slug='dry-shop', name='Dry Shop', domain='dry.example.test',
              currency='NZD', dry_run=True)

    assert not Workspace.objects.filter(slug='dry-shop').exists()
    assert not Currency.objects.filter(code='NZD').exists()


def test_check_reports_the_gaps_a_bare_workspace_has(db):
    user = User.objects.create_user(username='bare-admin', password='x')
    WorkspaceService(workspace=None, user=user).create_workspace(
        name='Bare', slug='bare-shop', owner_user=user,
    )

    out = StringIO()
    with pytest.raises(CommandError):
        call_command('provision_workspace', '--slug', 'bare-shop', '--check', stdout=out)

    report = out.getvalue()
    # Creating a workspace leaves it with no store, no domain, no site and no home page.
    assert 'MISSING active store' in report
    assert 'MISSING primary verified domain' in report
    assert 'MISSING site row' in report
    assert 'MISSING published home page' in report
    # …but its Settings row and roles do get created for it.
    assert 'ok      settings row' in report
    assert 'ok      workspace admin' in report


def test_check_passes_once_provisioned(db):
    User.objects.create_user(username='full-admin', password='x', is_superuser=True)
    provision(slug='full-shop', name='Full Shop', domain='full.example.test',
              country='NZ', currency='NZD', language='en', admin_user='full-admin', seed_home=True)

    out = StringIO()
    # The header menu is the one thing provisioning does not seed, so --check still
    # reports a gap; everything else has to pass.
    with pytest.raises(CommandError):
        call_command('provision_workspace', '--slug', 'full-shop', '--check', stdout=out)

    report = out.getvalue()
    assert report.count('MISSING') == 1
    assert 'MISSING header menu' in report


def test_domain_already_owned_by_another_workspace_is_refused(db):
    user = User.objects.create_user(username='clash-admin', password='x')
    other = WorkspaceService(workspace=None, user=user).create_workspace(
        name='Other', slug='other-shop', owner_user=user,
    )
    WorkspaceDomain.objects.create(
        workspace=other, hostname='taken.example.test',
        kind=WorkspaceDomain.KIND_CUSTOM,
        verification_status=WorkspaceDomain.VERIFICATION_VERIFIED,
        is_primary=True,
    )

    with pytest.raises(CommandError, match='already belongs to workspace'):
        provision(slug='clash-shop', name='Clash Shop', domain='taken.example.test')

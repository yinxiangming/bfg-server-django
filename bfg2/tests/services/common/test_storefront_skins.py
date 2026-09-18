from dataclasses import replace

import pytest
from django.core.cache import cache

from bfg.common.extensions import (
    ExtensionManifest,
    available_storefront_skins,
    validate_storefront_skin,
)
from bfg.common.extensions import registry
from bfg.common.extensions.storefront_skins import set_storefront_skin
from bfg.common.models import Workspace
from bfg.common.storefront_cache import storefront_config_cache_key


@pytest.fixture(autouse=True)
def manifests(monkeypatch):
    deployed = {
        'resale': ExtensionManifest(
            key='resale',
            name='Resale',
            storefront_skins=('preloved',),
            default_storefront_skin='preloved',
        ),
        'other': ExtensionManifest(key='other', name='Other', storefront_skins=('catalogue',)),
    }
    monkeypatch.setattr(registry, '_discover', lambda: dict(deployed))
    registry.reset_cache()
    yield deployed
    registry.reset_cache()


def test_all_deployed_manifest_skins_are_available_by_default():
    assert available_storefront_skins() == {'store', 'website', 'preloved', 'catalogue'}
    assert validate_storefront_skin(' preloved ') == 'preloved'


def test_extension_keys_restrict_skins_without_removing_core_skins():
    assert available_storefront_skins(['resale']) == {'store', 'website', 'preloved'}
    assert validate_storefront_skin('website', []) == 'website'
    with pytest.raises(ValueError, match='Unknown or unavailable'):
        validate_storefront_skin('preloved', [])


@pytest.mark.parametrize('value', ['', None, '   '])
def test_blank_skin_means_no_explicit_selection(value):
    assert validate_storefront_skin(value) == ''


def test_an_undeployed_skin_is_rejected(manifests):
    manifests['resale'] = replace(manifests['resale'], storefront_skins=(), default_storefront_skin='')
    registry.reset_cache()

    assert available_storefront_skins(['resale']) == {'store', 'website'}
    with pytest.raises(ValueError, match='Unknown or unavailable'):
        validate_storefront_skin('preloved', ['resale'])


@pytest.mark.django_db
def test_writing_a_skin_invalidates_storefront_config_after_commit(
    django_capture_on_commit_callbacks,
):
    workspace = Workspace.objects.create(name='Skinned', slug='skinned')
    key = storefront_config_cache_key(workspace.id, 'en')
    cache.set(key, {'theme': 'store'}, 60)

    with django_capture_on_commit_callbacks(execute=True):
        assert set_storefront_skin(workspace, 'preloved') is True

    assert cache.get(key) is None

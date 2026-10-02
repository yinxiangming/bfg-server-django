"""Generic extension manifests used by Brand Portal tests."""

from dataclasses import replace
from unittest.mock import patch

from bfg.common.extensions import ExtensionManifest, registry
from bfg.common.extensions import services as extension_services

from apps.brand_portal.extension import EXTENSION as BRAND_PORTAL_EXTENSION


SAMPLE_EXTENSION = "sample_feature"
SAMPLE_THEME_EXTENSION = "sample_theme_feature"
SAMPLE_SKIN = "sample_skin"


def _test_manifests():
    return {
        "brand_portal": replace(BRAND_PORTAL_EXTENSION, app_label="brand_portal"),
        SAMPLE_EXTENSION: ExtensionManifest(
            key=SAMPLE_EXTENSION,
            name="Sample feature",
            app_label="sample_feature_app",
        ),
        SAMPLE_THEME_EXTENSION: ExtensionManifest(
            key=SAMPLE_THEME_EXTENSION,
            name="Sample theme feature",
            storefront_skins=(SAMPLE_SKIN,),
            default_storefront_skin=SAMPLE_SKIN,
            app_label="sample_theme_feature_app",
        ),
    }


class GenericExtensionRegistryMixin:
    """Keep Brand Portal tests independent from deployment-owned extensions."""

    @classmethod
    def setUpClass(cls):
        cls._extension_registry_patch = patch.object(
            registry,
            "_discover",
            side_effect=_test_manifests,
        )
        cls._extension_registry_patch.start()
        registry.reset_cache()
        extension_services._load_entitlement_check.cache_clear()
        try:
            super().setUpClass()
        except Exception:
            cls._extension_registry_patch.stop()
            registry.reset_cache()
            extension_services._load_entitlement_check.cache_clear()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._extension_registry_patch.stop()
            registry.reset_cache()
            extension_services._load_entitlement_check.cache_clear()

"""MySQL-only settings for the schema retry CI job."""

import os

from .settings import *  # noqa: F403


# These synthetic apps intentionally have no migrations and are created with
# syncdb by the SQLite test suite. On MySQL, their foreign keys would be added
# before the migrated BFG tables they reference exist. The schema retry job
# exercises only real BFG migrations, so keep those unrelated fixtures out of
# this test database.
_SYNCDB_ONLY_TEST_APPS = {
    "tests.extension_data.apps.ExtensionDataTestsConfig",
    "tests.tenant_isolation.apps.TenantIsolationTestsConfig",
}
INSTALLED_APPS = [  # noqa: F405
    app for app in INSTALLED_APPS if app not in _SYNCDB_ONLY_TEST_APPS
]
MIGRATION_MODULES = {
    app_label: module
    for app_label, module in MIGRATION_MODULES.items()  # noqa: F405
    if app_label not in {"extension_data_tests", "tenant_isolation_tests"}
}


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE", "bfg_migration_ci"),
        "USER": os.environ.get("MYSQL_USER", "root"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", "test-only-password"),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
        "TEST": {"NAME": os.environ.get("MYSQL_TEST_DATABASE", "test_bfg_migration_ci")},
    }
}

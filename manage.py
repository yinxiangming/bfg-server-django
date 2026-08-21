#!/usr/bin/env python
import os
import sys
from pathlib import Path

# Add project paths for apps.* and bfg2
BASE_DIR = Path(__file__).resolve().parent
for p in (str(BASE_DIR), str(BASE_DIR / 'bfg2')):
    if p not in sys.path:
        sys.path.insert(0, p)

def main():
    """Run administrative tasks."""
    # Prefer mysqlclient (Django's recommended MySQL driver); fall back to PyMySQL.
    try:
        import MySQLdb  # noqa: F401  (mysqlclient)
    except ImportError:
        try:
            import pymysql
            pymysql.install_as_MySQLdb()
        except ImportError:
            pass

    from config.django_settings_env import setdefault_django_settings_module

    setdefault_django_settings_module()



    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

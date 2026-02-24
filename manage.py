#!/usr/bin/env python
import os
import sys
from pathlib import Path

# Add bfg2 to Python path
BASE_DIR = Path(__file__).resolve().parent
bfg2_path = BASE_DIR / 'bfg2'
if str(bfg2_path) not in sys.path:
    sys.path.insert(0, str(bfg2_path))

def main():
    """Run administrative tasks."""
    # Try to install PyMySQL if available
    try:
        import pymysql
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass

    # Set default settings module
    env = os.getenv('ENV', 'dev')
    
    # Mapping environment names to settings modules
    env_mapping = {
        'prod': 'config.prod',
        'test': 'config.test',
        'dev': 'config.dev',
        'local': 'config.dev',
    }
    
    # Default to 'config.settings' if env is not in mapping
    settings_module = env_mapping.get(env, 'config.settings')
    
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)



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

"""Isolated PostgreSQL integration settings; never load a business .env file."""
import os
from config.test import *
if os.environ.get('PACKGO_MOBILE_ISOLATED_TEST') != '1':
    raise RuntimeError('Explicit isolated-test opt-in required')
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'mobile_test',
    'USER': 'mobile_test', 'HOST': '127.0.0.1', 'PORT': '55439', 'CONN_MAX_AGE': 0,
    'TEST': {'NAME': 'test_mobile_api_20261010_v2'}}}

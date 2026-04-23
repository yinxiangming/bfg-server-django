# -*- coding: utf-8 -*-
"""
Runtime server version metadata for health checks and client compatibility.
"""

import os

from django.conf import settings


def get_server_version_payload():
    """
    Return version fields for the running server process.

    Optional env vars (CI / containers):
    - BUILD_ID, GIT_SHA: deployment revision shown when set.
    """
    import bfg

    spectacular = getattr(settings, 'SPECTACULAR_SETTINGS', None) or {}
    payload = {
        'api_version': 'v1',
        'schema_version': spectacular.get('VERSION') or '',
        'bfg_version': getattr(bfg, '__version__', 'unknown'),
    }
    build_id = os.environ.get('BUILD_ID') or os.environ.get('GIT_SHA')
    if build_id:
        payload['build_id'] = build_id
    return payload

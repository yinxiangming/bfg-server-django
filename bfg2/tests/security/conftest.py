"""Fixtures shared by the security tests."""

import pytest
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.views import APIView

from config.authentication import APIKeyAuthentication, BearerTokenAuthentication

# REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] in config/settings.py. The test
# settings authenticate by session and basic credentials only, so there a view
# that relies on the defaults never meets an API key or a JWT.
PRODUCTION_AUTHENTICATION_CLASSES = (
    APIKeyAuthentication,
    SessionAuthentication,
    BasicAuthentication,
    BearerTokenAuthentication,
)


@pytest.fixture
def production_authentication(monkeypatch):
    """Return a function that authenticates the given views as a deployment would.

    DRF reads the default classes once, at import, so overriding settings in a
    test changes nothing. A view that relies on the defaults gets production's;
    one that declares its own classes keeps them.
    """
    def apply(*view_classes):
        for view_class in view_classes:
            if view_class.authentication_classes is APIView.authentication_classes:
                monkeypatch.setattr(view_class, 'authentication_classes', PRODUCTION_AUTHENTICATION_CLASSES)

    return apply

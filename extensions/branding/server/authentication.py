# -*- coding: utf-8 -*-
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from config.authentication import APIKeyAuthentication


class PortalAPIKeyAuthentication(APIKeyAuthentication):
    """Portal-specific API-key authentication with an explicit OpenAPI contract."""


class PortalAPIKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = PortalAPIKeyAuthentication
    name = ['portalApiKey', 'portalApiSecret']

    def get_security_definition(self, auto_schema):
        return [
            {'type': 'apiKey', 'in': 'header', 'name': 'X-Api-Key'},
            {'type': 'apiKey', 'in': 'header', 'name': 'X-Api-Secret'},
        ]

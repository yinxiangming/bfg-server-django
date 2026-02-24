# -*- coding: utf-8 -*-
"""
Mailgun email backend via HTTP API.
"""
import requests
from typing import List, Optional

from .base import BaseEmailBackend, schema_field


class MailgunBackend(BaseEmailBackend):
    """Send email via Mailgun API. Config: api_key, domain, from_email, optional region (e.g. eu)."""

    backend_type_id = 'mailgun'
    label = 'Mailgun'
    config_schema = {
        'api_key': schema_field('string', required=True, sensitive=True),
        'domain': schema_field('string', required=True),
        'from_email': schema_field('string', required=True),
        'region': schema_field('string', required=False),
    }

    def send(
        self,
        to_list: List[str],
        subject: str,
        body_plain: str,
        body_html: Optional[str] = None,
        from_email: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        if not config:
            raise ValueError("Mailgun backend requires config")
        api_key = config.get('api_key')
        domain = config.get('domain')
        if not api_key or not domain:
            raise ValueError("Mailgun config must include api_key and domain")
        from_addr = from_email or config.get('from_email')
        if not from_addr:
            raise ValueError("Mailgun config must include from_email or pass from_email")

        region = config.get('region', '').lower()
        if region == 'eu':
            base_url = 'https://api.eu.mailgun.net/v3'
        else:
            base_url = 'https://api.mailgun.net/v3'
        url = f"{base_url}/{domain}/messages"

        data = {
            'from': from_addr,
            'to': to_list,
            'subject': subject,
            'text': body_plain,
        }
        if body_html:
            data['html'] = body_html

        resp = requests.post(
            url,
            auth=('api', api_key),
            data=data,
            timeout=30,
        )
        resp.raise_for_status()

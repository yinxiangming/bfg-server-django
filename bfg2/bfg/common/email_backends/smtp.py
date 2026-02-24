# -*- coding: utf-8 -*-
"""
SMTP email backend using smtplib.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from .base import BaseEmailBackend, schema_field


class SMTPBackend(BaseEmailBackend):
    """Send email via SMTP using config: host, port, use_tls, use_ssl, user, password, from_email."""

    backend_type_id = 'smtp'
    label = 'SMTP'
    config_schema = {
        'host': schema_field('string', required=True),
        'port': schema_field('integer', required=True, default=587),
        'use_tls': schema_field('boolean', default=False),
        'use_ssl': schema_field('boolean', default=False),
        'user': schema_field('string', required=False),
        'password': schema_field('string', required=False, sensitive=True),
        'from_email': schema_field('string', required=True),
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
            raise ValueError("SMTP backend requires config")
        host = config.get('host')
        port = config.get('port', 25)
        if host is None:
            raise ValueError("SMTP config must include host")
        from_addr = from_email or config.get('from_email')
        if not from_addr:
            raise ValueError("SMTP config must include from_email or pass from_email")

        use_ssl = config.get('use_ssl', False)
        use_tls = config.get('use_tls', False)
        user = config.get('user')
        password = config.get('password')

        if body_html:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(body_plain, 'plain'))
            msg.attach(MIMEText(body_html, 'html'))
        else:
            msg = MIMEText(body_plain, 'plain')

        msg['Subject'] = subject
        msg['From'] = from_addr
        msg['To'] = ', '.join(to_list)

        if use_ssl:
            server = smtplib.SMTP_SSL(host, int(port))
        else:
            server = smtplib.SMTP(host, int(port))
        try:
            if use_tls and not use_ssl:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to_list, msg.as_string())
        finally:
            server.quit()

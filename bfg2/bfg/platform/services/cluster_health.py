# -*- coding: utf-8 -*-
"""Restricted, allowlisted probes for configured Cluster API endpoints."""
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

import requests
from django.conf import settings


class ClusterHealthProbeConfigurationError(ValueError):
    """Raised when an operator has not allowed this host for a server-side probe."""


@dataclass(frozen=True)
class ClusterHealthProbeResult:
    health_status: str
    http_status: int | None


def _allowed_hosts():
    configured = getattr(settings, "CLUSTER_HEALTH_ALLOWED_HOSTS", []) or []
    if isinstance(configured, str):
        configured = configured.split(",")
    return {str(host).strip().lower().rstrip(".") for host in configured if str(host).strip()}


def _allowed(host, configured):
    return any(
        host.endswith(f".{candidate[2:]}") if candidate.startswith("*.") else host == candidate
        for candidate in configured
    )


def _is_ip_literal(host):
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def cluster_health_url(cluster):
    """Build exactly one HTTPS health URL from an explicit operator allowlist."""
    configured = _allowed_hosts()
    parsed = urlsplit(cluster.api_base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        not configured
        or parsed.scheme != "https"
        or not host
        or _is_ip_literal(host)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.port not in (None, 443)
        or not _allowed(host, configured)
    ):
        raise ClusterHealthProbeConfigurationError("Cluster health probe target is not allowed.")
    return f"https://{host}/api/v1/health/"


def probe_cluster_health(cluster):
    """Probe the fixed endpoint without proxy settings, redirects, or body disclosure."""
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            cluster_health_url(cluster),
            headers={"User-Agent": "BFG-Platform-Cluster-Health/1.0"},
            timeout=(2, 5),
            allow_redirects=False,
        )
    except requests.RequestException:
        return ClusterHealthProbeResult(health_status="down", http_status=None)
    finally:
        session.close()
    if not 200 <= response.status_code < 300:
        return ClusterHealthProbeResult(health_status="degraded", http_status=response.status_code)
    try:
        healthy = response.json() == {"status": "ok"}
    except ValueError:
        healthy = False
    return ClusterHealthProbeResult(
        health_status="healthy" if healthy else "degraded",
        http_status=response.status_code,
    )

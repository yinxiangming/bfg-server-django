# -*- coding: utf-8 -*-
"""Restricted server-side probes for Platform Cluster API health."""
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

import requests
from django.conf import settings


class ClusterHealthProbeConfigurationError(ValueError):
    """The target is not explicitly allowed for server-side health checks."""


@dataclass(frozen=True)
class ClusterHealthProbeResult:
    """Safe health result without transport or response-body disclosure."""

    health_status: str
    http_status: int | None


def _allowed_hosts():
    configured = getattr(settings, "CLUSTER_HEALTH_ALLOWED_HOSTS", []) or []
    if isinstance(configured, str):
        configured = configured.split(",")
    return {str(host).strip().lower().rstrip(".") for host in configured if str(host).strip()}


def _is_allowed_host(host, allowed_hosts):
    for allowed in allowed_hosts:
        if allowed.startswith("*."):
            suffix = allowed[2:]
            if host.endswith(f".{suffix}"):
                return True
        elif host == allowed:
            return True
    return False


def _is_ip_literal(host):
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def cluster_health_url(cluster):
    """Build the sole probe target from a whitelisted HTTPS API base URL."""
    configured_hosts = _allowed_hosts()
    if not configured_hosts:
        raise ClusterHealthProbeConfigurationError("Cluster health probes are not configured.")

    parsed = urlsplit(cluster.api_base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or _is_ip_literal(host)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.port not in (None, 443)
        or not _is_allowed_host(host, configured_hosts)
    ):
        raise ClusterHealthProbeConfigurationError("Cluster health probe target is not allowed.")
    return f"https://{host}/api/v1/health/"


def probe_cluster_health(cluster):
    """Probe a fixed health endpoint without redirects, proxies, or response data."""
    url = cluster_health_url(cluster)
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(
            url,
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
        payload = response.json()
    except ValueError:
        return ClusterHealthProbeResult(health_status="degraded", http_status=response.status_code)
    return ClusterHealthProbeResult(
        health_status="healthy" if payload == {"status": "ok"} else "degraded",
        http_status=response.status_code,
    )

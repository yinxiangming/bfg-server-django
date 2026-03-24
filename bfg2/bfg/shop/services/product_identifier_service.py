from __future__ import annotations

from datetime import datetime
import random
import string
from typing import MutableMapping


DEFAULT_SKU_PREFIX = "SKU-"
DEFAULT_BARCODE_PREFIX = "P-"


def _random_suffix(length: int = 4) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=length))


def generate_identifier(prefix: str, now: datetime | None = None) -> str:
    ts = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
    return f"{prefix}{ts}-{_random_suffix()}"


def _get_workspace_custom_settings(workspace) -> dict:
    ws_settings = getattr(workspace, "workspace_settings", None)
    custom = getattr(ws_settings, "custom_settings", None)
    return custom if isinstance(custom, dict) else {}


def get_workspace_identifier_prefixes(
    workspace,
    *,
    default_sku_prefix: str = DEFAULT_SKU_PREFIX,
    default_barcode_prefix: str = DEFAULT_BARCODE_PREFIX,
    custom_settings_path: tuple[str, ...] = ("shop", "product_identifiers"),
) -> tuple[str, str]:
    custom = _get_workspace_custom_settings(workspace)
    node = custom
    for key in custom_settings_path:
        if not isinstance(node, dict):
            node = {}
            break
        node = node.get(key, {})

    sku_prefix = default_sku_prefix
    barcode_prefix = default_barcode_prefix
    if isinstance(node, dict):
        if isinstance(node.get("sku_prefix"), str) and node.get("sku_prefix").strip():
            sku_prefix = node["sku_prefix"].strip()
        if isinstance(node.get("barcode_prefix"), str) and node.get("barcode_prefix").strip():
            barcode_prefix = node["barcode_prefix"].strip()
    return sku_prefix, barcode_prefix


def ensure_product_identifiers(
    data: MutableMapping[str, object],
    *,
    workspace=None,
    sku_prefix: str = DEFAULT_SKU_PREFIX,
    barcode_prefix: str = DEFAULT_BARCODE_PREFIX,
    custom_settings_path: tuple[str, ...] = ("shop", "product_identifiers"),
) -> MutableMapping[str, object]:
    if workspace is not None:
        sku_prefix, barcode_prefix = get_workspace_identifier_prefixes(
            workspace,
            default_sku_prefix=sku_prefix,
            default_barcode_prefix=barcode_prefix,
            custom_settings_path=custom_settings_path,
        )
    sku = str(data.get("sku") or "").strip()
    barcode = str(data.get("barcode") or "").strip()
    now = datetime.now()

    if not sku:
        data["sku"] = generate_identifier(sku_prefix, now)
    if not barcode:
        data["barcode"] = generate_identifier(barcode_prefix, now)
    return data

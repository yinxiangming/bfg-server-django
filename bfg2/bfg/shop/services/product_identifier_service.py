from __future__ import annotations

import re
import random
import string
from typing import MutableMapping


DEFAULT_SKU_PREFIX = ""
DEFAULT_BARCODE_PREFIX = "P-"


def _random_suffix(length: int = 3) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=length))


def _sku_from_name(name: str) -> str:
    """Derive a short readable code from a product name.

    Examples:
        "Blue T-Shirt"   → "BTS"
        "iPhone 15 Pro"  → "IP15"
        "Nike Air Max 90"→ "NAM90"
    """
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', name).strip()
    words = clean.split()
    if not words:
        return ""
    # First letter (alpha) of each word, up to 3 words
    abbrev = "".join(w[0].upper() for w in words[:3] if w and w[0].isalpha())
    if len(abbrev) < 2:
        # Too short — use first 4 alphanumeric chars of the first word
        abbrev = re.sub(r'[^A-Z0-9]', '', words[0].upper())[:4]
    # Append first number sequence found in the original name (up to 4 digits)
    num_match = re.search(r'\d+', name)
    if num_match:
        abbrev += num_match.group()[:4]
    return abbrev[:8]


def generate_sku(prefix: str, name: str = "") -> str:
    name_part = _sku_from_name(name) if name else ""
    suffix = _random_suffix(3)
    if name_part:
        return f"{prefix}{name_part}-{suffix}" if prefix else f"{name_part}-{suffix}"
    # Fallback when no name is available
    return f"{prefix}{suffix}" if prefix else suffix


def generate_barcode_from_product_id(product_id, prefix: str = DEFAULT_BARCODE_PREFIX) -> str:
    return f"{prefix}{product_id}"


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

    if not sku:
        name = str(data.get("name") or "").strip()
        data["sku"] = generate_sku(sku_prefix, name)

    # Barcode is set after product save using the product ID; store the prefix
    # in data so the caller can apply it post-save via generate_barcode_from_product_id.
    data.setdefault("_barcode_prefix", barcode_prefix)

    return data

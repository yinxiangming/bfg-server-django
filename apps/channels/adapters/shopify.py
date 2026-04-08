# -*- coding: utf-8 -*-
"""
Shopify adapter.

Credentials stored in ExternalChannel.credentials:
  {
    "shop_domain": "mystore.myshopify.com",
    "api_key":     "...",
    "api_password": "..."
  }

Uses Shopify REST Admin API 2024-01:
  https://shopify.dev/docs/api/admin-rest/2024-01
"""
import requests

from apps.channels.adapters.base import ChannelAdapter


class ShopifyAdapter(ChannelAdapter):
    API_VERSION = "2024-01"

    FIELD_SPEC = {
        "title": {"source": "name", "max_length": 255, "required": True},
        "body_html": {"source": "description", "type": "html"},
        "price": {"source": "price", "type": "decimal", "required": True},
        "tags": {"source": "tags", "type": "tags"},
        "vendor": {"type": "config", "key": "vendor_name"},
    }

    @property
    def base_url(self) -> str:
        shop = self.channel.credentials["shop_domain"]
        return f"https://{shop}/admin/api/{self.API_VERSION}"

    def _session(self) -> requests.Session:
        creds = self.channel.credentials
        session = requests.Session()
        session.auth = (creds["api_key"], creds["api_password"])
        session.headers.update({"Content-Type": "application/json"})
        return session

    def validate_credentials(self) -> bool:
        session = self._session()
        url = f"{self.base_url}/shop.json"
        resp = session.get(url, timeout=15)
        return resp.status_code == 200

    def _map_variants(self, product) -> list:
        """Map product variants to Shopify variant objects."""
        variants = []
        if hasattr(product, "variants") and product.variants.exists():
            for v in product.variants.all():
                variants.append({
                    "price": str(v.price),
                    "sku": v.sku or "",
                    "inventory_quantity": getattr(v, "stock", 0),
                })
        else:
            variants.append({
                "price": str(product.price),
                "sku": product.sku or "",
            })
        return variants

    def map_product(self, product) -> dict:
        tags = ",".join(t.name for t in product.tags.all()) if hasattr(product, "tags") else ""
        images = []
        if hasattr(product, "media"):
            images = [{"src": m.url} for m in product.media.all() if hasattr(m, "url")]
        return {
            "product": {
                "title": product.name,
                "body_html": product.description or "",
                "vendor": self.channel.config.get("vendor_name", ""),
                "tags": tags,
                "images": images,
                "variants": self._map_variants(product),
            }
        }

    def publish(self, product) -> str:
        session = self._session()
        url = f"{self.base_url}/products.json"
        payload = self.map_product(product)
        resp = session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return str(result["product"]["id"])

    def update(self, listing) -> None:
        session = self._session()
        url = f"{self.base_url}/products/{listing.external_id}.json"
        payload = self.map_product(listing.product)
        payload["product"]["id"] = listing.external_id
        resp = session.put(url, json=payload, timeout=30)
        resp.raise_for_status()

    def end(self, listing) -> None:
        """Set product status to 'draft' to effectively de-list it."""
        session = self._session()
        url = f"{self.base_url}/products/{listing.external_id}.json"
        payload = {"product": {"id": listing.external_id, "status": "draft"}}
        resp = session.put(url, json=payload, timeout=15)
        resp.raise_for_status()

    def relist(self, listing) -> str:
        """Set product status back to 'active'."""
        session = self._session()
        url = f"{self.base_url}/products/{listing.external_id}.json"
        payload = {"product": {"id": listing.external_id, "status": "active"}}
        resp = session.put(url, json=payload, timeout=15)
        resp.raise_for_status()
        # Shopify reuse the same product ID
        return listing.external_id

    def fetch_feedback(self, listing) -> list:
        """Shopify does not have a built-in feedback/review API; return empty."""
        return []

    def fetch_questions(self, listing) -> list:
        """Shopify does not have a built-in Q&A API; return empty."""
        return []

    def post_answer(self, question, answer: str) -> None:
        """Shopify does not support answering questions via API."""
        raise NotImplementedError("Shopify does not support posting answers via API.")

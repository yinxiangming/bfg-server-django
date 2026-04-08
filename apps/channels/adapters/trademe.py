# -*- coding: utf-8 -*-
"""
TradeMe adapter.

Credentials stored in ExternalChannel.credentials:
  {
    "consumer_key":        "...",
    "consumer_secret":     "...",
    "oauth_token":         "...",
    "oauth_token_secret":  "..."
  }

API docs: https://developer.trademe.co.nz/api-reference/
"""
import re

from apps.channels.adapters.base import ChannelAdapter


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text or "")


class TradeMeAdapter(ChannelAdapter):
    TITLE_MAX = 50
    DESC_MAX = 2048

    SANDBOX_BASE = "https://api.tmsandbox.co.nz/v1"
    PROD_BASE = "https://api.trademe.co.nz/v1"

    CONDITION_MAP = {
        "new": "New",
        "like_new": "Used",
        "good": "Used",
        "fair": "Used",
        "poor": "Used",
        "": "New",
    }

    FIELD_SPEC = {
        "title": {"source": "name", "max_length": 50, "required": True},
        "description": {
            "source": "description",
            "max_length": 2048,
            "strip_html": True,
        },
        "price": {"source": "price", "type": "decimal", "required": True},
        "category": {"source": "categories", "type": "mapped", "required": True},
        "condition": {"source": "condition", "type": "mapped"},
        "photos": {"source": "media", "max_count": 10, "type": "upload"},
    }

    @property
    def base_url(self) -> str:
        if self.channel.config.get("sandbox", False):
            return self.SANDBOX_BASE
        return self.PROD_BASE

    def _get_session(self):
        """Build an OAuth1-authenticated requests session."""
        try:
            from requests_oauthlib import OAuth1Session
        except ImportError as exc:
            raise RuntimeError(
                "requests_oauthlib is required for TradeMeAdapter. "
                "Install it with: pip install requests_oauthlib"
            ) from exc

        creds = self.channel.credentials
        return OAuth1Session(
            client_key=creds["consumer_key"],
            client_secret=creds["consumer_secret"],
            resource_owner_key=creds["oauth_token"],
            resource_owner_secret=creds["oauth_token_secret"],
        )

    def validate_credentials(self) -> bool:
        session = self._get_session()
        url = f"{self.base_url}/MyTradeMe/Summary.json"
        resp = session.get(url, timeout=15)
        return resp.status_code == 200

    def _map_category(self, product) -> str:
        """Map product categories to TradeMe category ID."""
        categories = list(product.categories.all()) if hasattr(product, "categories") else []
        if categories:
            # Use first category's external mapping if available
            cat = categories[0]
            mapping = self.channel.config.get("category_map", {})
            return mapping.get(str(cat.id), self.channel.config.get("default_category_id", ""))
        return self.channel.config.get("default_category_id", "")

    def _upload_photos(self, product) -> list:
        """Return list of TradeMe photo IDs (upload if needed)."""
        # Placeholder: in production, upload images and return photo IDs
        return []

    def map_product(self, product) -> dict:
        description = _strip_html(product.description or "")[: self.DESC_MAX]
        condition = getattr(product, "condition", "")
        return {
            "Title": (product.name or "")[:self.TITLE_MAX],
            "Description": description,
            "StartPrice": float(product.price),
            "ReservePrice": float(product.compare_price) if getattr(product, "compare_price", None) else None,
            "Category": self._map_category(product),
            "Condition": self.CONDITION_MAP.get(condition, "New"),
            "Duration": self.channel.config.get("default_duration_days", 7),
            "ShippingOptions": self.channel.config.get("shipping_options", []),
            "PhotoIds": self._upload_photos(product),
        }

    def publish(self, product) -> str:
        session = self._get_session()
        data = self.map_product(product)
        url = f"{self.base_url}/Selling.json"
        resp = session.post(url, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return str(result["ListingId"])

    def update(self, listing) -> None:
        session = self._get_session()
        data = self.map_product(listing.product)
        data["ListingId"] = listing.external_id
        url = f"{self.base_url}/Listings/{listing.external_id}.json"
        resp = session.post(url, json=data, timeout=30)
        resp.raise_for_status()

    def end(self, listing) -> None:
        session = self._get_session()
        url = f"{self.base_url}/Listings/{listing.external_id}/Withdraw.json"
        resp = session.post(url, json={"ListingId": listing.external_id, "Reason": "Sold"}, timeout=15)
        resp.raise_for_status()

    def relist(self, listing) -> str:
        session = self._get_session()
        url = f"{self.base_url}/Selling/{listing.external_id}/Relist.json"
        resp = session.post(url, json={}, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        return str(result["NewListingId"])

    def fetch_feedback(self, listing) -> list:
        session = self._get_session()
        url = f"{self.base_url}/MyTradeMe/FeedbackForSeller.json"
        resp = session.get(url, params={"rows": 50}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("List", []):
            if str(item.get("ListingId")) == str(listing.external_id):
                results.append({
                    "id": str(item["FeedbackId"]),
                    "author": item.get("Nickname", ""),
                    "type": item.get("FeedbackType", "positive").lower(),
                    "comment": item.get("Comment", ""),
                    "date": item.get("Date", ""),
                })
        return results

    def fetch_questions(self, listing) -> list:
        session = self._get_session()
        url = f"{self.base_url}/Listings/{listing.external_id}/Questions.json"
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("List", []):
            results.append({
                "id": str(item["QuestionId"]),
                "question": item.get("QuestionText", ""),
                "asker": item.get("Nickname", ""),
                "date": item.get("AskedAt", ""),
                "answer": item.get("Answer", ""),
            })
        return results

    def post_answer(self, question, answer: str) -> None:
        session = self._get_session()
        url = (
            f"{self.base_url}/Listings/{question.listing.external_id}"
            f"/Questions/{question.external_id}/Answer.json"
        )
        resp = session.post(url, json={"Answer": answer}, timeout=15)
        resp.raise_for_status()

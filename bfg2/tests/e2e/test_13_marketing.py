"""
E2E Test 13: Marketing Module

All test data is created via API (no ORM). Covers campaigns, discount rules,
coupons, gift cards, campaign displays (slides, featured categories/posts),
storefront promo API (slides, flash_sales, group_buys).
"""

import pytest
from datetime import datetime, timedelta
from django.utils import timezone


def _create_discount_rule_via_api(client, name="Test Discount Rule", **kwargs):
    """Create discount rule via API and return response data."""
    payload = {
        "name": name,
        "discount_type": kwargs.get("discount_type", "percentage"),
        "discount_value": str(kwargs.get("discount_value", "10.00")),
        "apply_to": kwargs.get("apply_to", "order"),
        "is_active": kwargs.get("is_active", True),
    }
    if "valid_from" in kwargs:
        payload["valid_from"] = kwargs["valid_from"].isoformat()
    if "valid_until" in kwargs:
        payload["valid_until"] = kwargs["valid_until"].isoformat()
    if "display_label" in kwargs:
        payload["display_label"] = kwargs["display_label"]
    response = client.post("/api/v1/marketing/discount-rules/", payload)
    assert response.status_code == 201
    return response.data


def _get_currency_id_via_api(client):
    """Get first active currency id from finance API."""
    response = client.get("/api/v1/finance/currencies/")
    assert response.status_code == 200
    data = response.data if isinstance(response.data, list) else response.data.get("results", response.data)
    if not data:
        pytest.skip("No currency in DB; create currency via API or seed.")
    for c in data:
        if c.get("is_active") and c.get("code") == "USD":
            return c["id"]
    return data[0]["id"]


@pytest.mark.e2e
@pytest.mark.django_db
class TestMarketing:

    def test_campaign_creation(self, authenticated_client, workspace):
        """Test campaign creation via API"""
        start_date = timezone.now()
        end_date = start_date + timedelta(days=30)

        payload = {
            "name": "Summer Sale Campaign",
            "campaign_type": "email",
            "description": "Summer sale campaign",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "budget": "1000.00",
            "utm_source": "email",
            "utm_medium": "newsletter",
            "utm_campaign": "summer_sale",
            "is_active": True,
        }

        response = authenticated_client.post("/api/v1/marketing/campaigns/", payload)

        assert response.status_code == 201
        assert response.data["name"] == "Summer Sale Campaign"
        assert response.data["campaign_type"] == "email"

    def test_campaign_update(self, authenticated_client, workspace):
        """Test campaign update via API"""
        start_date = timezone.now()
        end_date = start_date + timedelta(days=30)

        create_res = authenticated_client.post(
            "/api/v1/marketing/campaigns/",
            {
                "name": "Test Campaign",
                "campaign_type": "email",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_active": True,
            },
        )
        assert create_res.status_code == 201
        campaign_id = create_res.data["id"]

        update_payload = {"name": "Updated Campaign Name", "budget": "2000.00"}
        response = authenticated_client.patch(
            f"/api/v1/marketing/campaigns/{campaign_id}/", update_payload
        )

        assert response.status_code == 200
        assert response.data["name"] == "Updated Campaign Name"
        assert response.data["budget"] == "2000.00"

    def test_discount_rule_creation(self, authenticated_client, workspace):
        """Test discount rule creation via API"""
        data = _create_discount_rule_via_api(
            authenticated_client,
            name="API Discount Rule",
            discount_type="percentage",
            discount_value="15.00",
            apply_to="order",
        )
        assert data["name"] == "API Discount Rule"
        assert data["discount_type"] == "percentage"
        assert data["discount_value"] == "15.00"

    def test_coupon_creation(self, authenticated_client, workspace):
        """Test coupon creation via API (discount rule created via API first)"""
        dr = _create_discount_rule_via_api(authenticated_client, name="Coupon DR")
        valid_from = timezone.now()
        valid_until = valid_from + timedelta(days=30)

        payload = {
            "code": "SUMMER10",
            "description": "10% off summer sale",
            "discount_rule_id": dr["id"],
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "usage_limit": 100,
            "usage_limit_per_customer": 1,
            "is_active": True,
        }

        response = authenticated_client.post("/api/v1/marketing/coupons/", payload)

        assert response.status_code == 201
        assert response.data["code"] == "SUMMER10"
        assert response.data["discount_rule"]["id"] == dr["id"]

    def test_coupon_update(self, authenticated_client, workspace):
        """Test coupon update via API"""
        dr = _create_discount_rule_via_api(authenticated_client)
        valid_from = timezone.now()
        valid_until = valid_from + timedelta(days=30)

        create_res = authenticated_client.post(
            "/api/v1/marketing/coupons/",
            {
                "code": "TEST10",
                "discount_rule_id": dr["id"],
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "is_active": True,
            },
        )
        assert create_res.status_code == 201
        coupon_id = create_res.data["id"]

        response = authenticated_client.patch(
            f"/api/v1/marketing/coupons/{coupon_id}/", {"usage_limit": 200}
        )

        assert response.status_code == 200
        assert response.data["usage_limit"] == 200

    def test_gift_card_creation(self, authenticated_client, workspace, customer):
        """Test gift card creation via API (currency from finance API)"""
        currency_id = _get_currency_id_via_api(authenticated_client)

        payload = {
            "initial_value": "100.00",
            "balance": "100.00",
            "currency": currency_id,
            "is_active": True,
        }

        response = authenticated_client.post("/api/v1/marketing/gift-cards/", payload)

        assert response.status_code == 201
        assert response.data["initial_value"] == "100.00"
        assert response.data["balance"] == "100.00"
        assert response.data["code"]

    def test_gift_card_redeem(self, authenticated_client, workspace, customer):
        """Test gift card redemption via API"""
        currency_id = _get_currency_id_via_api(authenticated_client)

        create_res = authenticated_client.post(
            "/api/v1/marketing/gift-cards/",
            {
                "initial_value": "100.00",
                "balance": "100.00",
                "currency": currency_id,
                "is_active": True,
            },
        )
        assert create_res.status_code == 201
        gift_card_id = create_res.data["id"]

        response = authenticated_client.post(
            f"/api/v1/marketing/gift-cards/{gift_card_id}/redeem/",
            {"amount": "50.00"},
        )

        assert response.status_code == 200
        assert response.data["gift_card"]["balance"] == "50.00"

    def test_coupon_list_filtering(self, authenticated_client, workspace):
        """Test coupon list with filtering (all data via API)"""
        dr = _create_discount_rule_via_api(authenticated_client)
        valid_from = timezone.now()
        valid_until = valid_from + timedelta(days=30)

        authenticated_client.post(
            "/api/v1/marketing/coupons/",
            {
                "code": "ACTIVE10",
                "discount_rule_id": dr["id"],
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "is_active": True,
            },
        )
        authenticated_client.post(
            "/api/v1/marketing/coupons/",
            {
                "code": "INACTIVE20",
                "discount_rule_id": dr["id"],
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "is_active": False,
            },
        )

        response = authenticated_client.get("/api/v1/marketing/coupons/?is_active=true")

        assert response.status_code == 200
        data = response.data if isinstance(response.data, list) else response.data.get("results", [])
        assert len(data) >= 1
        assert all(c["is_active"] for c in data)

    def test_campaign_list(self, authenticated_client, workspace):
        """Test campaign list retrieval"""
        start_date = timezone.now()
        end_date = start_date + timedelta(days=30)

        for i in range(3):
            authenticated_client.post(
                "/api/v1/marketing/campaigns/",
                {
                    "name": f"Campaign {i+1}",
                    "campaign_type": "email",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "is_active": True,
                },
            )

        response = authenticated_client.get("/api/v1/marketing/campaigns/")

        assert response.status_code == 200
        data = response.data if isinstance(response.data, list) else response.data.get("results", [])
        assert len(data) >= 3

    # --- Storefront promo API (slides, featured_categories, flash_sales, group_buys) ---

    def test_storefront_promo_returns_structure(self, authenticated_client, workspace):
        """GET /api/store/promo/ returns context, available, types_present."""
        response = authenticated_client.get("/api/store/promo/?context=home")
        assert response.status_code == 200
        assert "context" in response.data
        assert "available" in response.data
        assert "types_present" in response.data
        assert response.data["context"] == "home"

    def test_storefront_promo_slides_after_campaign_display(
        self, authenticated_client, workspace
    ):
        """Create campaign + campaign display (slide) via API; GET promo returns slides."""
        start_date = timezone.now()
        end_date = start_date + timedelta(days=30)
        campaign_res = authenticated_client.post(
            "/api/v1/marketing/campaigns/",
            {
                "name": "Slide Campaign",
                "campaign_type": "email",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_active": True,
            },
        )
        assert campaign_res.status_code == 201
        campaign_id = campaign_res.data["id"]

        display_res = authenticated_client.post(
            "/api/v1/marketing/campaign-displays/",
            {
                "campaign": campaign_id,
                "display_type": "slide",
                "order": 0,
                "link_url": "https://example.com",
                "is_active": True,
            },
        )
        assert display_res.status_code == 201

        promo_res = authenticated_client.get("/api/store/promo/?context=home")
        assert promo_res.status_code == 200
        assert "slides" in promo_res.data.get("types_present", [])
        assert "slides" in promo_res.data.get("available", {})
        assert len(promo_res.data["available"]["slides"]) >= 1

    def test_storefront_promo_group_buys_after_campaign(
        self, authenticated_client, workspace
    ):
        """Create campaign with requires_participation and min_participants; GET promo returns group_buys."""
        start_date = timezone.now()
        end_date = start_date + timedelta(days=30)
        campaign_res = authenticated_client.post(
            "/api/v1/marketing/campaigns/",
            {
                "name": "Group Buy Campaign",
                "campaign_type": "email",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_active": True,
                "requires_participation": True,
                "min_participants": 5,
            },
        )
        assert campaign_res.status_code == 201

        promo_res = authenticated_client.get("/api/store/promo/?context=home")
        assert promo_res.status_code == 200
        assert "group_buys" in promo_res.data.get("types_present", [])
        group_buys = promo_res.data.get("available", {}).get("group_buys", [])
        assert any(g["min_participants"] == 5 for g in group_buys)

    def test_storefront_promo_flash_sales_after_discount_rule_and_coupon(
        self, authenticated_client, workspace
    ):
        """Create campaign, discount rule with valid_until, and coupon linking them; GET promo returns flash_sales."""
        start_date = timezone.now()
        end_date = start_date + timedelta(days=30)
        campaign_res = authenticated_client.post(
            "/api/v1/marketing/campaigns/",
            {
                "name": "Flash Campaign",
                "campaign_type": "email",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "is_active": True,
            },
        )
        assert campaign_res.status_code == 201
        campaign_id = campaign_res.data["id"]

        valid_from = timezone.now()
        valid_until = valid_from + timedelta(days=7)
        dr = _create_discount_rule_via_api(
            authenticated_client,
            name="Flash 20%",
            valid_from=valid_from,
            valid_until=valid_until,
            display_label="Flash 20% off",
        )

        coupon_res = authenticated_client.post(
            "/api/v1/marketing/coupons/",
            {
                "code": "FLASH20",
                "discount_rule_id": dr["id"],
                "campaign_id": campaign_id,
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "is_active": True,
            },
        )
        assert coupon_res.status_code == 201

        promo_res = authenticated_client.get("/api/store/promo/?context=home")
        assert promo_res.status_code == 200
        assert "flash_sales" in promo_res.data.get("types_present", [])
        flash_sales = promo_res.data.get("available", {}).get("flash_sales", [])
        assert any(f["discount_rule_id"] == dr["id"] for f in flash_sales)

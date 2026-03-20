from decimal import Decimal
from types import SimpleNamespace

import pytest

from bfg.marketing.services.promo_service import CouponService, CampaignService, StampService


# ---------------------------------------------------------------------------
# Existing test
# ---------------------------------------------------------------------------

def test_calculate_discount_applies_maximum_cap():
    service = CouponService(workspace=None, user=None)
    rule = type(
        "Rule",
        (),
        {"discount_type": "percentage", "discount_value": Decimal("20"), "maximum_discount": Decimal("15")},
    )()

    discount = service._calculate_discount(rule, Decimal("100"))
    assert discount == Decimal("15")


# ---------------------------------------------------------------------------
# CouponService.validate_coupon
# ---------------------------------------------------------------------------

def _now_minus(days=1):
    from django.utils import timezone
    from datetime import timedelta
    return timezone.now() - timedelta(days=days)


def _now_plus(days=1):
    from django.utils import timezone
    from datetime import timedelta
    return timezone.now() + timedelta(days=days)


def _make_rule(discount_type="percentage", discount_value="10", maximum_discount=None):
    return SimpleNamespace(
        discount_type=discount_type,
        discount_value=Decimal(discount_value),
        maximum_discount=Decimal(str(maximum_discount)) if maximum_discount is not None else None,
    )


@pytest.mark.django_db
def test_validate_coupon_valid_returns_true_none_amount(monkeypatch):
    service = CouponService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_rule(discount_type="percentage", discount_value="10")
    coupon = SimpleNamespace(
        valid_from=_now_minus(1),
        valid_until=_now_plus(5),
        usage_limit=None,
        times_used=0,
        discount_rule=rule,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    is_valid, msg, amount = service.validate_coupon("VALID10", customer=None, order_total=Decimal("100"))

    assert is_valid is True
    assert msg is None
    assert amount == Decimal("10")


@pytest.mark.django_db
def test_validate_coupon_expired_returns_false_with_message(monkeypatch):
    service = CouponService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_rule()
    coupon = SimpleNamespace(
        valid_from=_now_minus(10),
        valid_until=_now_minus(1),  # expired
        usage_limit=None,
        times_used=0,
        discount_rule=rule,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    is_valid, msg, amount = service.validate_coupon("EXPIRED", customer=None, order_total=Decimal("100"))

    assert is_valid is False
    assert msg is not None
    assert "expired" in msg.lower()
    assert amount is None


@pytest.mark.django_db
def test_validate_coupon_usage_limit_reached_returns_false(monkeypatch):
    service = CouponService(workspace=SimpleNamespace(id=1), user=None)

    rule = _make_rule()
    coupon = SimpleNamespace(
        valid_from=_now_minus(1),
        valid_until=_now_plus(5),
        usage_limit=5,
        times_used=5,  # exhausted
        discount_rule=rule,
    )

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.Coupon.objects",
        SimpleNamespace(get=lambda **_kw: coupon),
    )

    is_valid, msg, amount = service.validate_coupon("MAXED", customer=None, order_total=Decimal("100"))

    assert is_valid is False
    assert msg is not None
    assert "limit" in msg.lower()
    assert amount is None


@pytest.mark.django_db
def test_validate_coupon_invalid_code_returns_false(monkeypatch):
    service = CouponService(workspace=SimpleNamespace(id=1), user=None)

    class _CouponObjects:
        @staticmethod
        def get(**_kwargs):
            from bfg.marketing.models import Coupon
            raise Coupon.DoesNotExist()

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.Coupon.objects",
        _CouponObjects(),
    )

    is_valid, msg, amount = service.validate_coupon("BADCODE", customer=None, order_total=Decimal("100"))

    assert is_valid is False
    assert msg is not None
    assert amount is None


# ---------------------------------------------------------------------------
# CouponService._calculate_discount
# ---------------------------------------------------------------------------

def test_calculate_discount_percentage_normal():
    service = CouponService(workspace=None, user=None)
    rule = _make_rule(discount_type="percentage", discount_value="20")

    discount = service._calculate_discount(rule, Decimal("100"))
    assert discount == Decimal("20")


def test_calculate_discount_percentage_with_maximum_cap():
    # Covered by existing test; also verify explicitly
    service = CouponService(workspace=None, user=None)
    rule = _make_rule(discount_type="percentage", discount_value="50", maximum_discount="30")

    discount = service._calculate_discount(rule, Decimal("100"))
    assert discount == Decimal("30")


def test_calculate_discount_fixed_amount():
    service = CouponService(workspace=None, user=None)
    rule = _make_rule(discount_type="fixed_amount", discount_value="25")

    discount = service._calculate_discount(rule, Decimal("100"))
    assert discount == Decimal("25")


def test_calculate_discount_fixed_amount_exceeds_order_total():
    # Service returns the raw value without capping (caller handles cap)
    service = CouponService(workspace=None, user=None)
    rule = _make_rule(discount_type="fixed_amount", discount_value="200")

    discount = service._calculate_discount(rule, Decimal("100"))
    assert discount == Decimal("200")


# ---------------------------------------------------------------------------
# CampaignService.join_campaign
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_join_campaign_inactive_raises_value_error(monkeypatch):
    service = CampaignService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(
        id=1,
        is_active=False,
        start_date=_now_minus(1),
        end_date=_now_plus(10),
        max_participants=None,
    )

    with pytest.raises(ValueError, match="not active"):
        service.join_campaign(customer=None, campaign=campaign)


@pytest.mark.django_db
def test_join_campaign_not_started_raises_value_error():
    service = CampaignService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(
        id=1,
        is_active=True,
        start_date=_now_plus(2),  # future
        end_date=_now_plus(10),
        max_participants=None,
    )

    with pytest.raises(ValueError, match="not started"):
        service.join_campaign(customer=None, campaign=campaign)


@pytest.mark.django_db
def test_join_campaign_ended_raises_value_error():
    service = CampaignService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(
        id=1,
        is_active=True,
        start_date=_now_minus(10),
        end_date=_now_minus(1),  # ended
        max_participants=None,
    )

    with pytest.raises(ValueError, match="ended"):
        service.join_campaign(customer=None, campaign=campaign)


@pytest.mark.django_db
def test_join_campaign_max_participants_reached_raises_value_error():
    service = CampaignService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(
        id=1,
        is_active=True,
        start_date=_now_minus(1),
        end_date=_now_plus(10),
        max_participants=10,
        participations=SimpleNamespace(count=lambda: 10),  # already at limit
    )

    with pytest.raises(ValueError, match="limit"):
        service.join_campaign(customer=None, campaign=campaign)


# ---------------------------------------------------------------------------
# StampService.get_stamp_progress
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_stamp_progress_stamp_card_enough_stamps_can_redeem(monkeypatch):
    service = StampService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(config={"type": "stamp_card", "stamps_required": 5})

    class _StampQS:
        def filter(self, **_kwargs):
            return self

        def count(self):
            return 5  # exactly required

    class _RedemptionQS:
        def filter(self, **_kwargs):
            return self

        def exists(self):
            return False  # not yet redeemed

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.StampRecord.objects",
        SimpleNamespace(
            filter=lambda **kwargs: _StampQS() if kwargs.get("record_type") == "stamp" else _RedemptionQS(),
        ),
    )

    progress = service.get_stamp_progress(customer=None, campaign=campaign)

    assert progress["can_redeem"] is True
    assert progress["stamps_count"] == 5
    assert progress["already_redeemed"] is False


@pytest.mark.django_db
def test_get_stamp_progress_stamp_card_not_enough_cannot_redeem(monkeypatch):
    service = StampService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(config={"type": "stamp_card", "stamps_required": 5})

    class _StampQS:
        def filter(self, **_kwargs):
            return self

        def count(self):
            return 3  # not enough

    class _RedemptionQS:
        def filter(self, **_kwargs):
            return self

        def exists(self):
            return False

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.StampRecord.objects",
        SimpleNamespace(
            filter=lambda **kwargs: _StampQS() if kwargs.get("record_type") == "stamp" else _RedemptionQS(),
        ),
    )

    progress = service.get_stamp_progress(customer=None, campaign=campaign)

    assert progress["can_redeem"] is False
    assert progress["stamps_count"] == 3


@pytest.mark.django_db
def test_get_stamp_progress_already_redeemed_cannot_redeem(monkeypatch):
    service = StampService(workspace=SimpleNamespace(id=1), user=None)

    campaign = SimpleNamespace(config={"type": "stamp_card", "stamps_required": 3})

    class _StampQS:
        def filter(self, **_kwargs):
            return self

        def count(self):
            return 5  # more than enough

    class _RedemptionQS:
        def filter(self, **_kwargs):
            return self

        def exists(self):
            return True  # already redeemed

    monkeypatch.setattr(
        "bfg.marketing.services.promo_service.StampRecord.objects",
        SimpleNamespace(
            filter=lambda **kwargs: _StampQS() if kwargs.get("record_type") == "stamp" else _RedemptionQS(),
        ),
    )

    progress = service.get_stamp_progress(customer=None, campaign=campaign)

    assert progress["can_redeem"] is False
    assert progress["already_redeemed"] is True

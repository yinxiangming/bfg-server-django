"""Owned warehouse reservations: aggregate reserved stock is never an order identity."""
from django.db import models
from django.utils import timezone


class OrderItemStockReservation(models.Model):
    STATES = [('reserved', 'Reserved'), ('consumed', 'Consumed'), ('released', 'Released')]
    item = models.OneToOneField('shop.OrderItem', on_delete=models.PROTECT, related_name='stock_reservation')
    inventory = models.ForeignKey('shop.VariantInventory', on_delete=models.PROTECT, related_name='order_reservations')
    quantity = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=STATES, default='reserved')
    reserved_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=1), name='shop_order_reservation_positive')]

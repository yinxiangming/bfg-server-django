# -*- coding: utf-8 -*-
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

class ProductReview(models.Model):
    """Product review/rating."""
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE, related_name='product_reviews')
    product = models.ForeignKey('shop.Product', on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey('common.Customer', on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey('shop.Order', null=True, blank=True, on_delete=models.SET_NULL, related_name='reviews', help_text=_("Order associated with this review (for verified purchase)"))
    
    rating = models.PositiveSmallIntegerField(_("Rating"))  # 1-5
    title = models.CharField(_("Title"), max_length=255, blank=True)
    comment = models.TextField(_("Comment"), blank=True)
    
    # Images uploaded with review
    images = models.JSONField(_("Images"), default=list, blank=True, help_text=_("List of image URLs"))
    
    # Moderation
    is_verified_purchase = models.BooleanField(_("Verified Purchase"), default=False)
    is_approved = models.BooleanField(_("Approved"), default=False)
    
    # Engagement
    helpful_count = models.IntegerField(_("Helpful Count"), default=0, help_text=_("Number of users who found this review helpful"))
    
    created_at = models.DateTimeField(_("Created At"), default=timezone.now)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    class Meta:
        verbose_name = _("Product Review")
        verbose_name_plural = _("Product Reviews")
        ordering = ['-created_at']
        unique_together = ('product', 'customer')
    
    def __str__(self):
        return f"{self.product.name} - {self.rating} stars by {self.customer}"

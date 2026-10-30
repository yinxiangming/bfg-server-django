"""Workspace and category content policies, independent of product descriptions."""
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.dispatch import Signal
from django.dispatch import receiver
from django.db.models.signals import post_delete

from bfg.common.managers import TenantScopedModel


content_policy_changed = Signal()


class ProductContentPolicy(TenantScopedModel):
    workspace = models.ForeignKey('common.Workspace', on_delete=models.CASCADE)
    category = models.ForeignKey('shop.ProductCategory', null=True, blank=True, on_delete=models.CASCADE)
    # Non-null identity avoids MySQL's multiple-NULL unique-key behavior.
    scope_key = models.CharField(max_length=64, editable=False)
    language = models.CharField(max_length=10, default='en')
    slot = models.CharField(max_length=16, default='footer', choices=[('footer', 'Footer')])
    mode = models.CharField(max_length=10, default='own', choices=[('own', 'Own'), ('inherit', 'Inherit'), ('off', 'Off')])
    include_descendants = models.BooleanField(default=False)
    text = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        base_manager_name = 'all_objects'
        constraints = [models.UniqueConstraint(fields=['workspace', 'scope_key', 'language', 'slot'], name='shop_content_policy_scope_uniq')]
        ordering = ['scope_key', 'language']

    def clean(self):
        if self.category_id and self.category.workspace_id != self.workspace_id:
            raise ValidationError({'category': 'Category must belong to this workspace.'})
        if not self.category_id and self.mode == 'inherit':
            raise ValidationError({'mode': 'Workspace content cannot inherit.'})
        if self.enabled and self.mode == 'own' and not self.text.strip():
            raise ValidationError({'text': 'Own content requires text.'})

    def save(self, *args, **kwargs):
        from bfg.common.models import Workspace
        with transaction.atomic():
            Workspace.objects.select_for_update().get(pk=self.workspace_id)
            self.scope_key = f'category:{self.category_id}' if self.category_id else 'workspace'
            duplicate = type(self).all_objects.filter(workspace_id=self.workspace_id, scope_key=self.scope_key, language=self.language, slot=self.slot).exclude(pk=self.pk)
            if duplicate.exists():
                raise ValidationError('A policy already exists for this scope and language.')
            if self.pk:
                old = type(self).all_objects.select_for_update().get(pk=self.pk)
                if (old.workspace_id, old.category_id, old.language, old.slot) != (self.workspace_id, self.category_id, self.language, self.slot):
                    raise ValidationError('Policy scope and language are immutable; disable it and create another policy.')
                self.revision = old.revision + 1
            self.full_clean()
            kwargs.pop('update_fields', None)
            super().save(*args, **kwargs)
            content_policy_changed.send(sender=type(self), policy=self)


@receiver(post_delete, sender=ProductContentPolicy)
def content_policy_removed(sender, instance, **kwargs):
    content_policy_changed.send(sender=sender, policy=instance)

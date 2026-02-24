# -*- coding: utf-8 -*-
"""
Django admin configuration for BFG Common models.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import Workspace, User, Customer, Address, Settings, AuditLog


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'domain', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug', 'domain', 'email')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'slug', 'domain')
        }),
        (_('Contact'), {
            'fields': ('email', 'phone')
        }),
        (_('Settings'), {
            'fields': ('is_active', 'settings')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'default_workspace')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'default_workspace')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone')
    
    fieldsets = BaseUserAdmin.fieldsets + (
        (_('Additional Info'), {
            'fields': ('phone', 'avatar', 'default_workspace')
        }),
        (_('Preferences'), {
            'fields': ('language', 'timezone_name')
        }),
    )
    
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (_('Additional Info'), {
            'fields': ('phone', 'avatar', 'default_workspace', 'language')
        }),
    )


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'workspace', 'customer_number', 'balance', 'is_active', 'created_at')
    list_filter = ('workspace', 'is_active', 'is_verified', 'created_at')
    search_fields = ('user__username', 'user__email', 'customer_number', 'company_name')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user',)
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('workspace', 'user', 'customer_number')
        }),
        (_('Business Info'), {
            'fields': ('company_name', 'tax_number'),
            'classes': ('collapse',)
        }),
        (_('Financial'), {
            'fields': ('credit_limit', 'balance')
        }),
        (_('Status'), {
            'fields': ('is_active', 'is_verified', 'verified_at')
        }),
        (_('Notes'), {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'city', 'country', 'is_default', 'workspace')
    list_filter = ('workspace', 'country', 'is_default')
    search_fields = ('full_name', 'phone', 'email', 'city', 'postal_code')
    readonly_fields = ('created_at', 'updated_at', 'content_type', 'object_id')
    
    fieldsets = (
        (_('Contact'), {
            'fields': ('full_name', 'phone', 'email')
        }),
        (_('Address'), {
            'fields': ('address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country', 'latitude', 'longitude')
        }),
        (_('Settings'), {
            'fields': ('workspace', 'content_type', 'object_id', 'is_default', 'notes')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'site_name', 'default_language', 'default_currency')
    search_fields = ('workspace__name', 'site_name')
    readonly_fields = ('updated_at',)
    
    fieldsets = (
        (_('General'), {
            'fields': ('workspace', 'site_name', 'site_description', 'logo', 'favicon')
        }),
        (_('Localization'), {
            'fields': ('default_language', 'supported_languages', 'default_currency', 'default_timezone')
        }),
        (_('Contact'), {
            'fields': ('contact_email', 'support_email', 'contact_phone')
        }),
        (_('Social Media'), {
            'fields': ('facebook_url', 'twitter_url', 'instagram_url'),
            'classes': ('collapse',)
        }),
        (_('Features'), {
            'fields': ('features', 'custom_settings'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'workspace', 'object_repr', 'created_at')
    list_filter = ('action', 'workspace', 'created_at')
    search_fields = ('user__username', 'object_repr', 'description')
    readonly_fields = ('workspace', 'user', 'action', 'description', 'content_type', 'object_id', 
                      'object_repr', 'changes', 'ip_address', 'user_agent', 'created_at')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False

# -*- coding: utf-8 -*-
from django.urls import path

from apps.geo import views

urlpatterns = [
    path('address/config/', views.address_config, name='geo-address-config'),
    path('address/suggest/', views.address_suggest, name='geo-address-suggest'),
    path('address/resolve/', views.address_resolve, name='geo-address-resolve'),
    path('address/reverse/', views.address_reverse, name='geo-address-reverse'),
]

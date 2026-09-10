# -*- coding: utf-8 -*-
"""
Workspace onboarding: the checklist, the country/industry templates and the
service that applies them.

``provision_workspace`` fills a workspace in from the command line. This package
is the same job done from the admin UI by the person who owns the shop: it
reports how far along the workspace is, and it can write the boring 80% —
currency, tax, categories, legal pages, menus — from a country + industry pick.
"""

from .checklist import evaluate, STEPS  # noqa: F401
from .service import OnboardingService  # noqa: F401

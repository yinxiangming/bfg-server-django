# -*- coding: utf-8 -*-
"""
Seed CampaignDisplay (promo displays) for a workspace.
Usage: python manage.py seed_promo_displays [--workspace=SLUG]
"""

from django.core.management.base import BaseCommand
from bfg.common.models import Workspace
from bfg.marketing.models import Campaign
from bfg.marketing.seed_data import create_campaign_displays


class Command(BaseCommand):
    help = 'Seed promo displays (slides, category_entry, featured) for a workspace'

    def add_arguments(self, parser):
        parser.add_argument(
            '--workspace',
            type=str,
            default='demo',
            help='Workspace slug to seed (default: demo)',
        )

    def handle(self, *args, **options):
        slug = options['workspace']
        workspace = Workspace.objects.filter(slug=slug).first()
        if not workspace:
            self.stdout.write(self.style.ERROR(f'Workspace slug="{slug}" not found.'))
            return
        campaigns = list(Campaign.objects.filter(workspace=workspace).order_by('id')[:1])
        created = create_campaign_displays(workspace, campaigns, self.stdout, self.style)
        self.stdout.write(self.style.SUCCESS(f'\nDone. Created {len(created)} campaign display(s) for workspace "{workspace.name}".'))

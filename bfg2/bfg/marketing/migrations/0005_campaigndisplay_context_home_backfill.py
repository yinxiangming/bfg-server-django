# -*- coding: utf-8 -*-
"""
Pin pre-existing displays to the home page.

Before `context` existed, the only storefront surface that read promo displays
was the home page, so that is where every current row appears. Leaving them
blank would newly opt them into every page that asks — including the category
page — which is a visible change nobody asked for. New rows may still be left
blank to mean "all pages".
"""

from django.db import migrations


def pin_existing_to_home(apps, schema_editor):
    CampaignDisplay = apps.get_model('marketing', 'CampaignDisplay')
    CampaignDisplay.objects.filter(context='').update(context='home')


def unpin(apps, schema_editor):
    CampaignDisplay = apps.get_model('marketing', 'CampaignDisplay')
    CampaignDisplay.objects.filter(context='home').update(context='')


class Migration(migrations.Migration):

    dependencies = [
        ('marketing', '0004_campaigndisplay_context'),
    ]

    operations = [
        migrations.RunPython(pin_existing_to_home, unpin),
    ]

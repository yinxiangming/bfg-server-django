# Generated manually for Platform-controlled exchange-rate corrections.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0005_rename_finance_tra_wallet__idx_finance_tra_wallet__4bc174_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="exchangerate",
            name="entered_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="entered_exchange_rates", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="exchangerate",
            name="source",
            field=models.CharField(choices=[("feed", "Reference feed"), ("manual", "Manual")], default="feed", max_length=20, verbose_name="Source"),
        ),
    ]

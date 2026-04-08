# -*- coding: utf-8 -*-
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("common", "0001_initial"),
        ("shop", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalChannel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel_type", models.CharField(
                    choices=[
                        ("trademe", "TradeMe"),
                        ("shopify", "Shopify"),
                        ("ebay", "eBay"),
                        ("custom", "Custom"),
                    ],
                    max_length=20,
                    verbose_name="Channel Type",
                )),
                ("name", models.CharField(max_length=100, verbose_name="Name")),
                ("credentials", models.JSONField(default=dict, verbose_name="Credentials")),
                ("config", models.JSONField(blank=True, default=dict, verbose_name="Config")),
                ("is_active", models.BooleanField(default=True, verbose_name="Active")),
                ("last_sync_at", models.DateTimeField(blank=True, null=True, verbose_name="Last Sync At")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Created At")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated At")),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="external_channels",
                    to="common.workspace",
                    verbose_name="Workspace",
                )),
            ],
            options={
                "verbose_name": "External Channel",
                "verbose_name_plural": "External Channels",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ExternalListing",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(blank=True, max_length=100, verbose_name="External ID")),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("active", "Active"),
                        ("ended", "Ended"),
                        ("error", "Error"),
                        ("relisting", "Relisting"),
                    ],
                    default="pending",
                    max_length=20,
                    verbose_name="Status",
                )),
                ("mapped_data", models.JSONField(blank=True, default=dict, verbose_name="Mapped Data")),
                ("channel_meta", models.JSONField(blank=True, default=dict, verbose_name="Channel Meta")),
                ("expires_at", models.DateTimeField(blank=True, null=True, verbose_name="Expires At")),
                ("last_synced", models.DateTimeField(blank=True, null=True, verbose_name="Last Synced")),
                ("error_detail", models.TextField(blank=True, verbose_name="Error Detail")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Created At")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Updated At")),
                ("channel", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="listings",
                    to="channels.externalchannel",
                    verbose_name="Channel",
                )),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="external_listings",
                    to="shop.product",
                    verbose_name="Product",
                )),
            ],
            options={
                "verbose_name": "External Listing",
                "verbose_name_plural": "External Listings",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="externallisting",
            constraint=models.UniqueConstraint(
                fields=("product", "channel"),
                name="unique_product_channel",
            ),
        ),
        migrations.CreateModel(
            name="ExternalFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=100, unique=True, verbose_name="External ID")),
                ("author", models.CharField(max_length=100, verbose_name="Author")),
                ("rating", models.IntegerField(blank=True, null=True, verbose_name="Rating")),
                ("feedback_type", models.CharField(
                    choices=[
                        ("positive", "Positive"),
                        ("neutral", "Neutral"),
                        ("negative", "Negative"),
                    ],
                    max_length=20,
                    verbose_name="Feedback Type",
                )),
                ("comment", models.TextField(blank=True, verbose_name="Comment")),
                ("received_at", models.DateTimeField(verbose_name="Received At")),
                ("reply", models.TextField(blank=True, verbose_name="Reply")),
                ("replied_at", models.DateTimeField(blank=True, null=True, verbose_name="Replied At")),
                ("is_replied", models.BooleanField(default=False, verbose_name="Is Replied")),
                ("listing", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="feedback",
                    to="channels.externallisting",
                    verbose_name="Listing",
                )),
            ],
            options={
                "verbose_name": "External Feedback",
                "verbose_name_plural": "External Feedback",
                "ordering": ["-received_at"],
            },
        ),
        migrations.CreateModel(
            name="ExternalQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=100, unique=True, verbose_name="External ID")),
                ("question_text", models.TextField(verbose_name="Question")),
                ("asker", models.CharField(max_length=100, verbose_name="Asker")),
                ("asked_at", models.DateTimeField(verbose_name="Asked At")),
                ("answer_text", models.TextField(blank=True, verbose_name="Answer")),
                ("answered_at", models.DateTimeField(blank=True, null=True, verbose_name="Answered At")),
                ("answer_status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("answered", "Answered"),
                        ("skipped", "Skipped"),
                    ],
                    default="pending",
                    max_length=20,
                    verbose_name="Answer Status",
                )),
                ("is_auto_answered", models.BooleanField(default=False, verbose_name="Auto Answered")),
                ("listing", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="questions",
                    to="channels.externallisting",
                    verbose_name="Listing",
                )),
            ],
            options={
                "verbose_name": "External Question",
                "verbose_name_plural": "External Questions",
                "ordering": ["-asked_at"],
            },
        ),
        migrations.CreateModel(
            name="ChannelFAQRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("keywords", models.JSONField(default=list, verbose_name="Keywords")),
                ("answer", models.TextField(verbose_name="Answer")),
                ("priority", models.IntegerField(default=0, verbose_name="Priority")),
                ("is_active", models.BooleanField(default=True, verbose_name="Active")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="Created At")),
                ("channel", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="faq_rules",
                    to="channels.externalchannel",
                    verbose_name="Channel",
                )),
            ],
            options={
                "verbose_name": "Channel FAQ Rule",
                "verbose_name_plural": "Channel FAQ Rules",
                "ordering": ["-priority"],
            },
        ),
    ]

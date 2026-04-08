# -*- coding: utf-8 -*-
"""
Ensure common_workspace.domain exists.

Some deployments removed this column while the model/migration state still
expected it (or diverged from 0001_initial). Re-add the column when missing.
"""

from django.db import migrations


def add_workspace_domain_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "mysql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'common_workspace'
              AND COLUMN_NAME = 'domain'
            """
        )
        if cursor.fetchone()[0]:
            return
        cursor.execute(
            "ALTER TABLE common_workspace ADD COLUMN domain VARCHAR(255) NOT NULL DEFAULT ''"
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0006_workspacedomain"),
    ]

    operations = [
        migrations.RunPython(add_workspace_domain_if_missing, noop_reverse),
    ]

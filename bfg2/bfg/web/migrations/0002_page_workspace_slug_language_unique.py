# Generated manually for multi-workspace page slugs

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('web', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='page',
            name='slug',
            field=models.SlugField(max_length=255, verbose_name='Slug'),
        ),
        migrations.AlterUniqueTogether(
            name='page',
            unique_together={('workspace', 'slug', 'language')},
        ),
    ]

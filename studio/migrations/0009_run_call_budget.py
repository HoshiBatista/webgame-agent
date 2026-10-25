from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0008_completion_policy")]

    operations = [
        migrations.AddField("run", "model_call_limit", models.PositiveSmallIntegerField(null=True, blank=True)),
        migrations.AddField("run", "model_call_deadline", models.DateTimeField(null=True, blank=True)),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0004_invocation_provider_metadata")]

    operations = [
        migrations.AddField(model_name="run", name="allow_model_calls", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="invocation", name="raw_response", field=models.JSONField(null=True)),
    ]

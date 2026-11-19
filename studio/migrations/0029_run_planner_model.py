from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0028_pro_variant_batches")]

    operations = [
        migrations.AddField(
            model_name="run",
            name="planner_model",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]

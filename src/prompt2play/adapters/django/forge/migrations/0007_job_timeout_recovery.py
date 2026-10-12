from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forge", "0006_job_budget_usd_job_cost_nano_job_cost_upper_nano_and_more"),
    ]
    operations = [
        migrations.AlterField(
            model_name="job",
            name="budget_seconds",
            field=models.PositiveIntegerField(null=True, blank=True, default=None),
        ),
        migrations.AddField(
            model_name="job", name="resume_count", field=models.PositiveSmallIntegerField(default=0)
        ),
    ]

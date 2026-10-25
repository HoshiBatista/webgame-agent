from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0005_saved_response_recovery")]

    operations = [
        migrations.AddField(
            model_name="checkreport", name="stages", field=models.JSONField(default=list),
        ),
        # Existing jobs retain their original allowance, including in-flight jobs.
        migrations.AddField(
            model_name="run", name="max_repair_attempts",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="run", name="max_repair_attempts",
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.CheckConstraint(
                condition=models.Q(max_repair_attempts__lte=3), name="studio_run_repair_limit"
            ),
        ),
    ]

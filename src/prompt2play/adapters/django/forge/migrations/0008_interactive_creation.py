from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forge", "0007_job_timeout_recovery")]
    operations = [
        migrations.AddField(
            model_name="job",
            name="creation_mode",
            field=models.CharField(
                choices=[("lite", "lite"), ("pro", "pro")], default="lite", max_length=4
            ),
        ),
        migrations.AddField(model_name="job", name="review", field=models.JSONField(default=dict)),
        migrations.AlterField(
            model_name="job",
            name="status",
            field=models.CharField(
                choices=[
                    (s, s)
                    for s in ["queued", "running", "waiting", "completed", "failed", "cancelled"]
                ],
                db_index=True,
                default="queued",
                max_length=12,
            ),
        ),
        migrations.RemoveConstraint(model_name="job", name="one_active_job_per_project"),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(status__in=["queued", "running", "waiting"]),
                name="one_active_job_per_project",
            ),
        ),
    ]

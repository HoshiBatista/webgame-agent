from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forge", "0008_interactive_creation")]
    operations = [
        migrations.AddField(
            model_name="job",
            name="playthrough_mode",
            field=models.CharField(
                max_length=10, choices=[("manual", "manual"), ("auto", "auto")], default="auto"
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="job",
            name="playthrough_mode",
            field=models.CharField(
                max_length=10, choices=[("manual", "manual"), ("auto", "auto")], default="manual"
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0007_model_profiles")]

    operations = [
        migrations.AddField("run", "completion_policy", models.PositiveSmallIntegerField(default=1)),
        migrations.AlterField("run", "completion_policy", models.PositiveSmallIntegerField(default=2)),
        migrations.AddField("checkreport", "checks", models.JSONField(default=list)),
        migrations.AddField("checkreport", "assessment", models.JSONField(default=dict)),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0013_merge_titles_and_compact")]
    operations = [
        migrations.AddField(model_name="run", name="generation_strategy",
                            field=models.CharField(default="lite", max_length=16)),
        migrations.AddField(model_name="run", name="planning_required",
                            field=models.BooleanField(default=False)),
        migrations.AddField(model_name="run", name="game_plan", field=models.JSONField(default=dict)),
    ]

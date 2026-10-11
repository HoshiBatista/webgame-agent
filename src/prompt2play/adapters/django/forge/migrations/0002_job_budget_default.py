from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("forge", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="job",
            name="budget_tokens",
            field=models.PositiveIntegerField(default=400000),
        )
    ]

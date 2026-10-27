from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0019_remove_preference_suggest_templates")]

    operations = [
        migrations.AlterField(
            model_name="prompttemplate", name="title", field=models.CharField(max_length=60)
        ),
    ]

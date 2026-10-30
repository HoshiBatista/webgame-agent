from django.db import migrations, models


def use_pro_for_unset_preferences(apps, schema_editor):
    Preference = apps.get_model("studio", "Preference")
    Preference.objects.using(schema_editor.connection.alias).filter(model_profile="").update(model_profile="pro")


class Migration(migrations.Migration):
    dependencies = [("studio", "0020_template_title_60")]

    operations = [
        migrations.AlterField(
            model_name="preference",
            name="model_profile",
            field=models.CharField(blank=True, default="pro", max_length=10),
        ),
        migrations.RunPython(use_pro_for_unset_preferences, migrations.RunPython.noop),
    ]

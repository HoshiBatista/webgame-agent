from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("studio", "0018_personal_templates")]

    operations = [
        migrations.RemoveField(model_name="preference", name="suggest_templates"),
    ]

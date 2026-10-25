from django.db import migrations, models


def preserve_existing_titles(apps, schema_editor):
    chat = apps.get_model("studio", "Chat")
    # Existing nonempty names have no reliable provenance; preserve them conservatively.
    chat.objects.exclude(title="").update(title_is_custom=True)
    chat.objects.filter(title="").update(title="Новая игра")


class Migration(migrations.Migration):
    dependencies = [("studio", "0010_check_review_required")]

    operations = [
        migrations.AddField(
            model_name="chat", name="title_is_custom", field=models.BooleanField(default=False)
        ),
        migrations.RunPython(preserve_existing_titles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="chat",
            name="title",
            field=models.CharField(blank=True, default="Новая игра", max_length=160),
        ),
    ]

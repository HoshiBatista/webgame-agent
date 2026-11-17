from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('studio', '0025_run_pro_parallel')]
    operations = [
        migrations.AddField(model_name='run', name='pro_parallel_version',
                            field=models.PositiveSmallIntegerField(default=1)),
    ]

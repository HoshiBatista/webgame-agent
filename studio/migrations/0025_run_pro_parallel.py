from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('studio', '0024_validation_run_fence')]
    operations = [
        migrations.AddField(model_name='run', name='pro_parallel', field=models.BooleanField(default=False)),
        migrations.RemoveConstraint(model_name='run', name='studio_run_repair_limit'),
        migrations.AddConstraint(model_name='run', constraint=models.CheckConstraint(
            condition=models.Q(max_repair_attempts__lte=3) | models.Q(pro_parallel=True, max_repair_attempts__lte=5),
            name='studio_run_repair_limit')),
    ]

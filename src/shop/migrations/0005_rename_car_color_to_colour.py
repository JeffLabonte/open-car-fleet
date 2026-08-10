from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0004_car_color'),
    ]

    operations = [
        migrations.RenameField(
            model_name='car',
            old_name='color',
            new_name='colour',
        ),
    ]

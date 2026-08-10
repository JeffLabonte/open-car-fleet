from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0007_alter_car_colour_reportattachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="additional_information",
            field=models.TextField(blank=True),
        ),
    ]

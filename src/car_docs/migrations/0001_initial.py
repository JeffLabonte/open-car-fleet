from django.db import migrations, models
import django.db.models.deletion


def create_car_doc_model(apps, schema_editor):
    Car = apps.get_model('shop', 'Car')
    if not Car._meta.db_table:
        return


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('shop', '0008_report_additional_information'),
    ]

    operations = [
        migrations.CreateModel(
            name='CarDoc',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('content', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('car', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='docs', to='shop.car')),
            ],
            options={
                'ordering': ['-updated_at', '-created_at'],
            },
        ),
    ]

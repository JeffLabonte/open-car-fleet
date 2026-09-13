from django.test import TestCase
from django.urls import reverse
from shop.forms import CarCreateForm
from shop.importers import CSVImporter
from shop.importers import ImportContext
from shop.models.car import Car
from shop.models.car import CarPart
from shop.models.garage import Garage
from shop.models.garage import GarageMembership
from shop.models.job import WorkJob
from shop.models.user import ShopUser


class CarPartStatusTrackingTests(TestCase):
    def setUp(self) -> None:
        self.garage = Garage.objects.create(name='North Garage')
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Corolla',
            colour='Blue',
            year=2022,
            vin='1HGBH41JXMN109186',
            license_plate='ABC123',
        )

    def test_part_status_changes_are_recorded_with_timestamps(self):
        part = CarPart.objects.create(
            car=self.car,
            name='Brake pads',
            status=CarPart.STATUS_NEW,
            notes='Initial issue spotted on inspection.',
        )

        self.assertEqual(part.status, CarPart.STATUS_NEW)
        self.assertEqual(part.status_history.count(), 1)

        part.update_status(CarPart.STATUS_ORDERED, note='Ordered replacement set from supplier.')
        part.refresh_from_db()

        self.assertEqual(part.status, CarPart.STATUS_ORDERED)
        self.assertEqual(part.status_history.count(), 2)

        first_event = part.status_history.order_by('changed_at').first()
        second_event = part.status_history.order_by('changed_at').last()

        self.assertEqual(first_event.previous_status, '')
        self.assertEqual(first_event.new_status, CarPart.STATUS_NEW)
        self.assertIsNotNone(first_event.changed_at)

        self.assertEqual(second_event.previous_status, CarPart.STATUS_NEW)
        self.assertEqual(second_event.new_status, CarPart.STATUS_ORDERED)
        self.assertEqual(second_event.note, 'Ordered replacement set from supplier.')
        self.assertIsNotNone(second_event.changed_at)


class ColourFieldTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='colour-owner',
            email='colour-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Colour Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )

    def test_car_persists_colour_field(self):
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            colour='Noir',
            vin='JTDKB20U793512346',
        )
        car.refresh_from_db()
        self.assertEqual(car.colour, 'Noir')

    def test_car_create_form_includes_colour_field_with_british_label(self):
        self.assertIn('colour', CarCreateForm.base_fields)
        form = CarCreateForm(user=self.user)
        self.assertEqual(form.fields['colour'].label, 'Colour')

    def test_importer_reads_colour_key_from_record(self):
        importer = CSVImporter()
        result = importer.import_records(
            Car,
            [{
                'make': 'Toyota',
                'model': 'Yaris',
                'colour': 'Blanc',
                'vin': 'JTDKB20U793512347',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        car = Car.objects.get(vin='JTDKB20U793512347')
        self.assertEqual(car.colour, 'Blanc')

    def test_car_list_renders_colour_label_and_value(self):
        self.client.force_login(self.user)
        Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            colour='Noir',
            vin='JTDKB20U793512348',
        )

        response = self.client.get(reverse('shop-car-list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Colour:', response.content)
        self.assertIn(b'Noir', response.content)

    def test_car_detail_renders_colour_label_and_value(self):
        self.client.force_login(self.user)
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            colour='Noir',
            vin='JTDKB20U793512349',
        )

        response = self.client.get(reverse('shop-car-detail', args=[car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<dt>Colour</dt>', response.content)
        self.assertIn(b'Noir', response.content)

    def test_car_detail_hides_done_and_cancelled_work_jobs_by_default(self):
        self.client.force_login(self.user)
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            vin='JTDKB20U793512349',
        )
        WorkJob.objects.create(car=car, title='Open job', status=WorkJob.STATUS_PENDING)
        WorkJob.objects.create(car=car, title='Done job', status=WorkJob.STATUS_DONE)
        WorkJob.objects.create(car=car, title='Cancelled job', status=WorkJob.STATUS_CANCELLED)

        response = self.client.get(reverse('shop-car-detail', args=[car.pk]))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Open job', content)
        self.assertNotIn('Done job', content)
        self.assertNotIn('Cancelled job', content)
        self.assertIn('Show done/cancelled', content)

    def test_car_detail_show_done_reveals_done_and_cancelled_work_jobs(self):
        self.client.force_login(self.user)
        car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            vin='JTDKB20U793512349',
        )
        WorkJob.objects.create(car=car, title='Open job', status=WorkJob.STATUS_PENDING)
        WorkJob.objects.create(car=car, title='Done job', status=WorkJob.STATUS_DONE)
        WorkJob.objects.create(car=car, title='Cancelled job', status=WorkJob.STATUS_CANCELLED)

        response = self.client.get(reverse('shop-car-detail', args=[car.pk]), data={'show_done': '1'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Open job', content)
        self.assertIn('Done job', content)
        self.assertIn('Cancelled job', content)
        self.assertIn('Hide done/cancelled', content)

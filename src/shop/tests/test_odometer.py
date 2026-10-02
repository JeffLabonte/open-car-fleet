from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from shop.forms import CarCreateForm, CarUpdateForm, ReportForm
from shop.importers import CSVImporter, ImportContext
from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership
from shop.models.report import Report
from shop.models.user import ShopUser
from shop.services import update_car_odometer_from_report


class OdometerUpdateTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='odometer-owner',
            email='odometer-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Odometer Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='1HGCM82633A004352',
        )

    def _report_data(self, mileage: str, job_name: str = 'Service') -> dict:
        return {
            'mileage': mileage,
            'job_name': job_name,
            'date_done': '2026-08-20',
            'external_links': '',
            'note': '',
            'additional_information': '',
        }

    def test_create_report_with_higher_mileage_updates_car_odometer(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data=self._report_data('50000'),
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 50000)
        report = Report.objects.get(car=self.car)
        self.assertEqual(report.mileage, 50000)

    def test_create_report_with_lower_or_equal_mileage_leaves_car_unchanged(self):
        self.car.mileage = 50000
        self.car.save(update_fields=['mileage'])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data=self._report_data('40000'),
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 50000)

    def test_create_report_without_mileage_leaves_car_unchanged(self):
        self.car.mileage = 50000
        self.car.save(update_fields=['mileage'])
        self.client.force_login(self.owner)
        data = self._report_data('')
        data['mileage'] = ''

        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data=data,
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 50000)

    def test_failed_report_creation_rolls_back_car_odometer_update(self):
        self.car.mileage = 10000
        self.car.save(update_fields=['mileage'])
        self.client.force_login(self.owner)

        with patch('shop.views.save_attachments', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse('shop-report-create', args=[self.car.pk]),
                    data=self._report_data('20000'),
                )

        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 10000)
        self.assertFalse(Report.objects.filter(car=self.car).exists())

    def test_update_report_with_higher_mileage_updates_car_odometer(self):
        self.car.mileage = 10000
        self.car.save(update_fields=['mileage'])
        report = Report.objects.create(car=self.car, job_name='Service', date_done='2026-08-20', mileage=10000)
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-report-update', args=[self.car.pk, report.pk]),
            data=self._report_data('15000'),
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 15000)

    def test_update_report_with_lower_mileage_leaves_car_odometer_unchanged(self):
        self.car.mileage = 50000
        self.car.save(update_fields=['mileage'])
        report = Report.objects.create(car=self.car, job_name='Service', date_done='2026-08-20', mileage=50000)
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-report-update', args=[self.car.pk, report.pk]),
            data=self._report_data('30000'),
        )

        self.assertEqual(response.status_code, 302)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 50000)

    def test_report_form_shows_current_odometer_help_text(self):
        self.car.mileage = 12345
        form = ReportForm(car=self.car)
        self.assertIn('12345', str(form.fields['mileage'].help_text))

    def test_report_form_shows_unknown_when_car_has_no_odometer(self):
        self.car.mileage = None
        form = ReportForm(car=self.car)
        self.assertIn('unknown', str(form.fields['mileage'].help_text))

    def test_car_create_form_excludes_mileage_field(self):
        self.assertNotIn('mileage', CarCreateForm.base_fields)

    def test_car_update_form_excludes_mileage_field(self):
        self.assertNotIn('mileage', CarUpdateForm.base_fields)

    def test_service_helper_updates_car_only_for_higher_mileage(self):
        report = Report.objects.create(car=self.car, job_name='Service', date_done='2026-08-20', mileage=10000)
        self.assertTrue(update_car_odometer_from_report(report))
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 10000)

        report.mileage = 5000
        self.assertFalse(update_car_odometer_from_report(report))
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 10000)

    def test_csv_report_import_with_higher_mileage_updates_car_odometer(self):
        self.car.mileage = 10000
        self.car.save(update_fields=['mileage'])
        importer = CSVImporter()

        result = importer.import_records(
            Report,
            [{
                'car': str(self.car.pk),
                'job_name': 'Imported service',
                'date_done': '2026-08-20',
                'mileage': '25000',
            }],
            context=ImportContext(garage=self.garage, car=self.car),
        )

        self.assertFalse(result.has_errors)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 25000)

    def test_csv_report_import_with_lower_mileage_leaves_car_unchanged(self):
        self.car.mileage = 50000
        self.car.save(update_fields=['mileage'])
        importer = CSVImporter()

        result = importer.import_records(
            Report,
            [{
                'car': str(self.car.pk),
                'job_name': 'Imported service',
                'date_done': '2026-08-20',
                'mileage': '10000',
            }],
            context=ImportContext(garage=self.garage, car=self.car),
        )

        self.assertFalse(result.has_errors)
        self.car.refresh_from_db()
        self.assertEqual(self.car.mileage, 50000)

    def test_csv_car_import_ignores_mileage_column(self):
        importer = CSVImporter()

        result = importer.import_records(
            Car,
            [{
                'make': 'Toyota',
                'model': 'Yaris',
                'vin': 'JTDKB20U793512360',
                'mileage': '99999',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        car = Car.objects.get(vin='JTDKB20U793512360')
        self.assertIsNone(car.mileage)
        self.assertTrue(any('mileage' in warning.message for warning in result.warnings))

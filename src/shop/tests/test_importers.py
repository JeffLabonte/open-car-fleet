import tempfile
import uuid
from datetime import date
from io import StringIO
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook
from shop.importers import CSVImporter
from shop.importers import ImportContext
from shop.importers import ImportValidationError
from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.garage import Garage
from shop.models.garage import GarageMembership
from shop.models.garage import KnownShop
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser


class CSVImporterTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='import-owner',
            email='import-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Import Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.importer = CSVImporter()

    def test_car_dry_run_requires_target_garage_and_does_not_persist(self):
        result = self.importer.import_records(
            Car,
            [{'make': 'Toyota', 'model': 'Yaris', 'vin': 'JTDKB20U793512345'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        self.assertEqual(Car.objects.count(), 0)

    def test_report_import_parses_lists_and_persists(self):
        car = Car.objects.create(garage=self.garage, make='Honda', model='Civic', vin='2HGFG12698H512345')

        result = self.importer.import_records(
            Report,
            [{
                'car': str(car.pk),
                'job_name': 'Brake service',
                'date_done': '2026-08-01',
                'documents': 'invoice.pdf\nchecklist.pdf',
                'photos': 'before.jpg\nafter.jpg',
                'mileage': '12345',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.created_count, 1)
        report = Report.objects.get(job_name='Brake service')
        self.assertEqual(report.mileage, 12345)
        document_links = list(
            report.attachments.filter(source_type=Attachment.SOURCE_EXTERNAL, kind='document')
            .values_list('display_name', flat=True)
        )
        photo_links = list(
            report.attachments.filter(source_type=Attachment.SOURCE_EXTERNAL, kind='image')
            .values_list('display_name', flat=True)
        )
        self.assertEqual(document_links, ['invoice.pdf', 'checklist.pdf'])
        self.assertEqual(photo_links, ['before.jpg', 'after.jpg'])
        self.assertEqual(Attachment.objects.filter(url__gt='').count(), 0)

    def test_report_import_maps_url_values_to_external_links(self):
        car = Car.objects.create(garage=self.garage, make='Honda', model='Fit', vin='JHMGE88478S012345')

        result = self.importer.import_records(
            Report,
            [{
                'car': str(car.pk),
                'job_name': 'Brake service',
                'date_done': '2026-08-02',
                'documents': 'https://example.com/invoice.pdf',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertFalse(result.has_errors)
        report = Report.objects.get(job_name='Brake service')
        attachment = report.attachments.get()
        self.assertEqual(attachment.url, 'https://example.com/invoice.pdf')
        self.assertEqual(attachment.display_name, 'invoice.pdf')
        self.assertEqual(attachment.kind, 'document')

    def test_report_import_rejects_unsafe_attachment_links(self):
        car = Car.objects.create(garage=self.garage, make='Honda', model='Fit', vin='JHMGE88478S012346')

        result = self.importer.import_records(
            Report,
            [{
                'car': str(car.pk),
                'job_name': 'Brake service',
                'date_done': '2026-08-03',
                'documents': 'javascript:alert(1)',
            }],
            context=ImportContext(garage=self.garage),
        )

        self.assertTrue(result.has_errors)
        self.assertIn('Entries must be URLs', result.errors[0].message)

    def test_workjob_import_rejects_unknown_car(self):
        result = self.importer.import_records(
            WorkJob,
            [{'car': 'missing-car', 'title': 'Oil change'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )

        self.assertTrue(result.has_errors)
        self.assertIn('Car not found', result.errors[0].message)

    def test_workjob_import_requires_garage_scope(self):
        car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512345',
        )

        result = self.importer.import_records(
            WorkJob,
            [{'car': str(car.pk), 'title': 'Oil change'}],
            context=ImportContext(),
            dry_run=True,
        )

        self.assertTrue(result.has_errors)
        self.assertIn('target garage or car context', result.errors[0].message)

    def test_car_resolver_handles_malformed_uuid_without_leaking_validation_error(self):
        result = self.importer.import_records(
            WorkJob,
            [{'car': '00000000-0000-0000-0000-invalid', 'title': 'Oil change'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )

        self.assertTrue(result.has_errors)
        self.assertIn('Car not found', result.errors[0].message)


class ImportCsvCommandTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='command-owner',
            email='command-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Command Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )

    def test_car_import_command_dry_run_validates_without_persisting(self):
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('make,model,vin\nMazda,3,JM1BK323171512345\n')
            temp_path = handle.name

        output = StringIO()
        try:
            call_command(
                'import_csv',
                'Car',
                temp_path,
                '--garage',
                str(self.garage.pk),
                '--dry-run',
                stdout=output,
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)

        self.assertIn('Dry run complete', output.getvalue())
        self.assertEqual(Car.objects.count(), 0)

    def test_import_command_rejects_invalid_garage_uuid(self):
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('make,model,vin\nMazda,3,JM1BK323171512345\n')
            temp_path = handle.name

        try:
            with self.assertRaises(CommandError):
                call_command('import_csv', 'Car', temp_path, '--garage', 'not-a-uuid')
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_import_command_rejects_non_positive_batch_size(self):
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('make,model,vin\nMazda,3,JM1BK323171512345\n')
            temp_path = handle.name

        try:
            with self.assertRaises(CommandError):
                call_command(
                    'import_csv',
                    'Car',
                    temp_path,
                    '--garage',
                    str(self.garage.pk),
                    '--batch-size',
                    '0',
                )
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_export_garage_command_writes_excel_file(self):
        Car.objects.create(
            garage=self.garage,
            usual_name='Command Export Car',
            make='Mazda',
            model='3',
            vin='JM1BK323171512345',
        )
        output = StringIO()

        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as handle:
            output_path = Path(handle.name)
        output_path.unlink(missing_ok=True)

        try:
            call_command(
                'export_garage',
                str(self.garage.pk),
                '--output',
                str(output_path),
                stdout=output,
            )
            self.assertTrue(output_path.exists())
            workbook = load_workbook(filename=str(output_path))
            self.assertIn('cars_import', workbook.sheetnames)
            cars_sheet = workbook['cars_import']
            rows = list(cars_sheet.iter_rows(min_row=2, values_only=True))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][3], 'Mazda')
        finally:
            output_path.unlink(missing_ok=True)

    def test_export_garage_command_errors_for_unknown_garage(self):
        with self.assertRaises(CommandError):
            call_command('export_garage', str(uuid.uuid4()))

    def test_export_garage_command_rejects_invalid_garage_uuid(self):
        with self.assertRaises(CommandError):
            call_command('export_garage', 'not-a-uuid')


class GarageImportViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='garage-owner',
            email='garage-owner@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='garage-member',
            email='garage-member@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Upload Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.member,
            role=GarageMembership.ROLE_MEMBER,
        )

    def test_non_manager_is_redirected_from_garage_import(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-garage-import', args=[self.garage.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

    def test_manager_can_dry_run_car_import_from_upload(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'cars.csv',
            b'make,model,vin\nSubaru,Outback,4S4BSENC0J3351234',
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': upload,
                'dry_run': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any('Dry run complete' in str(message) for message in messages))
        self.assertEqual(Car.objects.count(), 0)

    def test_manager_can_import_cars_into_selected_garage(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'cars.csv',
            b'make,model,vin\nFord,Focus,1FAHP3F28CL512345',
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': upload,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        car = Car.objects.get(vin='1FAHP3F28CL512345')
        self.assertEqual(car.garage, self.garage)


class CarImportViewTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='car-owner',
            email='car-owner@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='car-member',
            email='car-member@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Car Import Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.member,
            role=GarageMembership.ROLE_MEMBER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            usual_name='Daily Driver',
            make='Toyota',
            model='Corolla',
            vin='2T1BURHE5JC512345',
        )

    def test_non_manager_is_redirected_from_car_import(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-car-import', args=[self.car.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-car-detail', args=[self.car.pk]))

    def test_manager_can_dry_run_workjob_import_for_selected_car(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'workjobs.csv',
            b'title,planned_date\nOil change,2026-08-02',
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_type': 'workjob',
                'import_file': upload,
                'dry_run': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context['messages'])
        self.assertTrue(any('Dry run complete' in str(message) for message in messages))
        self.assertEqual(WorkJob.objects.count(), 0)

    def test_manager_can_import_report_for_selected_car_without_car_field(self):
        self.client.force_login(self.owner)
        upload = SimpleUploadedFile(
            'reports.csv',
            b'job_name,date_done,note\nBrake service,2026-08-03,Pads replaced',
            content_type='text/csv',
        )

        response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_type': 'report',
                'import_file': upload,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        report = Report.objects.get(job_name='Brake service')
        self.assertEqual(report.car, self.car)


class ImporterCoverageTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='importer-owner',
            email='importer-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.garage = Garage.objects.create(name='Importer Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512348',
            year=2022,
        )

    def test_parse_csv_file_handles_missing_and_undecodable_files(self):
        importer = CSVImporter()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('make,model,vin\nToyota,Yaris,JTDKB20U793512346\n')
            path = Path(f.name)
        try:
            records = importer.parse_csv_file(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['make'], 'Toyota')
        finally:
            path.unlink()

        with self.assertRaises(ImportValidationError):
            importer.parse_csv_file('/nonexistent/path.csv')

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as f:
            f.write(b'\xff\xfe')
            bad_path = Path(f.name)
        try:
            with self.assertRaises(ImportValidationError):
                importer.parse_csv_file(bad_path)
        finally:
            bad_path.unlink()

    def test_import_records_validates_batch_size_and_skips_empty_records(self):
        importer = CSVImporter()

        with self.assertRaises(ImportValidationError):
            importer.import_records(Car, [], batch_size=0)

        result = importer.import_records(
            Car,
            [{'make': 'Honda', 'model': 'Civic', 'vin': 'JTDKB20U793512300'}],
            context=ImportContext(garage=self.garage),
            dry_run=True,
        )
        self.assertEqual(result.created_count, 1)

    def test_prepare_record_raises_for_unsupported_model(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._prepare_record(KnownShop, {}, ImportContext())

    def test_car_import_requires_garage(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._prepare_record(Car, {'make': 'Honda', 'model': 'Civic', 'vin': 'JTDKB20U793512301'}, ImportContext())

    def test_resolve_car_with_context_car_and_uuid(self):
        importer = CSVImporter()
        resolved = importer._resolve_car(str(self.car.pk), ImportContext(car=self.car))
        self.assertEqual(resolved.pk, self.car.pk)

        empty_context = ImportContext(car=self.car)
        with self.assertRaises(ImportValidationError):
            importer._resolve_car('not-the-car-uuid', empty_context)

    def test_resolve_car_without_context_raises(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._resolve_car(str(self.car.pk), ImportContext())

    def test_resolve_car_by_garage_only(self):
        importer = CSVImporter()
        resolved = importer._resolve_car(str(self.car.pk), ImportContext(garage=self.garage))
        self.assertEqual(resolved.pk, self.car.pk)

        with self.assertRaises(ImportValidationError):
            importer._resolve_car('', ImportContext(garage=self.garage))

    def test_resolve_car_by_vin_and_license_plate_and_usual_name(self):
        importer = CSVImporter()
        self.car.license_plate = 'ABC 123'
        self.car.usual_name = 'Daily Driver'
        self.car.save(update_fields=['license_plate', 'usual_name'])

        context = ImportContext(garage=self.garage)
        self.assertEqual(importer._resolve_car('ABC 123', context).pk, self.car.pk)
        self.assertEqual(importer._resolve_car('Daily Driver', context).pk, self.car.pk)

    def test_resolve_car_ambiguous_reference_raises(self):
        Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512349',
            usual_name='Same Name',
        )
        Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Accord',
            vin='1HGCM82633A123456',
            usual_name='Same Name',
        )

        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._resolve_car('Same Name', ImportContext(garage=self.garage))

    def test_resolve_car_by_non_uuid_pk(self):
        importer = CSVImporter()
        resolved = importer._resolve_car(self.car.pk, ImportContext(garage=self.garage))
        self.assertEqual(resolved.pk, self.car.pk)

    def test_resolve_mechanic_and_shop_branches(self):
        importer = CSVImporter()
        self.assertIsNone(importer._resolve_mechanic(''))
        self.assertIsNone(importer._resolve_mechanic(None))
        self.assertIsNone(importer._resolve_mechanic('   '))

        with self.assertRaises(ImportValidationError):
            importer._resolve_mechanic('no-such-mechanic@example.com')

        with self.assertRaises(ImportValidationError):
            importer._resolve_mechanic(uuid.uuid4())

        shop = KnownShop.objects.create(name='Test Shop', email='shop@example.com')
        self.assertEqual(importer._resolve_shop('Test Shop').pk, shop.pk)
        self.assertEqual(importer._resolve_shop('shop@example.com').pk, shop.pk)
        self.assertEqual(importer._resolve_shop(shop.pk).pk, shop.pk)

        with self.assertRaises(ImportValidationError):
            importer._resolve_shop('Missing Shop')

        with self.assertRaises(ImportValidationError):
            importer._resolve_shop(uuid.uuid4())

    def test_resolve_shop_scopes_to_user_context(self):
        importer = CSVImporter()
        other_user = ShopUser.objects.create_user(
            username='other-shop-owner',
            email='other-shop-owner@example.com',
            password='pass1234',
        )
        public_shop = KnownShop.objects.create(name='Public Shop', email='public@example.com')
        private_shop = KnownShop.objects.create(
            name='Private Shop',
            email='private@example.com',
            created_by=other_user,
        )

        self.assertEqual(
            importer._resolve_shop('Public Shop', context=ImportContext(user=self.user)).pk,
            public_shop.pk,
        )

        with self.assertRaises(ImportValidationError):
            importer._resolve_shop('Private Shop', context=ImportContext(user=self.user))

        with self.assertRaises(ImportValidationError):
            importer._resolve_shop(private_shop.pk, context=ImportContext(user=self.user))

        # The shop owner can still resolve their own shop.
        self.assertEqual(
            importer._resolve_shop('Private Shop', context=ImportContext(user=other_user)).pk,
            private_shop.pk,
        )

        # Without a user context (e.g. management command), resolution is unrestricted.
        self.assertEqual(importer._resolve_shop('Private Shop').pk, private_shop.pk)

    def test_report_attachment_plan_rejects_too_many_links(self):
        from shop.forms.base import MAX_EXTERNAL_LINKS

        importer = CSVImporter()
        links = '\n'.join(f'https://example.com/{index}' for index in range(MAX_EXTERNAL_LINKS + 1))
        with self.assertRaises(ImportValidationError):
            importer._report_attachment_plan({'attachments': links})

    def test_report_attachment_plan_rejects_link_too_long(self):
        from shop.forms.base import MAX_EXTERNAL_LINK_LENGTH

        importer = CSVImporter()
        long_link = 'https://example.com/' + 'a' * MAX_EXTERNAL_LINK_LENGTH
        with self.assertRaises(ImportValidationError):
            importer._report_attachment_plan({'attachments': long_link})

    def test_prepare_workjob_record_with_car_context(self):
        importer = CSVImporter()
        data, warnings = importer._prepare_workjob_record(
            {'title': 'Brake job', 'assigned_to': self.user.email, 'unknown_field': 'x'},
            ImportContext(car=self.car),
        )
        self.assertEqual(data['car'].pk, self.car.pk)
        self.assertEqual(data['assigned_to'].pk, self.user.pk)
        self.assertIn("Ignored fields", warnings[0])

    def test_prepare_report_record_with_description_alias(self):
        importer = CSVImporter()
        data, warnings, attachment_plan = importer._prepare_report_record(
            {'description': 'Annual service', 'date': '2026-08-20'},
            ImportContext(car=self.car),
        )
        self.assertEqual(data['job_name'], 'Annual service')
        self.assertEqual(data['date_done'], date(2026, 8, 20))
        self.assertEqual(data['additional_information'], '')
        self.assertEqual(attachment_plan, [])

    def test_prepare_report_record_requires_job_name_and_date(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer._prepare_report_record({}, ImportContext(car=self.car))

        with self.assertRaises(ImportValidationError):
            importer._prepare_report_record({'job_name': 'Missing date'}, ImportContext(car=self.car))

    def test_coerce_bool_and_int_and_string_list_edge_cases(self):
        importer = CSVImporter()

        self.assertTrue(importer._coerce_bool(True, field_name='flag'))
        self.assertFalse(importer._coerce_bool(False, field_name='flag'))
        self.assertTrue(importer._coerce_bool('Y', field_name='flag'))
        self.assertFalse(importer._coerce_bool('N', field_name='flag'))

        with self.assertRaises(ImportValidationError):
            importer._coerce_optional_int(-5, field_name='mileage')
        with self.assertRaises(ImportValidationError):
            importer._coerce_optional_int('abc', field_name='mileage')

        self.assertEqual(
            importer._coerce_string_list(['a', '', 'b'], field_name='list'),
            ['a', 'b'],
        )
        with self.assertRaises(ImportValidationError):
            importer._coerce_string_list({'not': 'list'}, field_name='list')

    def test_parse_date_value_branches(self):
        importer = CSVImporter()
        self.assertIsNone(importer._parse_date_value(None))
        self.assertEqual(importer._parse_date_value(date(2026, 8, 20)), date(2026, 8, 20))

        with self.assertRaises(ImportValidationError):
            importer._parse_date_value(12345)

    def test_normalize_license_plate_and_vin(self):
        importer = CSVImporter()
        self.assertEqual(importer._normalize_license_plate('abc 123'), 'ABC 123')

        with self.assertRaises(ImportValidationError):
            importer._normalize_vin('1HGBH41JXMN10918!')

    def test_ignored_field_warnings(self):
        importer = CSVImporter()
        self.assertEqual(
            importer._ignored_field_warnings({'a': 1, 'b': 2}, {'a'}),
            ["Ignored fields: ['b']"],
        )
        self.assertEqual(importer._ignored_field_warnings({'a': 1}, {'a'}), [])

import csv
from datetime import date
from unittest.mock import patch

import requests
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings

from shop.auth import (
    HankoAuthenticationError,
    _build_username,
    complete_hanko_login,
    fetch_hanko_userinfo,
    sync_hanko_user,
)
from shop.forms import CarCreateForm, KnownShopProofForm, ReportForm, WorkJobForm
from shop.importers import CSVImporter, ImportValidationError
from shop.middleware import HankoAuthenticationMiddleware, hanko_login_required
from shop.models.car import Car
from shop.models.fleet import Fleet, FleetMembership, KnownShop
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser
from shop.tests.helpers import PDF_SIGNATURE, FakeHankoResponse


class AuthAndInputCoverageTests(TestCase):
    def test_sync_hanko_user_builds_unique_usernames_and_updates_existing_user(self):
        existing = ShopUser.objects.create_user(username='alice', email='alice@example.com', password='pass1234')
        existing.hanko_id = 'hanko-42'
        existing.display_name = ''
        existing.avatar_url = ''
        existing.auth_provider = 'legacy'
        existing.save(update_fields=['hanko_id', 'display_name', 'avatar_url', 'auth_provider'])

        user = sync_hanko_user(hanko_id='hanko-42', email='alice@example.com', username='Alice', avatar_url='https://img.example.com/alice.png')
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.display_name, 'Alice')
        self.assertEqual(user.avatar_url, 'https://img.example.com/alice.png')

        created = sync_hanko_user(email='new@example.com', username='alice', hanko_id='hanko-99')
        self.assertTrue(created.username.startswith('alice'))
        self.assertNotEqual(created.username, 'alice')

    def test_complete_hanko_login_sets_session_values(self):
        factory = RequestFactory()
        request = factory.get('/auth/hanko/callback/')
        SessionMiddleware(lambda _request: None).process_request(request)

        user = complete_hanko_login(
            request,
            {
                'id': 'hanko-session-1',
                'email': 'session-user@example.com',
                'name': 'Session User',
                'avatar_url': 'https://img.example.com/session.png',
                'provider': 'hanko',
            },
        )

        self.assertTrue(request.user.is_authenticated)
        self.assertEqual(user.email, 'session-user@example.com')
        self.assertEqual(request.session['hanko_user_id'], 'hanko-session-1')
        self.assertEqual(request.session['hanko_email'], 'session-user@example.com')
        self.assertEqual(request.session['hanko_provider'], 'hanko')

    def test_fetch_hanko_userinfo_validates_token_and_response(self):
        with override_settings(HANKO_API_URL='https://hanko.example.com'):
            with self.assertRaises(HankoAuthenticationError):
                fetch_hanko_userinfo('')
            with self.assertRaises(HankoAuthenticationError):
                fetch_hanko_userinfo(123)  # type: ignore[arg-type]

            with patch('shop.auth.requests.post', side_effect=requests.RequestException('network')):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse('not-a-dict')):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({})):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            # A stringly-typed "false" must not be treated as a boolean False.
            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': 'false',
                'claims': {
                    'sub': 'stringly-false-id',
                    'email': 'false@example.com',
                },
            })):
                with self.assertRaises(HankoAuthenticationError):
                    fetch_hanko_userinfo('token')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': '  hanko-id  ',
                    'email': {'address': 'user@example.com'},
                    'username': 'User',
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['id'], 'hanko-id')
                self.assertEqual(info['email'], 'user@example.com')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': 'fallback-id',
                    'email': 'fallback@example.com',
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], 'fallback@example.com')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': 'invalid-field-id',
                    'email': 'valid@example.com',
                    'username': None,
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], 'valid@example.com')

            with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
                'is_valid': True,
                'claims': {
                    'sub': 'invalid-field-id',
                    'email': ['not', 'a', 'string'],
                },
            })):
                info = fetch_hanko_userinfo('token')
                self.assertEqual(info['email'], '')

    @override_settings(HANKO_API_URL='')
    def test_fetch_hanko_userinfo_requires_api_url(self):
        with patch.dict('os.environ', {'HANKO_API_URL': ''}):
            with self.assertRaises(HankoAuthenticationError):
                fetch_hanko_userinfo('token')

    def test_build_username_handles_collision_and_special_characters(self):
        base = _build_username('valid user!')
        self.assertEqual(base, 'valid-user-')

        ShopUser.objects.create_user(username='collider', email='collider@example.com', password='pass1234')

        first = _build_username('collider', hanko_id='id-1')
        self.assertEqual(first, 'collider1')

        second = _build_username('collider', hanko_id='id-2')
        self.assertEqual(second, 'collider1')

        empty = _build_username('', hanko_id='id-3')
        self.assertEqual(empty, 'hanko-id-3')

    def test_build_username_very_long_base_is_truncated(self):
        long_name = 'a' * 200
        result = _build_username(long_name)
        # Base is truncated to 140 chars to leave room for collision suffixes.
        self.assertEqual(len(result), 140)
        self.assertTrue(result.startswith('a' * 140))

    def test_build_username_collision_suffix_respects_max_length(self):
        long_base = 'a' * 200
        first = _build_username(long_base)
        self.assertEqual(len(first), 140)

        ShopUser.objects.create_user(
            username=first,
            email='long-base@example.com',
            password='pass1234',
        )
        second = _build_username(long_base)
        self.assertLessEqual(len(second), 150)
        self.assertTrue(second.startswith('a' * 139))
        self.assertTrue(second.endswith('1'))

        # Verify we can keep generating unique names without exceeding the limit.
        for index in range(2, 15):
            ShopUser.objects.create_user(
                username=second,
                email=f'long-base-{index}@example.com',
                password='pass1234',
            )
            second = _build_username(long_base)
            self.assertLessEqual(len(second), 150)

    def test_sync_hanko_user_finds_existing_user_by_matching_hanko_id(self):
        hanko_user = ShopUser.objects.create_user(
            username='hanko-user',
            email='lookup@example.com',
            password='pass1234',
        )
        hanko_user.hanko_id = 'existing-hanko-id'
        hanko_user.save(update_fields=['hanko_id'])

        linked = sync_hanko_user(
            hanko_id='existing-hanko-id',
            email='LOOKUP@EXAMPLE.COM',
            username='Linked User',
        )
        self.assertEqual(linked.pk, hanko_user.pk)
        self.assertEqual(linked.hanko_id, 'existing-hanko-id')
        self.assertEqual(linked.display_name, 'Linked User')

    def test_sync_hanko_user_creates_new_user_when_no_identity_match(self):
        created_no_email = sync_hanko_user()
        self.assertTrue(created_no_email.username.startswith('hanko-user'))
        self.assertEqual(created_no_email.email, '')

        created_with_email = sync_hanko_user(
            hanko_id='new-hanko-id',
            email='new-user@example.com',
            username='New User',
        )
        self.assertEqual(created_with_email.hanko_id, 'new-hanko-id')
        self.assertEqual(created_with_email.email, 'new-user@example.com')

    def test_sync_hanko_user_only_backfills_empty_fields_for_existing_hanko_user(self):
        user = ShopUser.objects.create_user(
            username='backfill',
            email='backfill@example.com',
            password='pass1234',
        )
        user.hanko_id = 'backfill-hanko-id'
        user.email = ''
        user.display_name = ''
        user.avatar_url = ''
        user.auth_provider = ''
        user.save(update_fields=['hanko_id', 'email', 'display_name', 'avatar_url', 'auth_provider'])

        updated = sync_hanko_user(
            hanko_id='backfill-hanko-id',
            email='new@example.com',
            username='New Name',
            avatar_url='https://example.com/new.png',
            provider='hanko',
        )
        self.assertEqual(updated.email, 'new@example.com')
        self.assertEqual(updated.display_name, 'New Name')
        self.assertEqual(updated.avatar_url, 'https://example.com/new.png')
        self.assertEqual(updated.auth_provider, 'hanko')

    def test_sync_hanko_user_preserves_populated_fields_for_existing_hanko_user(self):
        user = ShopUser.objects.create_user(
            username='preserve',
            email='preserve@example.com',
            password='pass1234',
        )
        user.hanko_id = 'preserve-hanko-id'
        user.display_name = 'Existing Name'
        user.avatar_url = 'https://example.com/existing.png'
        user.auth_provider = 'hanko'
        user.save(update_fields=['hanko_id', 'display_name', 'avatar_url', 'auth_provider'])

        updated_by_hanko_id = sync_hanko_user(
            hanko_id='preserve-hanko-id',
            email='new@example.com',
            username='Ignored Name',
            avatar_url='https://example.com/ignored.png',
            provider='legacy',
        )
        self.assertEqual(updated_by_hanko_id.display_name, 'Existing Name')
        self.assertEqual(updated_by_hanko_id.avatar_url, 'https://example.com/existing.png')
        self.assertEqual(updated_by_hanko_id.auth_provider, 'legacy')

        updated_by_hanko_id_no_provider = sync_hanko_user(
            hanko_id='preserve-hanko-id',
            email='new2@example.com',
            username='Ignored Name 2',
            avatar_url='https://example.com/ignored2.png',
        )
        self.assertEqual(updated_by_hanko_id_no_provider.display_name, 'Existing Name')
        self.assertEqual(updated_by_hanko_id_no_provider.avatar_url, 'https://example.com/existing.png')

    def test_sync_hanko_user_refuses_email_takeover(self):
        local_user = ShopUser.objects.create_user(
            username='local-only',
            email='local@example.com',
            password='pass1234',
        )
        self.assertIsNone(local_user.hanko_id)

        with self.assertRaises(HankoAuthenticationError):
            sync_hanko_user(
                hanko_id='attacker-hanko-id',
                email='local@example.com',
                username='Attacker',
            )

        local_user.refresh_from_db()
        self.assertIsNone(local_user.hanko_id)

        linked_user = ShopUser.objects.create_user(
            username='linked-user',
            email='linked@example.com',
            password='pass1234',
        )
        linked_user.hanko_id = 'original-hanko-id'
        linked_user.save(update_fields=['hanko_id'])

        with self.assertRaises(HankoAuthenticationError):
            sync_hanko_user(
                hanko_id='different-hanko-id',
                email='linked@example.com',
                username='Attacker',
            )

    def test_sync_hanko_user_with_empty_provider_does_not_overwrite_existing_provider(self):
        user = ShopUser.objects.create_user(
            username='provider-test',
            email='provider@example.com',
            password='pass1234',
        )
        user.hanko_id = 'provider-hanko-id'
        user.auth_provider = 'hanko'
        user.save(update_fields=['hanko_id', 'auth_provider'])

        updated_by_hanko_id = sync_hanko_user(
            hanko_id='provider-hanko-id',
            email='provider@example.com',
            username='Provider User',
            provider='',
        )
        self.assertEqual(updated_by_hanko_id.auth_provider, 'hanko')

    def test_car_form_validators_cover_invalid_ranges_and_duplicates(self):
        self.user = ShopUser.objects.create_user(username='validator', email='validator@example.com', password='pass1234')
        self.fleet = Fleet.objects.create(name='Validator Fleet', created_by=self.user)
        FleetMembership.objects.create(fleet=self.fleet, user=self.user, role=FleetMembership.ROLE_OWNER)

        Car.objects.create(fleet=self.fleet, make='Toyota', model='Yaris', vin='JTDKB20U793512346')

        invalid_year = CarCreateForm(data={
            'fleet': self.fleet.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '1800',
            'vin': 'JTDKB20U793512346',
            'license_plate': 'ABC 123',
        }, user=self.user)
        self.assertFalse(invalid_year.is_valid())
        self.assertIn('year', invalid_year.errors)

        duplicate_vin = CarCreateForm(data={
            'fleet': self.fleet.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '2024',
            'vin': 'JTDKB20U793512346',
            'license_plate': 'DEF456',
        }, user=self.user)
        self.assertFalse(duplicate_vin.is_valid())
        self.assertIn('vin', duplicate_vin.errors)

        invalid_chars = CarCreateForm(data={
            'fleet': self.fleet.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '2024',
            'vin': 'JTDKB20U7935I2346',
            'license_plate': 'ABC123',
        }, user=self.user)
        self.assertFalse(invalid_chars.is_valid())
        self.assertIn('vin', invalid_chars.errors)

        invalid_plate = CarCreateForm(data={
            'fleet': self.fleet.pk,
            'make': 'Honda',
            'model': 'Civic',
            'year': '2024',
            'vin': 'JTDKB20U793512350',
            'license_plate': 'BAD@PLATE',
        }, user=self.user)
        self.assertFalse(invalid_plate.is_valid())
        self.assertIn('license_plate', invalid_plate.errors)

    def test_car_orm_does_not_validate_vin_or_license_plate(self):
        """ORM-created cars bypass VIN/plate validation; forms enforce the rules."""
        user = ShopUser.objects.create_user(
            username='orm-car-validator',
            email='orm-car-validator@example.com',
            password='pass1234',
        )
        fleet = Fleet.objects.create(name='ORM Car Fleet', created_by=user)
        FleetMembership.objects.create(fleet=fleet, user=user, role=FleetMembership.ROLE_OWNER)

        car = Car.objects.create(
            fleet=fleet,
            make='Honda',
            model='Civic',
            vin='SHORT',
        )
        self.assertEqual(car.vin, 'SHORT')

        car2 = Car.objects.create(
            fleet=fleet,
            make='Honda',
            model='Civic',
            vin='JTDKB20U793512351',
            license_plate='BAD@PLATE',
        )
        self.assertEqual(car2.license_plate, 'BAD@PLATE')

    def test_workjob_and_report_form_line_lists_and_assignment_guards(self):
        user = ShopUser.objects.create_user(username='mechanic-form-user', email='mechanic@shop.test', password='pass1234', is_mechanic=True)
        shop = KnownShop.objects.create(name='Northside Auto', email='shop@example.com')

        workjob_form = WorkJobForm(data={
            'title': 'Brake service',
            'maintenance_type': 'inspection',
            'assigned_to': str(user.pk),
            'assigned_shop': str(shop.pk),
            'planned_date': '2026-08-09',
            'status': 'pending',
            'urgency': 'soon',
            'required_items': 'Pads\nFluid',
            'notes': 'Inspect',
        })
        self.assertFalse(workjob_form.is_valid())
        self.assertIn('__all__', workjob_form.errors)

        cleaned = WorkJobForm(data={
            'title': 'Brake service',
            'maintenance_type': 'inspection',
            'assigned_to': str(user.pk),
            'planned_date': '2026-08-09',
            'status': 'pending',
            'urgency': 'soon',
            'required_items': 'Pads\nFluid',
            'notes': 'Inspect',
        })
        self.assertTrue(cleaned.is_valid())
        self.assertEqual(cleaned.cleaned_data['required_items'], ['Pads', 'Fluid'])

        report_form = ReportForm(data={
            'mileage': '125000',
            'job_name': 'Brake service',
            'date_done': '2026-08-09',
            'external_links': 'https://example.com/one\nhttps://example.com/two',
            'note': 'Performed service.',
            'additional_information': 'Used OEM parts',
        })
        self.assertTrue(report_form.is_valid())
        self.assertEqual(report_form.cleaned_data['external_links'], ['https://example.com/one', 'https://example.com/two'])

    def test_known_shop_proof_form_rejects_invalid_files(self):
        form = KnownShopProofForm(
            data={'title': 'Proof', 'content': 'Valid proof'},
            files={'attachments': SimpleUploadedFile('bad.txt', b'nope', content_type='text/plain')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

        spoofed_pdf = SimpleUploadedFile('spoofed.pdf', b'not a pdf', content_type='application/pdf')
        spoofed_form = KnownShopProofForm(
            data={'title': 'Proof', 'content': 'Invalid proof'},
            files={'attachments': spoofed_pdf},
        )
        self.assertFalse(spoofed_form.is_valid())
        self.assertIn('attachments', spoofed_form.errors)

        pdf = SimpleUploadedFile('valid.pdf', PDF_SIGNATURE, content_type='application/pdf')
        valid_form = KnownShopProofForm(
            data={'title': 'Proof', 'content': 'Valid proof'},
            files={'attachments': pdf},
        )
        self.assertTrue(valid_form.is_valid())

    def test_orm_assignment_guards_reject_non_mechanics(self):
        non_mechanic = ShopUser.objects.create_user(
            username='orm-non-mechanic',
            email='orm-non-mechanic@example.com',
            password='pass1234',
        )
        fleet = Fleet.objects.create(name='ORM Guard Fleet', created_by=non_mechanic)
        FleetMembership.objects.create(
            fleet=fleet,
            user=non_mechanic,
            role=FleetMembership.ROLE_OWNER,
        )
        car = Car.objects.create(
            fleet=fleet,
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512346',
        )

        with self.assertRaises(ValidationError):
            WorkJob.objects.create(car=car, title='Invalid assignment', assigned_to=non_mechanic)
        with self.assertRaises(ValidationError):
            Report.objects.create(
                car=car,
                job_name='Invalid assignment',
                date_done='2026-08-09',
                assigned_to=non_mechanic,
            )

    def test_importer_list_and_type_validations(self):
        importer = CSVImporter()

        self.assertEqual(importer.parse_csv_content(''), [])
        self.assertEqual(importer.parse_csv_content('   \n '), [])
        self.assertEqual(importer._detect_dialect('make,model,vin\n').delimiter, ',')
        self.assertEqual(importer._detect_dialect('justaword\n'), csv.excel)
        self.assertEqual(importer._coerce_bool('yes', field_name='flag'), True)
        self.assertEqual(importer._coerce_bool('0', field_name='flag'), False)
        self.assertEqual(importer._coerce_bool('', field_name='flag'), False)
        with self.assertRaises(ImportValidationError):
            importer._coerce_bool('maybe', field_name='flag')

        self.assertEqual(importer._parse_date_value('2026-08'), date(2026, 8, 1))
        self.assertEqual(importer._parse_date_value('2026'), date(2026, 1, 1))
        with self.assertRaises(ImportValidationError):
            importer._parse_date_value('not-a-date')

        self.assertEqual(importer._coerce_string_list(['', 'fee', None], field_name='list'), ['fee'])
        self.assertEqual(importer._coerce_string_list('one\ntwo', field_name='list'), ['one', 'two'])
        with self.assertRaises(ImportValidationError):
            importer._coerce_string_list(123, field_name='list')

        with self.assertRaises(ImportValidationError):
            importer._normalize_vin('1HGBH41JXMN10918I')
        with self.assertRaises(ImportValidationError):
            importer._normalize_vin('SHORT')
        self.assertEqual(importer._normalize_vin(' 1hgbh41jxmn109186 '), '1HGBH41JXMN109186')

        with self.assertRaises(ImportValidationError):
            importer._normalize_license_plate('A' * 21)
        with self.assertRaises(ImportValidationError):
            importer._normalize_license_plate('BAD_PLATE')
        self.assertEqual(importer._normalize_license_plate('abc 123'), 'ABC 123')
        self.assertEqual(importer._normalize_license_plate(''), '')

        with self.assertRaises(ImportValidationError):
            importer._coerce_optional_int('not-an-int', field_name='mileage')
        self.assertEqual(importer._coerce_optional_int('', field_name='mileage'), None)
        self.assertEqual(importer._coerce_optional_int('123', field_name='mileage'), 123)

        self.assertEqual(importer._format_validation_error(ValidationError({'make': ['Bad value.']})), 'make: Bad value.')
        self.assertEqual(importer._format_validation_error(ValidationError('Plain error.')), 'Plain error.')

    def test_convert_user_to_mechanic_command_handles_grant_and_revoke_branches(self):
        user = ShopUser.objects.create_user(username='mechanic-cmd', email='mechanic-cmd@example.com', password='pass1234')

        call_command('convert_user_to_mechanic', user.email)
        user.refresh_from_db()
        self.assertTrue(user.is_mechanic)
        self.assertIsNotNone(user.mechanic_promoted_at)

        call_command('convert_user_to_mechanic', user.email, '--revoke')
        user.refresh_from_db()
        self.assertFalse(user.is_mechanic)
        self.assertIsNone(user.mechanic_promoted_at)

        with self.assertRaises(CommandError):
            call_command('convert_user_to_mechanic', '')

    def test_hanko_auth_middleware_and_decorator_cover_redirect_and_rehydrate_paths(self):
        factory = RequestFactory()

        with override_settings(HANKO_API_URL='https://hanko.example.com'):
            request = factory.get('/secure/route/')
            SessionMiddleware(lambda _request: None).process_request(request)
            request.session['hanko_session_token'] = 'session-token-ABC'
            request.user = AnonymousUser()

            with patch('shop.auth.requests.post') as mock_post:
                mock_post.return_value.raise_for_status.return_value = None
                mock_post.return_value.json.return_value = {
                    'is_valid': True,
                    'claims': {
                        'sub': 'recovered-hanko-id',
                        'email': 'recovered@example.com',
                        'username': 'Recovered User',
                    },
                }
                response = HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(request)
                self.assertIsNone(response)
                self.assertTrue(request.user.is_authenticated)

        public_request = factory.get('/login/')
        SessionMiddleware(lambda _request: None).process_request(public_request)
        public_request.user = AnonymousUser()
        self.assertIsNone(HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(public_request))

        no_session = factory.get('/private/')
        SessionMiddleware(lambda _request: None).process_request(no_session)
        no_session.user = AnonymousUser()
        response = HankoAuthenticationMiddleware(lambda _request: HttpResponse()).process_request(no_session)
        self.assertEqual(response.status_code, 302)

        decorated = hanko_login_required(lambda _request: HttpResponse('ok'))
        decorator_request = factory.get('/private/')
        SessionMiddleware(lambda _request: None).process_request(decorator_request)
        decorator_request.user = AnonymousUser()
        result = decorated(decorator_request)
        self.assertEqual(result.status_code, 302)

        authenticated = factory.get('/private/')
        SessionMiddleware(lambda _request: None).process_request(authenticated)
        authenticated.user = ShopUser.objects.create_user(username='decorated-user', email='decorated@example.com', password='pass1234')
        self.assertEqual(decorated(authenticated).status_code, 200)

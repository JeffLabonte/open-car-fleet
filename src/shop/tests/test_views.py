import json
from datetime import date
from datetime import timedelta
from unittest.mock import patch
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from shop.importers import CSVImporter
from shop.importers import ImportContext
from shop.importers import ImportValidationError
from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.car import CarPart
from shop.models.garage import Garage
from shop.models.garage import GarageInvitation
from shop.models.garage import GarageMembership
from shop.models.garage import KnownShop
from shop.models.garage import KnownShopProof
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser
from shop.tests.helpers import FakeHankoResponse


class AdditionalCoverageRegressionTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='coverage-owner',
            email='coverage-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.member = ShopUser.objects.create_user(
            username='coverage-member',
            email='coverage-member@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Coverage Garage', created_by=self.owner)
        GarageMembership.objects.create(garage=self.garage, user=self.owner, role=GarageMembership.ROLE_OWNER)
        GarageMembership.objects.create(garage=self.garage, user=self.member, role=GarageMembership.ROLE_MEMBER)
        self.car = Car.objects.create(
            garage=self.garage,
            make='Honda',
            model='Accord',
            vin='1HGCM82633A004352',
        )

    def test_login_theme_and_hanko_callback_branches(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-index'))

        self.client.logout()
        session = self.client.session
        session['logged_out'] = True
        session.save()
        login_response = self.client.get(reverse('shop-login'))
        self.assertTrue(login_response.context['logged_out'])

        invalid_theme = self.client.get(reverse('shop-theme', kwargs={'theme': 'banana'}), {'next': reverse('shop-login')})
        self.assertEqual(invalid_theme.cookies['theme'].value, 'light')

        dark_theme = self.client.get(reverse('shop-theme', kwargs={'theme': 'dark'}), {'next': reverse('shop-login')})
        self.assertEqual(dark_theme.cookies['theme'].value, 'dark')

        empty_payload = self.client.post(reverse('shop-hanko-callback'), data='not-json', content_type='application/json')
        self.assertEqual(empty_payload.status_code, 400)
        self.assertEqual(empty_payload.json()['error'], 'Missing user payload')

        valid_payload = {
            'user': {
                'id': 'hanko-coverage',
                'email': 'new-coverage@example.com',
                'name': 'Coverage User',
                'display_name': 'Coverage User',
                'provider': 'hanko',
            },
            'session_token': 'token-coverage-123',
        }
        with patch('shop.auth.requests.post', return_value=FakeHankoResponse({
            'is_valid': True,
            'claims': {
                'sub': 'hanko-coverage',
                'email': 'new-coverage@example.com',
                'username': 'Coverage User',
            },
        })):
            callback_response = self.client.post(
                reverse('shop-hanko-callback'),
                data=json.dumps(valid_payload),
                content_type='application/json',
            )
        self.assertEqual(callback_response.status_code, 200)
        self.assertEqual(callback_response.json()['user']['email'], 'new-coverage@example.com')
        self.assertEqual(self.client.session['hanko_session_token'], 'token-coverage-123')

    def test_garage_share_and_invitation_branches(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('shop-garage-share', args=[self.garage.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

        self.client.force_login(self.owner)
        with patch('shop.models.garage.send_mail', side_effect=Exception('mail failed')):
            response = self.client.post(
                reverse('shop-garage-share', args=[self.garage.pk]),
                data={
                    'invited_email': 'someone@example.com',
                    'message': 'Join us',
                    'expires_in_days': 7,
                },
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GarageInvitation.objects.filter(invited_email='someone@example.com').exists())

        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='coverage-member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.member)
        response = self.client.get(reverse('shop-garage-invitation-accept', args=[invitation.token]), follow=True)
        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_EXPIRED)

        other_invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='coverage-member@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-garage-invitation-accept', args=[other_invitation.token]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse('shop-index'))

    def test_car_crud_and_report_workflow_views(self):
        self.client.force_login(self.owner)
        create_response = self.client.post(
            reverse('shop-car-create'),
            data={
                'garage': str(self.garage.pk),
                'usual_name': 'Roadster',
                'make': 'Mazda',
                'model': 'MX-5',
                'colour': 'Red',
                'year': '2024',
                'vin': 'JM1NDAB77P0112345',
                'license_plate': 'ABC 123',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        created_car = Car.objects.get(vin='JM1NDAB77P0112345')

        update_response = self.client.post(
            reverse('shop-car-update', args=[created_car.pk]),
            data={
                'garage': str(self.garage.pk),
                'usual_name': 'Roadster Updated',
                'make': 'Mazda',
                'model': 'MX-5',
                'colour': 'Blue',
                'year': '2024',
                'vin': 'JM1NDAB77P0112345',
                'license_plate': 'XYZ 999',
            },
        )
        self.assertEqual(update_response.status_code, 302)
        created_car.refresh_from_db()
        self.assertEqual(created_car.usual_name, 'Roadster Updated')

        part_response = self.client.post(
            reverse('shop-part-create', args=[created_car.pk]),
            data={'name': 'Brake pads', 'status': CarPart.STATUS_NEW, 'notes': 'Initial inspection'},
        )
        self.assertEqual(part_response.status_code, 302)
        part = created_car.parts.get(name='Brake pads')

        workjob_response = self.client.post(
            reverse('shop-workjob-create', args=[created_car.pk]),
            data={
                'title': 'Oil service',
                'maintenance_type': 'service',
                'assigned_to': str(self.owner.pk),
                'planned_date': '2026-08-11',
                'status': 'pending',
                'urgency': 'soon',
                'required_items': 'Oil\nFilter',
                'notes': 'Routine service',
            },
        )
        self.assertEqual(workjob_response.status_code, 302)
        work_job = WorkJob.objects.get(title='Oil service')

        report_response = self.client.post(
            reverse('shop-report-create', args=[created_car.pk]),
            data={
                'mileage': '10000',
                'job_name': 'Oil service',
                'date_done': '2026-08-12',
                'external_links': 'https://example.com/invoice',
                'note': 'Completed',
                'additional_information': 'Used synthetic oil',
            },
        )
        self.assertEqual(report_response.status_code, 302)
        report = Report.objects.get(job_name='Oil service')

        self.client.post(reverse('shop-logout'))
        first_login = self.client.get(reverse('shop-login'))
        self.assertTrue(first_login.context['logged_out'])

        second_login = self.client.get(reverse('shop-login'))
        self.assertFalse(second_login.context['logged_out'])

        part_update_response = self.client.post(
            reverse('shop-part-update', args=[created_car.pk, part.pk]),
            data={'name': 'Brake pads', 'status': CarPart.STATUS_ORDERED, 'notes': 'Parts ordered'},
        )
        self.assertEqual(part_update_response.status_code, 302)

        workjob_update_response = self.client.post(
            reverse('shop-workjob-update', args=[created_car.pk, work_job.pk]),
            data={
                'title': 'Oil service',
                'maintenance_type': 'service',
                'assigned_to': str(self.owner.pk),
                'planned_date': '2026-08-11',
                'status': 'done',
                'is_done': 'on',
                'done_date': '2026-08-12',
                'urgency': 'ahead',
                'required_items': 'Oil\nFilter',
                'notes': 'Routine service complete',
            },
        )
        self.assertEqual(workjob_update_response.status_code, 302)

        report_update_response = self.client.post(
            reverse('shop-report-update', args=[created_car.pk, report.pk]),
            data={
                'mileage': '10001',
                'job_name': 'Oil service',
                'date_done': '2026-08-12',
                'external_links': 'https://example.com/invoice',
                'note': 'Completed and rechecked',
                'additional_information': 'Used synthetic oil and filter',
            },
        )
        self.assertEqual(report_update_response.status_code, 302)

        self.client.force_login(self.owner)
        car_delete_response = self.client.post(reverse('shop-car-delete', args=[created_car.pk]))
        self.assertEqual(car_delete_response.status_code, 302)
        self.assertFalse(Car.objects.filter(pk=created_car.pk).exists())

    def test_importer_edge_cases_and_unknown_model_branches(self):
        importer = CSVImporter()
        with self.assertRaises(ImportValidationError):
            importer.resolve_model('unknown_model')

        result = importer.import_records(Car, [{'make': 'Nope'}], context=ImportContext(garage=self.garage))
        self.assertTrue(result.has_errors)
        self.assertIn("Field 'model' is required", result.errors[0].message)

        result = importer.import_records(Car, [42], context=ImportContext(garage=self.garage))
        self.assertTrue(result.has_errors)
        self.assertIn('Record is not an object', result.errors[0].message)

        self.client.force_login(self.owner)
        result = importer.import_records(
            WorkJob,
            [{
                'car': str(self.car.pk),
                'title': 'Tire rotation',
                'assigned_to': 'missing-user@example.com',
                'assigned_shop': 'missing-shop@example.com',
            }],
            context=ImportContext(garage=self.garage),
        )
        self.assertTrue(result.has_errors)

        result = importer.import_records(
            Report,
            [{
                'car': str(self.car.pk),
                'job_name': 'Inspection',
                'date_done': '2026-08-13',
                'assigned_to': 'not-a-mechanic@example.com',
                'assigned_shop': 'not-a-shop@example.com',
            }],
            context=ImportContext(garage=self.garage),
        )
        self.assertTrue(result.has_errors)

        self.assertTrue(importer._looks_like_uuid(str(self.car.pk)))
        self.assertFalse(importer._looks_like_uuid('not-a-uuid'))
        self.assertEqual(importer._parse_date_value('2026-08-15'), date(2026, 8, 15))


class ViewCoverageTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='view-owner',
            email='view-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.member = ShopUser.objects.create_user(
            username='view-member',
            email='view-member@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='view-stranger',
            email='view-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='View Garage', created_by=self.owner)
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
            make='Honda',
            model='Civic',
            vin='2HGFG12698H512347',
            year=2022,
        )

    def test_garage_create_renders_form_and_handles_invalid_post(self):
        self.client.force_login(self.owner)

        get_response = self.client.get(reverse('shop-garage-create'))
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(reverse('shop-garage-create'), data={'name': ''})
        self.assertEqual(post_response.status_code, 200)
        self.assertFalse(Garage.objects.filter(name='').exists())

    def test_garage_detail_and_index_render_for_member(self):
        self.client.force_login(self.owner)

        detail_response = self.client.get(reverse('shop-garage-detail', args=[self.garage.pk]))
        self.assertEqual(detail_response.status_code, 200)

        index_response = self.client.get(reverse('shop-index'))
        self.assertEqual(index_response.status_code, 200)

    def test_garage_share_branches(self):
        self.client.force_login(self.owner)

        # Already a member
        member_response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': self.member.email,
                'message': 'Already member',
                'expires_in_days': 14,
            },
        )
        self.assertEqual(member_response.status_code, 302)

        # Invalid form
        invalid_response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': 'not-an-email',
                'message': 'Bad',
                'expires_in_days': 14,
            },
        )
        self.assertEqual(invalid_response.status_code, 200)

        # Successful invitation renders GET form
        with patch('shop.models.garage.send_mail', side_effect=Exception('SMTP down')):
            send_failure_response = self.client.post(
                reverse('shop-garage-share', args=[self.garage.pk]),
                data={
                    'invited_email': 'new-invite@example.com',
                    'message': 'Join us',
                    'expires_in_days': 14,
                },
            )
        self.assertEqual(send_failure_response.status_code, 302)

    def test_garage_import_branches(self):
        self.client.force_login(self.owner)

        csv_content = b'make,model,vin\nFord,F-150,1FTFW1ET5DFC12345\n'
        valid_response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': SimpleUploadedFile('cars.csv', csv_content, content_type='text/csv'),
                'dry_run': 'on',
            },
        )
        self.assertEqual(valid_response.status_code, 200)

        invalid_response = self.client.post(
            reverse('shop-garage-import', args=[self.garage.pk]),
            data={
                'import_file': SimpleUploadedFile('bad.txt', b'garbage', content_type='text/plain'),
                'dry_run': '',
            },
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn('import_file', invalid_response.context['form'].errors)

        get_response = self.client.get(reverse('shop-garage-import', args=[self.garage.pk]))
        self.assertEqual(get_response.status_code, 200)

        self.client.force_login(self.member)
        forbidden_response = self.client.get(reverse('shop-garage-import', args=[self.garage.pk]))
        self.assertEqual(forbidden_response.status_code, 302)

    def test_garage_export_forbidden_to_non_managers(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('shop-garage-export', args=[self.garage.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-garage-detail', args=[self.garage.pk]))

    def test_known_shop_create_and_detail_and_proof_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-known-shop-create'),
            data={
                'name': 'Branch Shop',
                'email': 'branch@example.com',
                'phone': '555-0200',
                'address': '20 Side Street',
                'notes': 'Note',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        shop = KnownShop.objects.get(name='Branch Shop')

        detail_response = self.client.get(reverse('shop-known-shop-detail', args=[shop.pk]))
        self.assertEqual(detail_response.status_code, 200)

        invalid_proof_response = self.client.post(
            reverse('shop-known-shop-proof-create', args=[shop.pk]),
            data={
                'title': 'Bad proof',
                'content': 'No file',
                'attachments': SimpleUploadedFile('not-pdf.txt', b'not a pdf', content_type='text/plain'),
            },
        )
        self.assertEqual(invalid_proof_response.status_code, 200)
        self.assertIn('attachments', invalid_proof_response.context['form'].errors)

        # Non-manager cannot add proof
        self.client.force_login(self.stranger)
        forbidden_proof_response = self.client.get(
            reverse('shop-known-shop-proof-create', args=[shop.pk]),
        )
        self.assertEqual(forbidden_proof_response.status_code, 404)

    def test_known_shop_proof_file_missing_file_raises_404(self):
        self.client.force_login(self.owner)
        shop = KnownShop.objects.create(name='No Proof Shop', created_by=self.owner)
        proof = KnownShopProof.objects.create(shop=shop, title='No file')
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(proof),
            object_id=str(proof.pk),
            source_type=Attachment.SOURCE_UPLOAD,
        )

        response = self.client.get(reverse('shop-attachment-file', args=[attachment.pk]))
        self.assertEqual(response.status_code, 404)

    def test_car_import_branches(self):
        self.client.force_login(self.owner)

        csv_content = b'title,maintenance_type,planned_date,status,urgency\nTire rotation,service,2026-08-20,pending,soon\n'
        valid_response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_file': SimpleUploadedFile('workjobs.csv', csv_content, content_type='text/csv'),
                'import_type': 'workjob',
                'dry_run': '',
            },
        )
        self.assertEqual(valid_response.status_code, 302)

        invalid_response = self.client.post(
            reverse('shop-car-import', args=[self.car.pk]),
            data={
                'import_file': SimpleUploadedFile('bad.txt', b'garbage', content_type='text/plain'),
                'import_type': 'workjob',
                'dry_run': '',
            },
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn('import_file', invalid_response.context['form'].errors)

        get_response = self.client.get(
            reverse('shop-car-import', args=[self.car.pk]),
            {'type': 'report'},
        )
        self.assertEqual(get_response.status_code, 200)

        invalid_type_response = self.client.get(
            reverse('shop-car-import', args=[self.car.pk]),
            {'type': 'invalid'},
        )
        self.assertEqual(invalid_type_response.status_code, 200)

    def test_part_create_and_update_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-part-create', args=[self.car.pk]),
                data={'name': 'Brake pads', 'status': CarPart.STATUS_NEW, 'notes': 'Good'},
        )
        self.assertEqual(create_response.status_code, 302)
        part = CarPart.objects.get(car=self.car, name='Brake pads')

        get_update_response = self.client.get(reverse('shop-part-update', args=[self.car.pk, part.pk]))
        self.assertEqual(get_update_response.status_code, 200)

        update_response = self.client.post(
            reverse('shop-part-update', args=[self.car.pk, part.pk]),
            data={'name': 'Brake pads', 'status': CarPart.STATUS_ORDERED, 'notes': 'Ordered'},
        )
        self.assertEqual(update_response.status_code, 302)
        part.refresh_from_db()
        self.assertEqual(part.status, CarPart.STATUS_ORDERED)

    def test_workjob_create_and_update_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-workjob-create', args=[self.car.pk]),
            data={
                'title': 'Oil change',
                'maintenance_type': 'service',
                'planned_date': '2026-08-20',
                'status': 'pending',
                'urgency': 'soon',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        work_job = WorkJob.objects.get(car=self.car, title='Oil change')

        get_update_response = self.client.get(reverse('shop-workjob-update', args=[self.car.pk, work_job.pk]))
        self.assertEqual(get_update_response.status_code, 200)

        update_response = self.client.post(
            reverse('shop-workjob-update', args=[self.car.pk, work_job.pk]),
            data={
                'title': 'Oil change updated',
                'maintenance_type': 'service',
                'planned_date': '2026-08-21',
                'status': 'done',
                'urgency': 'soon',
            },
        )
        self.assertEqual(update_response.status_code, 302)

    def test_report_create_and_update_branches(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data={
                'mileage': '50000',
                'job_name': 'Inspection',
                'date_done': '2026-08-20',
                'external_links': 'https://example.com/invoice',
            },
        )
        self.assertEqual(create_response.status_code, 302)
        report = Report.objects.get(car=self.car, job_name='Inspection')
        self.assertTrue(report.attachments.exists())

        get_update_response = self.client.get(reverse('shop-report-update', args=[self.car.pk, report.pk]))
        self.assertEqual(get_update_response.status_code, 200)

        update_response = self.client.post(
            reverse('shop-report-update', args=[self.car.pk, report.pk]),
            data={
                'mileage': '50001',
                'job_name': 'Inspection updated',
                'date_done': '2026-08-21',
            },
        )
        self.assertEqual(update_response.status_code, 302)

    def test_report_attachment_file_branches(self):
        self.client.force_login(self.owner)
        report = Report.objects.create(car=self.car, job_name='Attachment test', date_done='2026-08-20')
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile('report.pdf', b'%PDF-1.4 report', content_type='application/pdf'),
        )

        try:
            response = self.client.get(
                reverse('shop-attachment-file', args=[attachment.pk]),
            )
            self.assertEqual(response.status_code, 200)
        finally:
            attachment.file.delete(save=False)

        empty_attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
        )
        response = self.client.get(
            reverse('shop-attachment-file', args=[empty_attachment.pk]),
        )
        self.assertEqual(response.status_code, 404)

    def test_hanko_callback_branches(self):
        response = self.client.get(reverse('shop-hanko-callback'))
        self.assertEqual(response.status_code, 405)

        empty_response = self.client.post(
            reverse('shop-hanko-callback'),
            data='',
            content_type='application/json',
        )
        self.assertEqual(empty_response.status_code, 400)

        invalid_json_response = self.client.post(
            reverse('shop-hanko-callback'),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(invalid_json_response.status_code, 400)

    def test_login_view_redirects_authenticated_users(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-index'))

    def test_theme_view_rejects_unknown_theme(self):
        response = self.client.get(reverse('shop-theme', args=['pink']), {'next': reverse('shop-login')})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies['theme'].value, 'light')

    def test_logout_view_ignores_get(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-logout'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_car_create_and_update_invalid_forms(self):
        self.client.force_login(self.owner)

        invalid_create = self.client.post(
            reverse('shop-car-create'),
            data={'make': '', 'model': '', 'garage': str(self.garage.pk)},
        )
        self.assertEqual(invalid_create.status_code, 200)

        invalid_update = self.client.post(
            reverse('shop-car-update', args=[self.car.pk]),
            data={'make': '', 'model': ''},
        )
        self.assertEqual(invalid_update.status_code, 200)

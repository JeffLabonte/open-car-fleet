import io
from datetime import timedelta
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.forms.base import AttachmentField
from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership
from shop.models.report import Report
from shop.models.user import ShopUser
from shop.tests.helpers import PNG_SIGNATURE
from shop.views import purge_stale_staged_attachments


class AttachmentStagingEndpointTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='staging-owner',
            email='staging-owner@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='staging-stranger',
            email='staging-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Staging Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Prius',
            vin='JTDKB20U929483756',
        )

    def _upload(self, client, name='photo.png', content=PNG_SIGNATURE, content_type='image/png'):
        return client.post(
            reverse('shop-attachment-upload'),
            data={'file': SimpleUploadedFile(name, content, content_type=content_type)},
        )

    def test_upload_requires_authentication(self):
        response = self._upload(self.client)
        self.assertEqual(response.status_code, 302)

    def test_upload_stages_file_for_owner(self):
        self.client.force_login(self.user)
        response = self._upload(self.client)
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['name'], 'photo.png')
        self.assertEqual(payload['kind'], 'image')
        attachment = Attachment.objects.get(pk=payload['id'])
        self.assertEqual(attachment.object_id, '')
        self.assertIsNone(attachment.content_type)
        self.assertEqual(attachment.uploaded_by, self.user)
        self.assertTrue(attachment.file)
        attachment.file.delete(save=False)

    def test_upload_without_file_returns_400(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('shop-attachment-upload'), data={})
        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_disallowed_extension(self):
        self.client.force_login(self.user)
        response = self._upload(self.client, name='payload.exe', content=b'MZ', content_type='application/x-msdownload')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Unsupported attachment file type.')
        self.assertFalse(Attachment.objects.exists())

    def test_upload_rejects_spoofed_magic_bytes(self):
        self.client.force_login(self.user)
        response = self._upload(self.client, content=b'<html><script>alert(1)</script></html>')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Attachment contents do not match its file type.')
        self.assertFalse(Attachment.objects.exists())

    def test_upload_rejects_oversized_file(self):
        self.client.force_login(self.user)
        with patch.object(AttachmentField, 'max_upload_bytes', 10):
            response = self._upload(self.client, content=PNG_SIGNATURE + b'0' * 11)
        self.assertEqual(response.status_code, 400)
        self.assertIn('no larger than', response.json()['error'])
        self.assertFalse(Attachment.objects.exists())

    def test_upload_opportunistically_purges_stale_staged(self):
        stale = Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('stale.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='stale.png',
            mime_type='image/png',
        )
        Attachment.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=13))

        self.client.force_login(self.user)
        response = self._upload(self.client)

        self.assertEqual(response.status_code, 201)
        self.assertFalse(Attachment.objects.filter(pk=stale.pk).exists())

    def test_delete_staged_by_owner(self):
        self.client.force_login(self.user)
        upload_response = self._upload(self.client)
        attachment_id = upload_response.json()['id']

        response = self.client.post(reverse('shop-attachment-delete', args=[attachment_id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attachment.objects.filter(pk=attachment_id).exists())

    def test_delete_rejects_other_users_staged_attachments(self):
        attachment = Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('mine.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='mine.png',
            mime_type='image/png',
        )
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('shop-attachment-delete', args=[attachment.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())
        attachment.file.delete(save=False)

    def test_delete_rejects_claimed_attachments(self):
        report = Report.objects.create(car=self.car, job_name='Claimed', date_done='2026-09-14')
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('claimed.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='claimed.png',
            mime_type='image/png',
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse('shop-attachment-delete', args=[attachment.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())
        attachment.file.delete(save=False)


class StagedAttachmentClaimTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='claim-owner',
            email='claim-owner@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='claim-stranger',
            email='claim-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Claim Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Corolla',
            vin='JTDKB20U112233445',
        )
        self.client.force_login(self.user)

    def _stage(self, name, content=PNG_SIGNATURE, content_type='image/png'):
        response = self.client.post(
            reverse('shop-attachment-upload'),
            data={'file': SimpleUploadedFile(name, content, content_type=content_type)},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def _report_payload(self, **overrides):
        payload = {
            'mileage': '100000',
            'job_name': 'Brake service',
            'date_done': '2026-09-14',
            'note': 'Replaced pads',
            'additional_information': '',
        }
        payload.update(overrides)
        return payload

    def test_report_create_claims_staged_attachments_in_order(self):
        first = self._stage('first.png')
        second = self._stage('second.png')

        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data=self._report_payload(staged_attachments=f'{second},{first}'),
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get(job_name='Brake service')
        attachments = list(report.attachments.filter(source_type='upload').order_by('order'))
        self.assertEqual([item.display_name for item in attachments], ['second.png', 'first.png'])
        self.assertEqual([item.pk for item in attachments], [second, first])
        for item in attachments:
            self.assertEqual(item.content_type, ContentType.objects.get_for_model(report))
            self.assertEqual(item.object_id, str(report.pk))

    def test_report_create_rejects_foreign_staged_ids(self):
        self.client.force_login(self.stranger)
        foreign_id = self._stage('theirs.png')
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data=self._report_payload(staged_attachments=str(foreign_id)),
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('staged_attachments', form.errors)
        self.assertFalse(Report.objects.filter(job_name='Brake service').exists())

    def test_report_create_rejects_already_claimed_ids(self):
        report = Report.objects.create(car=self.car, job_name='Existing', date_done='2026-09-14')
        claimed = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('claimed.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='claimed.png',
            mime_type='image/png',
        )

        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data=self._report_payload(job_name='Second report', staged_attachments=str(claimed.pk)),
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('staged_attachments', form.errors)
        claimed.file.delete(save=False)

    def test_direct_uploads_and_staged_together_exceed_limit(self):
        staged_id = self._stage('staged.png')
        files = [
            SimpleUploadedFile(f'photo-{index}.png', PNG_SIGNATURE, content_type='image/png')
            for index in range(AttachmentField.max_files)
        ]
        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data={
                **self._report_payload(staged_attachments=str(staged_id)),
                'attachments': files,
            },
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('staged_attachments', form.errors)

    def test_purge_keeps_claimed_attachments_older_than_window(self):
        report = Report.objects.create(car=self.car, job_name='Old claim', date_done='2026-09-14')
        claimed = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('old-claim.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='old-claim.png',
            mime_type='image/png',
        )
        Attachment.objects.filter(pk=claimed.pk).update(created_at=timezone.now() - timedelta(hours=13))
        stale = Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('stale.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='stale.png',
            mime_type='image/png',
        )
        fresh = Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('fresh.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='fresh.png',
            mime_type='image/png',
        )
        Attachment.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=13))

        purged = purge_stale_staged_attachments()

        self.assertEqual(purged, 1)
        self.assertFalse(Attachment.objects.filter(pk=stale.pk).exists())
        self.assertTrue(Attachment.objects.filter(pk__in=[claimed.pk, fresh.pk]).exists())
        claimed.file.delete(save=False)
        fresh.file.delete(save=False)

    def test_purge_command_reports_count(self):
        stale = Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            uploaded_by=self.user,
            file=SimpleUploadedFile('stale.png', PNG_SIGNATURE, content_type='image/png'),
            display_name='stale.png',
            mime_type='image/png',
        )
        Attachment.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=13))

        buffer = io.StringIO()
        call_command('purge_staged_attachments', stdout=buffer)

        self.assertIn('Purged 1', buffer.getvalue())
        self.assertFalse(Attachment.objects.filter(pk=stale.pk).exists())

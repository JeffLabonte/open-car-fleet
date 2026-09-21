from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from shop.forms import ReportForm
from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.garage import Garage
from shop.models.garage import GarageMembership
from shop.models.report import Report
from shop.models.user import ShopUser
from shop.tests.helpers import MP4_SIGNATURE
from shop.tests.helpers import PNG_SIGNATURE


class ReportAttachmentTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='report-owner',
            email='report-owner@example.com',
            password='pass1234',
            is_mechanic=True,
        )
        self.stranger = ShopUser.objects.create_user(
            username='report-stranger',
            email='report-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Report Garage', created_by=self.user)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Prius',
            vin='JTDKB20U123456789',
        )

    def test_report_create_accepts_uploads_and_external_links(self):
        self.client.force_login(self.user)
        image = SimpleUploadedFile('before.png', PNG_SIGNATURE, content_type='image/png')
        video = SimpleUploadedFile('clip.mp4', MP4_SIGNATURE, content_type='video/mp4')

        job_name = f'Brake service {self._testMethodName}'
        response = self.client.post(
            reverse('shop-report-create', args=[self.car.pk]),
            data={
                'mileage': '125000',
                'job_name': job_name,
                'date_done': '2026-08-09',
                'note': 'Replaced brake pads',
                'additional_information': 'Used OEM parts and torqued wheels to spec',
                'external_links': 'https://onedrive.example.com/share/abc\nhttps://drive.google.com/file/d/123/view',
                'attachments': [image, video],
            },
        )

        self.assertEqual(response.status_code, 302)
        report = Report.objects.get(job_name=job_name)
        self.assertEqual(report.attachments.count(), 4)
        self.assertEqual(report.attachments.filter(source_type='upload').count(), 2)
        self.assertEqual(report.attachments.filter(source_type='external').count(), 2)
        self.assertEqual(report.additional_information, 'Used OEM parts and torqued wheels to spec')
        self.assertTrue(report.attachments.filter(source_type='external').exists())
        self.assertTrue(report.attachments.filter(source_type='upload', kind='image').exists())
        self.assertTrue(report.attachments.filter(source_type='upload', kind='video').exists())
        attachment_urls = {attachment.url for attachment in report.attachments.all()}
        self.assertIn('https://onedrive.example.com/share/abc', attachment_urls)
        self.assertIn('https://drive.google.com/file/d/123/view', attachment_urls)

    def test_report_form_rejects_unsafe_links_and_upload_types(self):
        unsafe_link_form = ReportForm(data={
            'job_name': 'Unsafe link',
            'date_done': '2026-08-10',
            'external_links': 'javascript:alert(1)',
        })
        self.assertFalse(unsafe_link_form.is_valid())
        self.assertIn('external_links', unsafe_link_form.errors)

        unsafe_file_form = ReportForm(
            data={
                'job_name': 'Executable attachment',
                'date_done': '2026-08-10',
            },
            files={
                'attachments': SimpleUploadedFile(
                    'payload.exe',
                    b'MZ executable',
                    content_type='application/x-msdownload',
                ),
            },
        )
        self.assertFalse(unsafe_file_form.is_valid())
        self.assertIn('attachments', unsafe_file_form.errors)

    def test_orphaned_attachment_returns_404(self):
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(Report),
            object_id='999999',
            source_type=Attachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile('orphan.pdf', b'%PDF-1.4 orphan', content_type='application/pdf'),
        )
        try:
            self.client.force_login(self.user)
            response = self.client.get(reverse('shop-attachment-file', args=[attachment.pk]))
            self.assertEqual(response.status_code, 404)
        finally:
            attachment.file.delete(save=False)

    def test_uploaded_report_attachment_is_streamed_only_to_car_members(self):
        report = Report.objects.create(
            car=self.car,
            job_name='Uploaded invoice',
            date_done='2026-08-10',
        )
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            file=SimpleUploadedFile(
                'invoice.pdf',
                b'%PDF-1.4 invoice',
                content_type='application/pdf',
            ),
        )

        try:
            self.client.force_login(self.user)
            response = self.client.get(
                reverse('shop-attachment-file', args=[attachment.pk]),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 invoice')

            self.client.force_login(self.stranger)
            forbidden_response = self.client.get(
                reverse('shop-attachment-file', args=[attachment.pk]),
            )
            self.assertEqual(forbidden_response.status_code, 404)
        finally:
            attachment.file.delete(save=False)

    def test_car_detail_renders_attachment_preview_links(self):
        self.client.force_login(self.user)
        report = Report.objects.create(
            car=self.car,
            job_name='Oil change',
            date_done='2026-08-10',
            note='Completed',
        )
        Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            source_type='external',
            url='https://drive.google.com/file/d/456/view',
            display_name='Service checklist',
            kind='link',
        )

        response = self.client.get(reverse('shop-car-detail', args=[self.car.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Service checklist')
        self.assertContains(response, 'https://drive.google.com/file/d/456/view')

    def test_attachment_file_sets_private_cache_headers(self):
        report = Report.objects.create(
            car=self.car,
            job_name='Cached report',
            date_done='2026-08-10',
        )
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(report),
            object_id=str(report.pk),
            file=SimpleUploadedFile('cached.pdf', b'%PDF-1.4 cached', content_type='application/pdf'),
        )

        try:
            self.client.force_login(self.user)
            response = self.client.get(reverse('shop-attachment-file', args=[attachment.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(response['Pragma'], 'no-cache')
        finally:
            attachment.file.delete(save=False)

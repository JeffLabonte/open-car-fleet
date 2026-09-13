from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from openpyxl import load_workbook
from shop.exporters import export_garage_to_excel
from shop.forms import ReportForm
from shop.models.car import Car
from shop.models.garage import Garage
from shop.models.garage import GarageMembership
from shop.models.user import ShopUser
from shop.tests.helpers import PNG_SIGNATURE


class SecurityHardeningTests(TestCase):
    """Regression tests for security audit fixes."""

    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='security-owner',
            email='security-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Security Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Toyota',
            model='Yaris',
            vin='JTDKB20U793512349',
        )

    def test_login_page_rejects_javascript_next_url(self):
        response = self.client.get(reverse('shop-login'), {'next': 'javascript:alert(document.cookie)'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'javascript:alert')
        self.assertContains(response, "const nextUrl = '/';")

    def test_theme_view_rejects_absolute_next_url(self):
        response = self.client.get(reverse('shop-theme', args=['light']), {'next': 'https://evil.example.com'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('shop-index'))

    def test_theme_view_allows_local_next_url(self):
        response = self.client.get(reverse('shop-theme', args=['dark']), {'next': '/cars/'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/cars/')

    def test_report_attachment_rejects_disallowed_extension(self):
        form = ReportForm(
            data={
                'mileage': '',
                'job_name': 'Oil change',
                'date_done': '2026-01-15',
                'note': '',
                'additional_information': '',
            },
            files={
                'attachments': SimpleUploadedFile(
                    'payload.html',
                    b'<html></html>',
                    content_type='image/jpeg',
                ),
            },
            user=self.owner,
            garage=self.garage,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

    def test_report_attachment_rejects_spoofed_magic_bytes(self):
        form = ReportForm(
            data={
                'mileage': '',
                'job_name': 'Oil change',
                'date_done': '2026-01-15',
                'note': '',
                'additional_information': '',
            },
            files={
                'attachments': SimpleUploadedFile(
                    'payload.png',
                    b'<html><script>alert(1)</script></html>',
                    content_type='image/png',
                ),
            },
            user=self.owner,
            garage=self.garage,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

    def test_report_attachment_rejects_oversized_upload(self):
        from shop.forms.base import ATTACHMENT_MAX_UPLOAD_BYTES

        form = ReportForm(
            data={
                'mileage': '',
                'job_name': 'Oil change',
                'date_done': '2026-01-15',
                'note': '',
                'additional_information': '',
            },
            files={
                'attachments': SimpleUploadedFile(
                    'large.png',
                    PNG_SIGNATURE + b'0' * (ATTACHMENT_MAX_UPLOAD_BYTES + 1),
                    content_type='image/png',
                ),
            },
            user=self.owner,
            garage=self.garage,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

    def test_report_attachment_rejects_too_many_files(self):
        from shop.forms.base import ATTACHMENT_MAX_FILES

        form = ReportForm(
            data={
                'mileage': '',
                'job_name': 'Oil change',
                'date_done': '2026-01-15',
                'note': '',
                'additional_information': '',
            },
            files={
                'attachments': [
                    SimpleUploadedFile(f'photo-{index}.png', PNG_SIGNATURE, content_type='image/png')
                    for index in range(ATTACHMENT_MAX_FILES + 1)
                ],
            },
            user=self.owner,
            garage=self.garage,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

    def test_set_test_session_is_disabled_in_production(self):
        response = self.client.get(reverse('shop-set-test-session'), {'email': 'e2e@example.com'})
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=True)
    def test_set_test_session_signs_user_in_when_debug(self):
        response = self.client.get(
            reverse('shop-set-test-session'),
            {'email': 'e2e-user@example.com', 'next': '/cars/'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/cars/')
        self.assertTrue(self.client.session.get('_auth_user_id'))

    @override_settings(DEBUG=True)
    def test_set_test_session_requires_email(self):
        response = self.client.get(reverse('shop-set-test-session'), {'next': '/cars/'})
        self.assertEqual(response.status_code, 400)

    def test_excel_export_neutralizes_formula_injection(self):
        self.garage.name = "=cmd|'/c calc'!A0"
        self.garage.save(update_fields=['name'])
        workbook_file = export_garage_to_excel(self.garage)
        workbook = load_workbook(filename=BytesIO(workbook_file.content))
        garage_name_cell = workbook['garage'].cell(row=2, column=2).value
        self.assertEqual(garage_name_cell, "'=cmd|'/c calc'!A0")

    def test_known_shop_create_invalid_post_returns_form_not_500(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('shop-known-shop-create'), data={'name': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add shop')

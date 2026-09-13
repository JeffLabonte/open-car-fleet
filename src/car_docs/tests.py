from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from car_docs.forms import CarDocForm
from car_docs.models import CarDoc
from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership
from shop.models.user import ShopUser

PDF_SIGNATURE = b'%PDF-1.4'
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR'


class CarDocAttachmentValidationTests(TestCase):
    def test_car_doc_form_rejects_spoofed_pdf_content(self):
        form = CarDocForm(
            data={'title': 'Malware'},
            files={
                'attachments': SimpleUploadedFile(
                    'malware.pdf',
                    b'MZ-not-a-pdf',
                    content_type='application/pdf',
                ),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

    def test_car_doc_form_rejects_plain_text_upload(self):
        form = CarDocForm(
            data={'title': 'Notes'},
            files={
                'attachments': SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain'),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn('attachments', form.errors)

    def test_car_doc_form_accepts_valid_pdf_upload(self):
        form = CarDocForm(
            data={'title': 'Manual', 'content': 'Owner manual'},
            files={
                'attachments': SimpleUploadedFile(
                    'manual.pdf',
                    PDF_SIGNATURE + b' manual',
                    content_type='application/pdf',
                ),
            },
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_car_doc_form_accepts_valid_image_upload(self):
        form = CarDocForm(
            data={'title': 'Photo'},
            files={
                'attachments': SimpleUploadedFile('photo.png', PNG_SIGNATURE, content_type='image/png'),
            },
        )

        self.assertTrue(form.is_valid(), form.errors)


class CarDocAttachmentStorageTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='pdf-user',
            email='pdf@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Garage One', created_by=self.owner)
        GarageMembership.objects.create(garage=self.garage, user=self.owner, role=GarageMembership.ROLE_OWNER)
        self.car = Car.objects.create(
            garage=self.garage,
            make='Ford',
            model='Transit',
            colour='Blue',
            year=2024,
            vin='1HGBH41JXMN109186',
            license_plate='ABC-123',
        )

    def _create_doc_with_pdf(self, title: str) -> tuple[CarDoc, Attachment]:
        doc = CarDoc.objects.create(car=self.car, title=title, content='PDF reference doc')
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(doc),
            object_id=str(doc.pk),
            file=SimpleUploadedFile('manual.pdf', PDF_SIGNATURE + b' manual', content_type='application/pdf'),
        )
        return doc, attachment

    def test_car_doc_accepts_pdf_upload(self):
        doc, attachment = self._create_doc_with_pdf('Owner manual')
        self.addCleanup(attachment.file.delete, save=False)

        attachment.file.seek(0)
        with attachment.file.open('rb') as stored_file:
            saved_contents = stored_file.read()

        self.assertTrue(attachment.file.name.lower().endswith('.pdf'))
        self.assertEqual(saved_contents, PDF_SIGNATURE + b' manual')
        self.assertEqual(attachment.kind, 'document')
        self.assertEqual(doc.attachments.count(), 1)

    def test_deleting_car_doc_removes_uploaded_file(self):
        doc, attachment = self._create_doc_with_pdf('Delete me')
        file_name = attachment.file.name

        doc.delete()

        self.assertFalse(CarDoc.objects.filter(title='Delete me').exists())
        self.assertFalse(Attachment.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(attachment.file.storage.exists(file_name))


class CarDocFileAccessTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='doc-owner',
            email='doc-owner@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='doc-stranger',
            email='doc-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Document Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        self.car = Car.objects.create(
            garage=self.garage,
            make='Ford',
            model='Focus',
            vin='1FAHP3F28CL512345',
        )
        self.doc = CarDoc.objects.create(car=self.car, title='Registration')
        self.attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(self.doc),
            object_id=str(self.doc.pk),
            file=SimpleUploadedFile(
                'registration.pdf',
                b'%PDF-1.4 protected document',
                content_type='application/pdf',
            ),
        )

    def tearDown(self) -> None:
        self.attachment.file.delete(save=False)

    def test_authenticated_garage_member_can_stream_car_document(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('shop-attachment-file', args=[self.attachment.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 protected document')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_anonymous_user_is_redirected_from_car_document_file(self):
        response = self.client.get(reverse('shop-attachment-file', args=[self.attachment.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('shop-login'), response['Location'])

    def test_user_outside_the_garage_cannot_stream_car_document(self):
        self.client.force_login(self.stranger)

        response = self.client.get(reverse('shop-attachment-file', args=[self.attachment.pk]))

        self.assertEqual(response.status_code, 404)

    def test_raw_media_url_does_not_expose_car_document(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.attachment.file.url)

        self.assertEqual(response.status_code, 404)

    def test_car_document_crud_views_cover_read_write_and_delete_paths(self):
        self.client.force_login(self.owner)

        self.assertEqual(
            self.client.get(reverse('shop-car-doc-list', args=[self.car.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse('shop-car-doc-detail', args=[self.car.pk, self.doc.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse('shop-car-doc-create', args=[self.car.pk])).status_code,
            200,
        )

        invalid_response = self.client.post(
            reverse('shop-car-doc-create', args=[self.car.pk]),
            data={'title': '', 'content': 'Missing title'},
        )
        self.assertEqual(invalid_response.status_code, 200)

        create_response = self.client.post(
            reverse('shop-car-doc-create', args=[self.car.pk]),
            data={
                'title': 'Created document',
                'content': 'Created content',
                'attachments': SimpleUploadedFile(
                    'created.pdf',
                    PDF_SIGNATURE + b' created',
                    content_type='application/pdf',
                ),
            },
        )
        self.assertEqual(create_response.status_code, 302)
        created_doc = CarDoc.objects.get(title='Created document')
        self.assertTrue(created_doc.attachments.filter(kind='document').exists())

        self.assertEqual(
            self.client.get(reverse('shop-car-doc-update', args=[self.car.pk, self.doc.pk])).status_code,
            200,
        )
        update_response = self.client.post(
            reverse('shop-car-doc-update', args=[self.car.pk, self.doc.pk]),
            data={'title': 'Updated registration', 'content': 'Updated content'},
        )
        self.assertEqual(update_response.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, 'Updated registration')

        self.assertEqual(
            self.client.get(reverse('shop-car-doc-delete', args=[self.car.pk, self.doc.pk])).status_code,
            200,
        )
        delete_response = self.client.post(
            reverse('shop-car-doc-delete', args=[self.car.pk, self.doc.pk]),
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(CarDoc.objects.filter(pk=self.doc.pk).exists())
        created_doc.delete()

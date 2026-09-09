from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from car_docs.forms import CarDocForm
from car_docs.models import CarDoc
from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership
from shop.models.user import ShopUser


class CarDocPdfUploadTests(TestCase):
    def test_car_doc_form_rejects_spoofed_pdf_content(self):
        form = CarDocForm(
            data={'title': 'Malware'},
            files={
                'file': SimpleUploadedFile(
                    'malware.pdf',
                    b'MZ-not-a-pdf',
                    content_type='application/pdf',
                ),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

    def test_car_doc_accepts_pdf_upload(self):
        user = ShopUser.objects.create_user(username='pdf-user', email='pdf@example.com', password='pass1234')
        garage = Garage.objects.create(name='Garage One', created_by=user)
        GarageMembership.objects.create(garage=garage, user=user, role=GarageMembership.ROLE_OWNER)
        car = Car.objects.create(
            garage=garage,
            make='Ford',
            model='Transit',
            colour='Blue',
            year=2024,
            vin='1HGBH41JXMN109186',
            license_plate='ABC-123',
        )

        pdf = SimpleUploadedFile('manual.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF', content_type='application/pdf')

        doc = CarDoc.objects.create(
            car=car,
            title='Owner manual',
            content='PDF reference doc',
            file=pdf,
        )

        pdf.seek(0)
        with open(doc.file.path, 'rb') as uploaded_file:
            saved_contents = uploaded_file.read()

        self.assertTrue(doc.file.name.lower().endswith('.pdf'))
        self.assertEqual(saved_contents, pdf.read())

    def test_deleting_car_doc_removes_uploaded_file(self):
        user = ShopUser.objects.create_user(username='delete-pdf-user', email='delete-pdf@example.com', password='pass1234')
        garage = Garage.objects.create(name='Delete Garage', created_by=user)
        GarageMembership.objects.create(garage=garage, user=user, role=GarageMembership.ROLE_OWNER)
        car = Car.objects.create(garage=garage, make='Ford', model='Transit', vin='1HGBH41JXMN109187')
        doc = CarDoc.objects.create(
            car=car,
            title='Delete me',
            file=SimpleUploadedFile('delete-me.pdf', b'%PDF-1.4', content_type='application/pdf'),
        )
        file_name = doc.file.name

        doc.delete()

        self.assertFalse(CarDoc.objects.filter(title='Delete me').exists())
        self.assertFalse(doc.file.storage.exists(file_name))


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
        self.doc = CarDoc.objects.create(
            car=self.car,
            title='Registration',
            file=SimpleUploadedFile(
                'registration.pdf',
                b'%PDF-1.4 protected document',
                content_type='application/pdf',
            ),
        )

    def tearDown(self) -> None:
        self.doc.file.delete(save=False)

    def test_authenticated_garage_member_can_stream_car_document(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('shop-car-doc-file', args=[self.car.pk, self.doc.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 protected document')

    def test_anonymous_user_is_redirected_from_car_document_file(self):
        response = self.client.get(reverse('shop-car-doc-file', args=[self.car.pk, self.doc.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('shop-login'), response['Location'])

    def test_user_outside_the_garage_cannot_stream_car_document(self):
        self.client.force_login(self.stranger)

        response = self.client.get(reverse('shop-car-doc-file', args=[self.car.pk, self.doc.pk]))

        self.assertEqual(response.status_code, 404)

    def test_raw_media_url_does_not_expose_car_document(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.doc.file.url)

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
                'file': SimpleUploadedFile('created.pdf', b'%PDF-1.4 created', content_type='application/pdf'),
            },
        )
        self.assertEqual(create_response.status_code, 302)
        created_doc = CarDoc.objects.get(title='Created document')

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

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from car_docs.models import CarDoc
from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership
from shop.models.user import ShopUser


class CarDocPdfUploadTests(TestCase):
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

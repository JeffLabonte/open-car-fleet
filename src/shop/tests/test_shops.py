from pathlib import Path
from unittest.mock import patch
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from shop.models.attachment import Attachment
from shop.models.garage import Garage
from shop.models.garage import GarageInvitation
from shop.models.garage import GarageMembership
from shop.models.garage import KnownShop
from shop.models.garage import KnownShopProof
from shop.models.user import ShopUser


class KnownShopTests(TestCase):
    def setUp(self) -> None:
        self.user = ShopUser.objects.create_user(
            username='shop-user',
            email='shop-user@example.com',
            password='pass1234',
        )
        self.other_user = ShopUser.objects.create_user(
            username='other-shop-user',
            email='other-shop-user@example.com',
            password='pass1234',
        )

    def test_user_can_add_shop_and_proof(self):
        self.client.force_login(self.user)

        shop_response = self.client.post(
            reverse('shop-known-shop-create'),
            data={
                'name': 'Northside Auto',
                'email': 'service@northside.example',
                'phone': '555-0100',
                'address': '10 Main Street',
                'notes': 'Recommended by the fleet manager.',
            },
        )

        self.assertEqual(shop_response.status_code, 302)
        shop = KnownShop.objects.get(name='Northside Auto')
        self.assertEqual(shop.created_by, self.user)
        proof_response = self.client.post(
            reverse('shop-known-shop-proof-create', args=[shop.pk]),
            data={
                'title': 'Business registration',
                'content': 'Registration document received.',
                'attachments': SimpleUploadedFile('registration.pdf', b'%PDF-1.4 proof', content_type='application/pdf'),
            },
        )

        self.assertEqual(proof_response.status_code, 302)
        proof = KnownShopProof.objects.get(shop=shop)
        self.assertEqual(proof.title, 'Business registration')
        attachment = proof.attachments.get()
        self.assertIn('registration', attachment.file.name)
        self.assertTrue(attachment.file.name.endswith('.pdf'))

    def test_other_user_cannot_view_or_add_proof_to_owned_shop(self):
        shop = KnownShop.objects.create(name='Private Shop', created_by=self.user)
        self.client.force_login(self.other_user)

        detail_response = self.client.get(reverse('shop-known-shop-detail', args=[shop.pk]))
        proof_response = self.client.get(reverse('shop-known-shop-proof-create', args=[shop.pk]))

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(proof_response.status_code, 404)

    def test_known_shop_model_str_and_invitation_methods(self):
        shop = KnownShop.objects.create(name='Str Shop', created_by=self.user)
        self.assertEqual(str(shop), 'Str Shop')

        proof = KnownShopProof.objects.create(shop=shop, title='Str Proof')
        self.assertEqual(str(proof), 'Str Proof (Str Shop)')

        garage = Garage.objects.create(name='Str Garage', created_by=self.user)
        membership = GarageMembership.objects.create(
            garage=garage,
            user=self.user,
            role=GarageMembership.ROLE_OWNER,
        )
        self.assertIn('owner', str(membership))

        invitation = GarageInvitation.objects.create(
            garage=garage,
            invited_email='invite@example.com',
            invited_by=self.user,
        )
        self.assertIn('invite@example.com', str(invitation))

        with patch('shop.models.garage.send_mail', return_value=1):
            sent_count = invitation.send_invitation_email(
                accept_base_url='https://example.com/accept',
                sender_email='from@example.com',
            )
        self.assertEqual(sent_count, 1)

        invitation_with_message = GarageInvitation.objects.create(
            garage=garage,
            invited_email='invite-message@example.com',
            invited_by=self.user,
            message='Please join our fleet.',
        )
        with patch('shop.models.garage.send_mail', return_value=1) as mock_send:
            invitation_with_message.send_invitation_email(accept_base_url='https://example.com/accept')
            self.assertIn('Please join our fleet.', mock_send.call_args[1]['message'])

    def test_known_shop_proof_file_deleted_on_model_delete(self):
        shop = KnownShop.objects.create(name='Delete Proof Shop', created_by=self.user)
        proof = KnownShopProof.objects.create(shop=shop, title='Delete proof')
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(proof),
            object_id=str(proof.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile('delete.pdf', b'%PDF-1.4 delete', content_type='application/pdf'),
        )
        file_path = attachment.file.path
        self.assertTrue(Path(file_path).exists())
        proof.delete()
        self.assertFalse(Path(file_path).exists())

    def test_known_shop_proof_file_requires_authentication(self):
        self.client.force_login(self.user)
        shop = KnownShop.objects.create(name='Proof Shop', created_by=self.user)
        proof = KnownShopProof.objects.create(shop=shop, title='Insurance proof')
        attachment = Attachment.objects.create(
            content_type=ContentType.objects.get_for_model(proof),
            object_id=str(proof.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=SimpleUploadedFile(
                'insurance.pdf',
                b'%PDF-1.4 shop proof',
                content_type='application/pdf',
            ),
        )

        try:
            response = self.client.get(
                reverse('shop-attachment-file', args=[attachment.pk]),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 shop proof')
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

            self.client.logout()
            anonymous_response = self.client.get(
                reverse('shop-attachment-file', args=[attachment.pk]),
            )
            self.assertEqual(anonymous_response.status_code, 302)
        finally:
            attachment.file.delete(save=False)

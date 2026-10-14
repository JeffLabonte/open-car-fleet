from django.db import IntegrityError, transaction
from django.test import TestCase

from shop.auth import sync_hanko_user
from shop.models.user import ShopUser


class ShopUserIdentityTests(TestCase):
    def test_non_empty_emails_are_unique_case_insensitively(self):
        ShopUser.objects.create_user(
            username='identity-one',
            email='Identity@example.com',
            password='pass1234',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShopUser.objects.create_user(
                    username='identity-two',
                    email='identity@example.com',
                    password='pass1234',
                )

    def test_hanko_email_is_normalized_before_account_creation(self):
        user = sync_hanko_user(
            hanko_id='normalized-hanko-id',
            email='  User@Example.COM ',
            username='Normalized User',
        )

        self.assertEqual(user.email, 'user@example.com')



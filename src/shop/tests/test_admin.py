from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from shop.admin import AttachmentAdmin
from shop.models.attachment import Attachment
from shop.models.user import ShopUser


class AttachmentAdminTests(TestCase):
    def test_parent_label_handles_staged_attachment(self):
        """Staged uploads have no parent; the admin changelist must not crash."""
        staged = Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            display_name='staged.png',
        )

        admin = AttachmentAdmin(Attachment, AdminSite())
        self.assertEqual(str(admin.parent_label(staged)), 'Staged upload')

    def test_admin_changelist_with_staged_attachment(self):
        """The changelist view must render when staged attachments exist."""
        user = ShopUser.objects.create_superuser(
            username='admin-staged',
            email='admin-staged@example.com',
            password='adminpass123',
        )
        Attachment.objects.create(
            source_type=Attachment.SOURCE_UPLOAD,
            display_name='staged.png',
        )

        factory = RequestFactory()
        request = factory.get('/admin/shop/attachment/')
        request.user = user

        admin = AttachmentAdmin(Attachment, AdminSite())
        response = admin.changelist_view(request)
        self.assertEqual(response.status_code, 200)

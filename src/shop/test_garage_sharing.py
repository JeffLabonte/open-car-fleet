from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from shop.models.garage import Garage, GarageInvitation, GarageMembership
from shop.models.user import ShopUser


class GarageSharingRoleModelTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='role-owner',
            email='role-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Role Garage', created_by=self.owner)

    def test_membership_has_audit_timestamps(self):
        membership = GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        self.assertIsNotNone(membership.created_at)
        self.assertIsNotNone(membership.updated_at)

    def test_owner_can_assign_non_owner_roles(self):
        admin = ShopUser.objects.create_user(
            username='role-admin',
            email='role-admin@example.com',
            password='pass1234',
        )
        membership = GarageMembership.objects.create(
            garage=self.garage,
            user=admin,
            role=GarageMembership.ROLE_ADMIN,
        )
        self.assertEqual(membership.role, GarageMembership.ROLE_ADMIN)

    def test_invalid_role_is_rejected(self):
        user = ShopUser.objects.create_user(
            username='role-user',
            email='role-user@example.com',
            password='pass1234',
        )
        membership = GarageMembership(
            garage=self.garage,
            user=user,
            role='superuser',
        )
        with self.assertRaises(Exception):
            membership.full_clean()

    def test_duplicate_membership_is_rejected(self):
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        duplicate = GarageMembership(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_VIEWER,
        )
        with self.assertRaises(Exception):
            duplicate.save()


class GarageSharingInvitationRoleTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='invite-owner',
            email='invite-owner@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Invite Role Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )

    @patch('shop.models.garage.send_mail', return_value=1)
    def test_invitation_can_specify_role(self, _mock_send_mail: object):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': 'mechanic@example.com',
                'message': 'Join as mechanic',
                'expires_in_days': 14,
                'role': GarageMembership.ROLE_MECHANIC,
            },
        )
        self.assertEqual(response.status_code, 302)
        invitation = GarageInvitation.objects.get(garage=self.garage, invited_email='mechanic@example.com')
        self.assertEqual(invitation.role, GarageMembership.ROLE_MECHANIC)

    @patch('shop.models.garage.send_mail', return_value=1)
    def test_invitation_defaults_to_viewer_role(self, _mock_send_mail: object):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-garage-share', args=[self.garage.pk]),
            data={
                'invited_email': 'viewer@example.com',
                'message': 'Join as viewer',
                'expires_in_days': 14,
            },
        )
        self.assertEqual(response.status_code, 302)
        invitation = GarageInvitation.objects.get(garage=self.garage, invited_email='viewer@example.com')
        self.assertEqual(invitation.role, GarageMembership.ROLE_VIEWER)


class GarageSharingMemberManagementTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='mgmt-owner',
            email='mgmt-owner@example.com',
            password='pass1234',
        )
        self.admin = ShopUser.objects.create_user(
            username='mgmt-admin',
            email='mgmt-admin@example.com',
            password='pass1234',
        )
        self.viewer = ShopUser.objects.create_user(
            username='mgmt-viewer',
            email='mgmt-viewer@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='mgmt-stranger',
            email='mgmt-stranger@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Mgmt Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )
        self.admin_membership = GarageMembership.objects.create(
            garage=self.garage,
            user=self.admin,
            role=GarageMembership.ROLE_ADMIN,
        )
        self.viewer_membership = GarageMembership.objects.create(
            garage=self.garage,
            user=self.viewer,
            role=GarageMembership.ROLE_VIEWER,
        )

    def test_owner_can_list_members(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-garage-members', args=[self.garage.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('members', response.context)
        member_emails = {m.user.email for m in response.context['members']}
        self.assertIn(self.owner.email, member_emails)
        self.assertIn(self.admin.email, member_emails)
        self.assertIn(self.viewer.email, member_emails)

    def test_owner_can_change_member_role(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-garage-member-role', args=[self.garage.pk, self.viewer_membership.pk]),
            data={'role': GarageMembership.ROLE_MECHANIC},
        )
        self.assertEqual(response.status_code, 302)
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.role, GarageMembership.ROLE_MECHANIC)

    def test_admin_cannot_promote_to_admin_or_owner(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('shop-garage-member-role', args=[self.garage.pk, self.viewer_membership.pk]),
            data={'role': GarageMembership.ROLE_ADMIN},
        )
        self.assertEqual(response.status_code, 302)
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.role, GarageMembership.ROLE_VIEWER)

    def test_viewer_cannot_change_roles(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse('shop-garage-member-role', args=[self.garage.pk, self.admin_membership.pk]),
            data={'role': GarageMembership.ROLE_VIEWER},
        )
        self.assertEqual(response.status_code, 302)
        self.admin_membership.refresh_from_db()
        self.assertEqual(self.admin_membership.role, GarageMembership.ROLE_ADMIN)

    def test_owner_can_remove_member(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-garage-member-remove', args=[self.garage.pk, self.viewer_membership.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            GarageMembership.objects.filter(pk=self.viewer_membership.pk).exists()
        )

    def test_cannot_remove_last_owner(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-garage-member-remove', args=[self.garage.pk, self._owner_membership().pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GarageMembership.objects.filter(pk=self._owner_membership().pk).exists()
        )

    def test_stranger_gets_404_for_member_list(self):
        other_garage = Garage.objects.create(name='Other Garage', created_by=self.stranger)
        GarageMembership.objects.create(
            garage=other_garage,
            user=self.stranger,
            role=GarageMembership.ROLE_OWNER,
        )
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('shop-garage-members', args=[self.garage.pk]))
        self.assertEqual(response.status_code, 404)

    def _owner_membership(self):
        return GarageMembership.objects.get(garage=self.garage, user=self.owner)


class GarageSharingAcceptDeclineTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='accept-owner',
            email='accept-owner@example.com',
            password='pass1234',
        )
        self.invitee = ShopUser.objects.create_user(
            username='accept-invitee',
            email='accept-invitee@example.com',
            password='pass1234',
        )
        self.garage = Garage.objects.create(name='Accept Garage', created_by=self.owner)
        GarageMembership.objects.create(
            garage=self.garage,
            user=self.owner,
            role=GarageMembership.ROLE_OWNER,
        )

    @patch('shop.models.garage.send_mail', return_value=1)
    def test_accept_invitation_uses_invited_role_on_post(self, _mock_send_mail: object):
        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            role=GarageMembership.ROLE_MECHANIC,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )
        self.client.force_login(self.invitee)

        response = self.client.post(reverse('shop-garage-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        membership = GarageMembership.objects.get(garage=self.garage, user=self.invitee)
        self.assertEqual(membership.role, GarageMembership.ROLE_MECHANIC)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_ACCEPTED)

    def test_get_accept_does_not_mutate(self):
        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            role=GarageMembership.ROLE_VIEWER,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )
        self.client.force_login(self.invitee)

        response = self.client.get(reverse('shop-garage-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_PENDING)
        self.assertFalse(GarageMembership.objects.filter(garage=self.garage, user=self.invitee).exists())

    def test_decline_invitation_sets_status(self):
        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            role=GarageMembership.ROLE_VIEWER,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )
        self.client.force_login(self.invitee)

        response = self.client.post(reverse('shop-garage-invitation-decline', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_DECLINED)
        self.assertFalse(GarageMembership.objects.filter(garage=self.garage, user=self.invitee).exists())

    def test_expired_invitation_is_not_accepted(self):
        invitation = GarageInvitation.objects.create(
            garage=self.garage,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=GarageInvitation.STATUS_PENDING,
            role=GarageMembership.ROLE_VIEWER,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        self.client.force_login(self.invitee)

        response = self.client.post(reverse('shop-garage-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, GarageInvitation.STATUS_EXPIRED)
        self.assertFalse(GarageMembership.objects.filter(garage=self.garage, user=self.invitee).exists())

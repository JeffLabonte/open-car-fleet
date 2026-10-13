from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from shop.models.car import Car
from shop.models.fleet import Fleet
from shop.models.fleet import FleetInvitation
from shop.models.fleet import FleetMembership
from shop.models.user import ShopUser


class FleetSharingTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='pass1234',
        )
        self.member = ShopUser.objects.create_user(
            username='member',
            email='member@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='stranger',
            email='stranger@example.com',
            password='pass1234',
        )
        self.fleet = Fleet.objects.create(name='Alpha Fleet', created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )


    def test_create_fleet_adds_owner_membership(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-fleet-create'),
            data={'name': 'Second Fleet', 'description': 'Family vehicles'},
        )

        self.assertEqual(response.status_code, 302)
        created = Fleet.objects.get(name='Second Fleet')
        self.assertTrue(
            FleetMembership.objects.filter(
                fleet=created,
                user=self.owner,
                role=FleetMembership.ROLE_OWNER,
            ).exists()
        )

    @patch('shop.models.fleet.send_mail', return_value=1)
    def test_share_fleet_creates_pending_invitation(self, _mock_send_mail: object):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-fleet-share', args=[self.fleet.pk]),
            data={
                'invited_email': 'member@example.com',
                'message': 'Join this fleet.',
                'expires_in_days': 14,
            },
        )

        self.assertEqual(response.status_code, 302)
        invitation = FleetInvitation.objects.get(fleet=self.fleet, invited_email='member@example.com')
        self.assertEqual(invitation.status, FleetInvitation.STATUS_PENDING)
        self.assertEqual(invitation.invited_by, self.owner)
        self.assertIsNotNone(invitation.expires_at)

    @patch('shop.models.fleet.send_mail', return_value=1)
    def test_duplicate_pending_invitation_is_not_created(self, _mock_send_mail: object):
        self.client.force_login(self.owner)
        FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )

        response = self.client.post(
            reverse('shop-fleet-share', args=[self.fleet.pk]),
            data={
                'invited_email': 'member@example.com',
                'message': 'Second invite',
                'expires_in_days': 14,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            FleetInvitation.objects.filter(
                fleet=self.fleet,
                invited_email='member@example.com',
                status=FleetInvitation.STATUS_PENDING,
            ).count(),
            1,
        )

    @patch('shop.models.fleet.send_mail', return_value=1)
    def test_accept_invitation_adds_membership(self, _mock_send_mail: object):
        invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )
        self.client.force_login(self.member)

        response = self.client.post(reverse('shop-fleet-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            FleetMembership.objects.filter(
                fleet=self.fleet,
                user=self.member,
            ).exists()
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, FleetInvitation.STATUS_ACCEPTED)
        self.assertEqual(invitation.accepted_by, self.member)

    def test_accept_invitation_requires_matching_email(self):
        invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='member@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )
        self.client.force_login(self.stranger)

        response = self.client.get(reverse('shop-fleet-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            FleetMembership.objects.filter(
                fleet=self.fleet,
                user=self.stranger,
            ).exists()
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, FleetInvitation.STATUS_PENDING)

    def test_non_manager_cannot_share_fleet(self):
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.member,
            role=FleetMembership.ROLE_MEMBER,
        )
        self.client.force_login(self.member)

        response = self.client.get(reverse('shop-fleet-share', args=[self.fleet.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-fleet-detail', args=[self.fleet.pk]))

    def test_owner_can_delete_car_from_car_list(self):
        self.client.force_login(self.owner)
        car = Car.objects.create(
            fleet=self.fleet,
            make='Toyota',
            model='Yaris',
            vin='JTDKB20U793512345',
        )

        response = self.client.post(reverse('shop-car-delete', args=[car.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('shop-car-list'))
        self.assertFalse(Car.objects.filter(pk=car.pk).exists())


class FleetSharingRoleModelTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='role-owner',
            email='role-owner@example.com',
            password='pass1234',
        )
        self.fleet = Fleet.objects.create(name='Role Fleet', created_by=self.owner)

    def test_membership_has_audit_timestamps(self):
        membership = FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )
        self.assertIsNotNone(membership.created_at)
        self.assertIsNotNone(membership.updated_at)

    def test_owner_can_assign_non_owner_roles(self):
        admin = ShopUser.objects.create_user(
            username='role-admin',
            email='role-admin@example.com',
            password='pass1234',
        )
        membership = FleetMembership.objects.create(
            fleet=self.fleet,
            user=admin,
            role=FleetMembership.ROLE_ADMIN,
        )
        self.assertEqual(membership.role, FleetMembership.ROLE_ADMIN)

    def test_invalid_role_is_rejected(self):
        user = ShopUser.objects.create_user(
            username='role-user',
            email='role-user@example.com',
            password='pass1234',
        )
        membership = FleetMembership(
            fleet=self.fleet,
            user=user,
            role='superuser',
        )
        with self.assertRaises(Exception):
            membership.full_clean()

    def test_duplicate_membership_is_rejected(self):
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )
        duplicate = FleetMembership(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_VIEWER,
        )
        with self.assertRaises(Exception):
            duplicate.save()


class FleetSharingInvitationRoleTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='invite-owner',
            email='invite-owner@example.com',
            password='pass1234',
        )
        self.fleet = Fleet.objects.create(name='Invite Role Fleet', created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )

    @patch('shop.models.fleet.send_mail', return_value=1)
    def test_invitation_can_specify_role(self, _mock_send_mail: object):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-share', args=[self.fleet.pk]),
            data={
                'invited_email': 'mechanic@example.com',
                'message': 'Join as mechanic',
                'expires_in_days': 14,
                'role': FleetMembership.ROLE_MECHANIC,
            },
        )
        self.assertEqual(response.status_code, 302)
        invitation = FleetInvitation.objects.get(fleet=self.fleet, invited_email='mechanic@example.com')
        self.assertEqual(invitation.role, FleetMembership.ROLE_MECHANIC)

    @patch('shop.models.fleet.send_mail', return_value=1)
    def test_invitation_defaults_to_viewer_role(self, _mock_send_mail: object):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-share', args=[self.fleet.pk]),
            data={
                'invited_email': 'viewer@example.com',
                'message': 'Join as viewer',
                'expires_in_days': 14,
            },
        )
        self.assertEqual(response.status_code, 302)
        invitation = FleetInvitation.objects.get(fleet=self.fleet, invited_email='viewer@example.com')
        self.assertEqual(invitation.role, FleetMembership.ROLE_VIEWER)


class FleetSharingMemberManagementTests(TestCase):
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
        self.fleet = Fleet.objects.create(name='Mgmt Fleet', created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )
        self.admin_membership = FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.admin,
            role=FleetMembership.ROLE_ADMIN,
        )
        self.viewer_membership = FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.viewer,
            role=FleetMembership.ROLE_VIEWER,
        )

    def test_owner_can_list_members(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('shop-fleet-members', args=[self.fleet.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('members', response.context)
        member_emails = {m.user.email for m in response.context['members']}
        self.assertIn(self.owner.email, member_emails)
        self.assertIn(self.admin.email, member_emails)
        self.assertIn(self.viewer.email, member_emails)

    def test_owner_can_change_member_role(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-member-role', args=[self.fleet.pk, self.viewer_membership.pk]),
            data={'role': FleetMembership.ROLE_MECHANIC},
        )
        self.assertEqual(response.status_code, 302)
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.role, FleetMembership.ROLE_MECHANIC)

    def test_admin_cannot_promote_to_admin_or_owner(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('shop-fleet-member-role', args=[self.fleet.pk, self.viewer_membership.pk]),
            data={'role': FleetMembership.ROLE_ADMIN},
        )
        self.assertEqual(response.status_code, 302)
        self.viewer_membership.refresh_from_db()
        self.assertEqual(self.viewer_membership.role, FleetMembership.ROLE_VIEWER)

    def test_viewer_cannot_change_roles(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse('shop-fleet-member-role', args=[self.fleet.pk, self.admin_membership.pk]),
            data={'role': FleetMembership.ROLE_VIEWER},
        )
        self.assertEqual(response.status_code, 302)
        self.admin_membership.refresh_from_db()
        self.assertEqual(self.admin_membership.role, FleetMembership.ROLE_ADMIN)

    def test_owner_can_remove_member(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-member-remove', args=[self.fleet.pk, self.viewer_membership.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            FleetMembership.objects.filter(pk=self.viewer_membership.pk).exists()
        )

    def test_cannot_remove_last_owner(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-member-remove', args=[self.fleet.pk, self._owner_membership().pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            FleetMembership.objects.filter(pk=self._owner_membership().pk).exists()
        )

    def test_admin_cannot_remove_owner(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('shop-fleet-member-remove', args=[self.fleet.pk, self._owner_membership().pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            FleetMembership.objects.filter(pk=self._owner_membership().pk).exists()
        )

    def test_admin_cannot_demote_owner(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('shop-fleet-member-role', args=[self.fleet.pk, self._owner_membership().pk]),
            data={'role': FleetMembership.ROLE_MECHANIC},
        )
        self.assertEqual(response.status_code, 302)
        self._owner_membership().refresh_from_db()
        self.assertEqual(self._owner_membership().role, FleetMembership.ROLE_OWNER)

    def test_owner_can_remove_admin(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-member-remove', args=[self.fleet.pk, self.admin_membership.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            FleetMembership.objects.filter(pk=self.admin_membership.pk).exists()
        )

    def test_owner_can_demote_admin(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('shop-fleet-member-role', args=[self.fleet.pk, self.admin_membership.pk]),
            data={'role': FleetMembership.ROLE_MECHANIC},
        )
        self.assertEqual(response.status_code, 302)
        self.admin_membership.refresh_from_db()
        self.assertEqual(self.admin_membership.role, FleetMembership.ROLE_MECHANIC)

    def test_admin_can_still_remove_viewer(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('shop-fleet-member-remove', args=[self.fleet.pk, self.viewer_membership.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            FleetMembership.objects.filter(pk=self.viewer_membership.pk).exists()
        )

    def test_stranger_gets_404_for_member_list(self):
        other_fleet = Fleet.objects.create(name='Other Fleet', created_by=self.stranger)
        FleetMembership.objects.create(
            fleet=other_fleet,
            user=self.stranger,
            role=FleetMembership.ROLE_OWNER,
        )
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('shop-fleet-members', args=[self.fleet.pk]))
        self.assertEqual(response.status_code, 404)

    def _owner_membership(self):
        return FleetMembership.objects.get(fleet=self.fleet, user=self.owner)


class FleetSharingPermissionsHierarchyTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='perm-owner',
            email='perm-owner@example.com',
            password='pass1234',
        )
        self.admin = ShopUser.objects.create_user(
            username='perm-admin',
            email='perm-admin@example.com',
            password='pass1234',
        )
        self.mechanic = ShopUser.objects.create_user(
            username='perm-mechanic',
            email='perm-mechanic@example.com',
            password='pass1234',
        )
        self.viewer = ShopUser.objects.create_user(
            username='perm-viewer',
            email='perm-viewer@example.com',
            password='pass1234',
        )
        self.fleet = Fleet.objects.create(name='Perm Fleet', created_by=self.owner)
        FleetMembership.objects.create(fleet=self.fleet, user=self.owner, role=FleetMembership.ROLE_OWNER)
        FleetMembership.objects.create(fleet=self.fleet, user=self.admin, role=FleetMembership.ROLE_ADMIN)
        FleetMembership.objects.create(fleet=self.fleet, user=self.mechanic, role=FleetMembership.ROLE_MECHANIC)
        FleetMembership.objects.create(fleet=self.fleet, user=self.viewer, role=FleetMembership.ROLE_VIEWER)

    def test_role_hierarchy_enforcement(self):
        from shop.permissions import FleetSharingPermissions

        owner_perms = FleetSharingPermissions(self.owner, self.fleet)
        self.assertTrue(owner_perms.can_manage_member(FleetMembership.ROLE_ADMIN))
        self.assertTrue(owner_perms.can_manage_member(FleetMembership.ROLE_VIEWER))

        admin_perms = FleetSharingPermissions(self.admin, self.fleet)
        self.assertTrue(admin_perms.can_manage_member(FleetMembership.ROLE_MECHANIC))
        self.assertTrue(admin_perms.can_manage_member(FleetMembership.ROLE_VIEWER))
        self.assertFalse(admin_perms.can_manage_member(FleetMembership.ROLE_OWNER))
        self.assertFalse(admin_perms.can_manage_member(FleetMembership.ROLE_ADMIN))

        mechanic_perms = FleetSharingPermissions(self.mechanic, self.fleet)
        self.assertFalse(mechanic_perms.can_manage_member(FleetMembership.ROLE_VIEWER))


class FleetSharingAcceptDeclineTests(TestCase):
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
        self.fleet = Fleet.objects.create(name='Accept Fleet', created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )

    @patch('shop.models.fleet.send_mail', return_value=1)
    def test_accept_invitation_uses_invited_role_on_post(self, _mock_send_mail: object):
        invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            role=FleetMembership.ROLE_MECHANIC,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )
        self.client.force_login(self.invitee)

        response = self.client.post(reverse('shop-fleet-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        membership = FleetMembership.objects.get(fleet=self.fleet, user=self.invitee)
        self.assertEqual(membership.role, FleetMembership.ROLE_MECHANIC)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, FleetInvitation.STATUS_ACCEPTED)

    def test_get_accept_does_not_mutate(self):
        invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            role=FleetMembership.ROLE_VIEWER,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )
        self.client.force_login(self.invitee)

        response = self.client.get(reverse('shop-fleet-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, FleetInvitation.STATUS_PENDING)
        self.assertFalse(FleetMembership.objects.filter(fleet=self.fleet, user=self.invitee).exists())

    def test_decline_invitation_sets_status(self):
        invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            role=FleetMembership.ROLE_VIEWER,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )
        self.client.force_login(self.invitee)

        response = self.client.post(reverse('shop-fleet-invitation-decline', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, FleetInvitation.STATUS_DECLINED)
        self.assertFalse(FleetMembership.objects.filter(fleet=self.fleet, user=self.invitee).exists())

    def test_expired_invitation_is_not_accepted(self):
        invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='accept-invitee@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            role=FleetMembership.ROLE_VIEWER,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        self.client.force_login(self.invitee)

        response = self.client.post(reverse('shop-fleet-invitation-accept', args=[invitation.token]))

        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, FleetInvitation.STATUS_EXPIRED)
        self.assertFalse(FleetMembership.objects.filter(fleet=self.fleet, user=self.invitee).exists())


class FleetInvitationCancelTests(TestCase):
    def setUp(self) -> None:
        self.owner = ShopUser.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='pass1234',
        )
        self.stranger = ShopUser.objects.create_user(
            username='stranger',
            email='stranger@example.com',
            password='pass1234',
        )
        self.fleet = Fleet.objects.create(name='Cancel Fleet', created_by=self.owner)
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )
        FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.stranger,
            role=FleetMembership.ROLE_VIEWER,
        )
        self.invitation = FleetInvitation.objects.create(
            fleet=self.fleet,
            invited_email='pending@example.com',
            invited_by=self.owner,
            status=FleetInvitation.STATUS_PENDING,
            role=FleetMembership.ROLE_VIEWER,
            expires_at=timezone.now() + timezone.timedelta(days=14),
        )

    def test_owner_can_cancel_pending_invitation(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-fleet-invitation-cancel', args=[self.fleet.pk, self.invitation.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, FleetInvitation.STATUS_CANCELLED)

    def test_cancelled_invitation_cannot_be_cancelled_again(self):
        self.invitation.status = FleetInvitation.STATUS_CANCELLED
        self.invitation.save()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('shop-fleet-invitation-cancel', args=[self.fleet.pk, self.invitation.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, FleetInvitation.STATUS_CANCELLED)

    def test_non_manager_cannot_cancel_invitation(self):
        self.client.force_login(self.stranger)

        response = self.client.post(
            reverse('shop-fleet-invitation-cancel', args=[self.fleet.pk, self.invitation.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, FleetInvitation.STATUS_PENDING)

    def test_get_request_does_not_cancel(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('shop-fleet-invitation-cancel', args=[self.fleet.pk, self.invitation.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, FleetInvitation.STATUS_PENDING)

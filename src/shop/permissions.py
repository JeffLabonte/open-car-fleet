from typing import Any

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from shop.models.fleet import Fleet, FleetMembership

# Strict role hierarchy used for membership-management authorization.
# Higher number = more privilege. A member may only modify or remove members
# whose role is strictly lower than their own.
ROLE_RANK = {
    FleetMembership.ROLE_VIEWER: 1,
    FleetMembership.ROLE_MECHANIC: 2,
    FleetMembership.ROLE_ADMIN: 3,
    FleetMembership.ROLE_OWNER: 4,
}


class FleetSharingPermissions:
    """Role-based access helpers for a user's relationship with a fleet."""

    MANAGEMENT_ROLES = FleetMembership.MANAGEMENT_ROLES
    WRITE_DATA_ROLES = FleetMembership.WRITE_DATA_ROLES

    def __init__(self, user: Any, fleet: Fleet):
        self.user = user
        self.fleet = fleet
        self.membership: FleetMembership | None = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.user.is_authenticated:
            self.membership = self.fleet.memberships.filter(user=self.user).first()
        self._loaded = True

    @property
    def is_member(self) -> bool:
        self._load()
        return self.membership is not None

    @property
    def role(self) -> str | None:
        self._load()
        return self.membership.role if self.membership else None

    @property
    def is_owner(self) -> bool:
        return self.role == FleetMembership.ROLE_OWNER

    @property
    def is_manager(self) -> bool:
        return self.role in self.MANAGEMENT_ROLES

    @property
    def can_view_fleet(self) -> bool:
        return self.is_member

    @property
    def can_edit_fleet_data(self) -> bool:
        return self.role in self.WRITE_DATA_ROLES

    @property
    def can_manage_members(self) -> bool:
        return self.is_manager

    @property
    def can_invite_with_role(self) -> set[str]:
        """Return the roles the current user may assign when inviting someone."""
        if self.is_owner:
            return {FleetMembership.ROLE_ADMIN, FleetMembership.ROLE_MECHANIC, FleetMembership.ROLE_VIEWER}
        if self.role == FleetMembership.ROLE_ADMIN:
            return {FleetMembership.ROLE_MECHANIC, FleetMembership.ROLE_VIEWER}
        return set()

    @property
    def can_change_role_to(self) -> set[str]:
        """Return the roles the current user may assign when editing an existing membership."""
        if self.is_owner:
            return {FleetMembership.ROLE_ADMIN, FleetMembership.ROLE_MECHANIC, FleetMembership.ROLE_VIEWER}
        if self.role == FleetMembership.ROLE_ADMIN:
            return {FleetMembership.ROLE_MECHANIC, FleetMembership.ROLE_VIEWER}
        return set()

    @property
    def can_remove_members(self) -> bool:
        return self.is_manager

    def can_manage_member(self, target_role: str) -> bool:
        """Return True if this user may modify or remove a member with target_role."""
        own_role = self.role
        if not self.can_manage_members or own_role is None or target_role not in ROLE_RANK:
            return False
        return ROLE_RANK[own_role] > ROLE_RANK[target_role]

    @property
    def can_invite_owners(self) -> bool:
        return self.is_owner


def get_membership_or_404(user: Any, fleet: Fleet) -> FleetMembership:
    """Return the user's active membership or raise Http404 for IDOR protection."""
    membership = fleet.memberships.filter(user=user).first()
    if membership is None:
        raise Http404(_("Membership not found."))
    return membership


def get_fleet_membership_or_404(user: Any, fleet_pk: Any) -> tuple[Fleet, FleetMembership]:
    """Return the fleet scoped to the user's membership and the membership itself."""
    fleet = get_object_or_404(Fleet.objects.filter(members=user), pk=fleet_pk)
    membership = get_membership_or_404(user, fleet)
    return fleet, membership


def user_can_manage_fleet(user: Any, fleet: Fleet) -> bool:
    return FleetSharingPermissions(user, fleet).can_manage_members


def user_can_edit_fleet_data(user: Any, fleet: Fleet) -> bool:
    return FleetSharingPermissions(user, fleet).can_edit_fleet_data


def user_can_view_fleet(user: Any, fleet: Fleet) -> bool:
    return FleetSharingPermissions(user, fleet).can_view_fleet

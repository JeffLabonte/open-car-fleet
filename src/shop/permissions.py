from typing import Any

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from shop.models.garage import Garage, GarageMembership


class GarageSharingPermissions:
    """Role-based access helpers for a user's relationship with a garage."""

    MANAGEMENT_ROLES = GarageMembership.MANAGEMENT_ROLES
    WRITE_DATA_ROLES = GarageMembership.WRITE_DATA_ROLES

    def __init__(self, user: Any, garage: Garage):
        self.user = user
        self.garage = garage
        self.membership: GarageMembership | None = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.user.is_authenticated:
            self.membership = self.garage.memberships.filter(user=self.user).first()
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
        return self.role == GarageMembership.ROLE_OWNER

    @property
    def is_manager(self) -> bool:
        return self.role in self.MANAGEMENT_ROLES

    @property
    def can_view_garage(self) -> bool:
        return self.is_member

    @property
    def can_edit_garage_data(self) -> bool:
        return self.role in self.WRITE_DATA_ROLES

    @property
    def can_manage_members(self) -> bool:
        return self.is_manager

    @property
    def can_invite_with_role(self) -> set[str]:
        """Return the roles the current user may assign when inviting someone."""
        if self.is_owner:
            return {GarageMembership.ROLE_ADMIN, GarageMembership.ROLE_MECHANIC, GarageMembership.ROLE_VIEWER}
        if self.role == GarageMembership.ROLE_ADMIN:
            return {GarageMembership.ROLE_MECHANIC, GarageMembership.ROLE_VIEWER}
        return set()

    @property
    def can_change_role_to(self) -> set[str]:
        """Return the roles the current user may assign when editing an existing membership."""
        if self.is_owner:
            return {GarageMembership.ROLE_ADMIN, GarageMembership.ROLE_MECHANIC, GarageMembership.ROLE_VIEWER}
        if self.role == GarageMembership.ROLE_ADMIN:
            return {GarageMembership.ROLE_MECHANIC, GarageMembership.ROLE_VIEWER}
        return set()

    @property
    def can_remove_members(self) -> bool:
        return self.is_manager

    @property
    def can_invite_owners(self) -> bool:
        return self.is_owner


def get_membership_or_404(user: Any, garage: Garage) -> GarageMembership:
    """Return the user's active membership or raise Http404 for IDOR protection."""
    membership = garage.memberships.filter(user=user).first()
    if membership is None:
        raise Http404(_('Membership not found.'))
    return membership


def get_garage_membership_or_404(user: Any, garage_pk: Any) -> tuple[Garage, GarageMembership]:
    """Return the garage scoped to the user's membership and the membership itself."""
    garage = get_object_or_404(Garage.objects.filter(members=user), pk=garage_pk)
    membership = get_membership_or_404(user, garage)
    return garage, membership


def user_can_manage_garage(user: Any, garage: Garage) -> bool:
    return GarageSharingPermissions(user, garage).is_manager


def user_can_edit_garage_data(user: Any, garage: Garage) -> bool:
    return GarageSharingPermissions(user, garage).can_edit_garage_data


def user_can_view_garage(user: Any, garage: Garage) -> bool:
    return GarageSharingPermissions(user, garage).can_view_garage

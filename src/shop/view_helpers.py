from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q

from shop.models.car import Car
from shop.models.fleet import Fleet, KnownShop
from shop.permissions import (
    FleetSharingPermissions,
    user_can_edit_fleet_data,  # noqa: F401
    user_can_manage_fleet,  # noqa: F401
    user_can_view_fleet,  # noqa: F401
)
from shop.services.attachments import save_attachments  # noqa: F401

SELECTED_FLEET_ID_SESSION_KEY = "selected_fleet_id"


def user_cars_queryset(user: Any):
    return Car.objects.filter(fleet__members=user).distinct()


def user_fleets_queryset(user: Any):
    return Fleet.objects.filter(members=user).distinct()


def set_selected_fleet(request: Any, fleet: Fleet) -> None:
    """Store the given fleet as the user's current fleet in the session."""
    request.session[SELECTED_FLEET_ID_SESSION_KEY] = str(fleet.pk)


def get_selected_fleet(request: Any) -> Fleet | None:
    """Return the fleet currently selected in the session, if any.

    The fleet is only returned if the requesting user is authenticated, is a
    member of the fleet, and has permission to edit fleet data (e.g. add cars).
    Invalid, missing, or inaccessible values are ignored.
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None

    fleet_id = request.session.get(SELECTED_FLEET_ID_SESSION_KEY)
    if not fleet_id:
        return None

    fleet_qs = user_fleets_queryset(user)
    try:
        fleet = fleet_qs.get(pk=fleet_id)
    except (Fleet.DoesNotExist, ValidationError, ValueError, TypeError):
        return None

    if not FleetSharingPermissions(user, fleet).can_edit_fleet_data:
        return None

    return fleet


def user_car_docs_queryset(user: Any):
    from car_docs.models import CarDoc

    return CarDoc.objects.filter(car__fleet__members=user).distinct()


def user_known_shops_queryset(user: Any):
    """Return unowned directory entries and shops owned by the user."""
    return KnownShop.objects.filter(Q(created_by__isnull=True) | Q(created_by=user)).distinct()


def user_can_manage_known_shop(user: Any, shop: KnownShop) -> bool:
    return bool(getattr(user, "is_staff", False) or shop.created_by_id == getattr(user, "pk", None))

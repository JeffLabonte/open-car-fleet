from typing import Any

from django.db.models import Q

from shop.models.car import Car
from shop.models.fleet import Fleet, KnownShop
from shop.permissions import (
    FleetSharingPermissions,
    user_can_edit_fleet_data,
    user_can_manage_fleet,
    user_can_view_fleet,
)
from shop.services.attachments import save_attachments  # noqa: F401


def user_cars_queryset(user: Any):
    return Car.objects.filter(fleet__members=user).distinct()


def user_fleets_queryset(user: Any):
    return Fleet.objects.filter(members=user).distinct()


def user_car_docs_queryset(user: Any):
    from car_docs.models import CarDoc
    return CarDoc.objects.filter(car__fleet__members=user).distinct()


def user_known_shops_queryset(user: Any):
    """Return unowned directory entries and shops owned by the user."""
    return KnownShop.objects.filter(Q(created_by__isnull=True) | Q(created_by=user)).distinct()


def user_can_manage_known_shop(user: Any, shop: KnownShop) -> bool:
    return bool(getattr(user, 'is_staff', False) or shop.created_by_id == getattr(user, 'pk', None))

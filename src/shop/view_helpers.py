from typing import Any

from django.db.models import Q

from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership, KnownShop


def user_cars_queryset(user: Any):
    return Car.objects.filter(garage__members=user).distinct()


def user_garages_queryset(user: Any):
    return Garage.objects.filter(members=user).distinct()


def user_car_docs_queryset(user: Any):
    from car_docs.models import CarDoc
    return CarDoc.objects.filter(car__garage__members=user).distinct()


def user_can_manage_garage(user: Any, garage: Garage) -> bool:
    return garage.memberships.filter(
        user=user,
        role__in=[GarageMembership.ROLE_OWNER, GarageMembership.ROLE_MANAGER],
    ).exists()


def user_known_shops_queryset(user: Any):
    """Return unowned directory entries and shops owned by the user."""
    return KnownShop.objects.filter(Q(created_by__isnull=True) | Q(created_by=user)).distinct()


def user_can_manage_known_shop(user: Any, shop: KnownShop) -> bool:
    return bool(getattr(user, 'is_staff', False) or shop.created_by_id == getattr(user, 'pk', None))

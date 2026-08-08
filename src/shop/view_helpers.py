from typing import Any

from shop.models.car import Car
from shop.models.garage import Garage, GarageMembership


def user_cars_queryset(user: Any):
    return Car.objects.filter(garage__members=user).distinct()


def user_garages_queryset(user: Any):
    return Garage.objects.filter(members=user).distinct()


def user_can_manage_garage(user: Any, garage: Garage) -> bool:
    return garage.memberships.filter(
        user=user,
        role__in=[GarageMembership.ROLE_OWNER, GarageMembership.ROLE_MANAGER],
    ).exists()
from car_docs.models import CarDoc
from shop.models.attachment import Attachment
from shop.models.car import Car, CarPart, CarPartStatusHistory
from shop.models.fleet import (
    Fleet,
    FleetInvitation,
    FleetMembership,
    KnownShop,
    KnownShopProof,
)
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.models.user import ShopUser

__all__ = [
    "Car",
    "CarPart",
    "CarPartStatusHistory",
    "CarDoc",
    "Fleet",
    "FleetInvitation",
    "FleetMembership",
    "KnownShop",
    "KnownShopProof",
    "WorkJob",
    "Report",
    "Attachment",
    "ShopUser",
]

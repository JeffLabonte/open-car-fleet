"""Shared test fixtures and fakes for the shop test modules."""

from django.test import TestCase

from shop.models.car import Car
from shop.models.fleet import Fleet, FleetMembership
from shop.models.user import ShopUser


class FakeHankoResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class ShopTestCase(TestCase):
    """Base test case that creates an owner user, a fleet, and an owner membership."""

    def setUp(self) -> None:
        super().setUp()
        self._vin_counter = 0
        self.owner = self.create_user(
            username="test-owner",
            email="test-owner@example.com",
        )
        self.fleet = Fleet.objects.create(
            name="Test Fleet",
            created_by=self.owner,
        )
        self.owner_membership = FleetMembership.objects.create(
            fleet=self.fleet,
            user=self.owner,
            role=FleetMembership.ROLE_OWNER,
        )

    def create_user(self, **kwargs) -> ShopUser:
        defaults = {
            "username": "test-user",
            "email": "test-user@example.com",
            "password": "pass1234",
        }
        defaults.update(kwargs)
        return ShopUser.objects.create_user(**defaults)

    def add_fleet_member(self, user: ShopUser, role: str = FleetMembership.ROLE_MEMBER) -> FleetMembership:
        return FleetMembership.objects.create(
            fleet=self.fleet,
            user=user,
            role=role,
        )

    def create_car(self, **kwargs) -> Car:
        self._vin_counter += 1
        defaults = {
            "fleet": self.fleet,
            "make": "Honda",
            "model": "Civic",
            "vin": f"2HGFG12698H{self._vin_counter:06d}",
        }
        defaults.update(kwargs)
        return Car.objects.create(**defaults)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
PDF_SIGNATURE = b"%PDF-1.4"
MP4_SIGNATURE = b"\x00\x00\x00\x20ftypisom"

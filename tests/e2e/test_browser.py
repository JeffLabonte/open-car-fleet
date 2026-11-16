import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options

from shop.auth import sync_hanko_user
from shop.models import Car, Fleet, FleetMembership
from tests.e2e.conftest import sign_in_with_test_session


@pytest.fixture
def firefox_driver() -> Iterator[webdriver.Firefox]:
    options = Options()
    options.add_argument("-headless")
    firefox_binary = os.environ.get("FIREFOX_BIN")
    if firefox_binary:
        options.binary_location = firefox_binary

    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(30)
    try:
        yield driver
    finally:
        driver.quit()


def _base_url() -> str:
    return os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def test_anonymous_protected_page_redirects_to_login(firefox_driver: webdriver.Firefox) -> None:
    firefox_driver.get(f"{_base_url()}/cars/")

    parsed_url = urlparse(firefox_driver.current_url)
    assert parsed_url.path == "/login/"
    assert parsed_url.query.startswith("next=")


def test_login_page_renders_in_firefox(firefox_driver: webdriver.Firefox) -> None:
    firefox_driver.get(f"{_base_url()}/login/")

    headings = [element.text for element in firefox_driver.find_elements(By.TAG_NAME, "h1")]
    assert "Sign in" in headings
    assert "Authentication is not configured" in firefox_driver.find_element(By.ID, "hanko-auth-container").text


def test_car_list_actions_fit_phone_viewports(firefox_driver: webdriver.Firefox, django_db_blocker) -> None:
    email = "responsive-owner@example.com"
    with django_db_blocker.unblock():
        owner = sync_hanko_user(
            hanko_id=f"e2e-{email}",
            email=email,
            username="responsive-owner",
            provider="local",
        )
        fleet = Fleet.objects.create(name="Responsive Fleet", created_by=owner)
        FleetMembership.objects.create(fleet=fleet, user=owner, role=FleetMembership.ROLE_OWNER)
        Car.objects.create(fleet=fleet, make="Honda", model="Fit", vin="1HGBH41JXMN109186")
    sign_in_with_test_session(firefox_driver, email, next_url="/cars/")

    for width in (320, 375):
        firefox_driver.set_window_size(width, 800)
        firefox_driver.get(f"{_base_url()}/cars/")
        metrics = firefox_driver.execute_script(
            """
            const form = document.querySelector('.page-actions--car-list .car-search-form');
            const input = form.querySelector('#car-search');
            const button = form.querySelector('button[type="submit"]');
            const add = document.querySelector('.page-actions--car-list a.button');
            return {
              viewportWidth: document.documentElement.clientWidth,
              documentWidth: document.documentElement.scrollWidth,
              inputWidth: input.getBoundingClientRect().width,
              inputTop: input.getBoundingClientRect().top,
              buttonTop: button.getBoundingClientRect().top,
              formBottom: form.getBoundingClientRect().bottom,
              addTop: add.getBoundingClientRect().top
            };
            """
        )

        assert metrics["documentWidth"] <= metrics["viewportWidth"]
        assert metrics["inputWidth"] >= 120
        assert abs(metrics["inputTop"] - metrics["buttonTop"]) < 2
        assert metrics["addTop"] >= metrics["formBottom"]

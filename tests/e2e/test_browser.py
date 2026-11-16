import os
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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
        firefox_driver.get(f"{_base_url()}/cars/")
        # Firefox enforces a minimum outer window width, so use an iframe for phone-sized viewports.
        firefox_driver.execute_script(
            """
            const frame = document.createElement('iframe');
            frame.id = 'phone-viewport';
            frame.style.cssText = `width: ${arguments[0]}px; height: 800px; border: 0`;
            frame.srcdoc = document.documentElement.outerHTML;
            document.body.appendChild(frame);
            """,
            width,
        )
        WebDriverWait(firefox_driver, 10).until(EC.frame_to_be_available_and_switch_to_it((By.ID, "phone-viewport")))
        WebDriverWait(firefox_driver, 10).until(EC.presence_of_element_located((By.ID, "car-search")))
        metrics = firefox_driver.execute_script(
            """
            const form = document.querySelector('.page-actions--car-list .car-search-form');
            const input = form.querySelector('#car-search');
            const button = form.querySelector('button[type="submit"]');
            const add = document.querySelector('.page-actions--car-list a.button');
            const inputRect = input.getBoundingClientRect();
            const buttonRect = button.getBoundingClientRect();
            const addRect = add.getBoundingClientRect();
            return {
              innerWidth: window.innerWidth,
              viewportWidth: document.documentElement.clientWidth,
              documentWidth: document.documentElement.scrollWidth,
              inputWidth: inputRect.width,
              inputTop: inputRect.top,
              inputRight: inputRect.right,
              buttonTop: buttonRect.top,
              buttonLeft: buttonRect.left,
              buttonRight: buttonRect.right,
              buttonHeight: buttonRect.height,
              buttonContentFits: button.scrollWidth <= button.clientWidth,
              formBottom: form.getBoundingClientRect().bottom,
              addTop: addRect.top,
              addRight: addRect.right,
              addHeight: addRect.height,
              addContentFits: add.scrollWidth <= add.clientWidth
            };
            """
        )

        assert metrics["innerWidth"] == width
        assert metrics["documentWidth"] <= metrics["viewportWidth"]
        assert metrics["inputWidth"] >= 120
        assert abs(metrics["inputTop"] - metrics["buttonTop"]) < 2
        assert metrics["inputRight"] <= metrics["buttonLeft"]
        assert metrics["buttonRight"] <= metrics["viewportWidth"]
        assert metrics["buttonHeight"] >= 44
        assert metrics["buttonContentFits"]
        assert metrics["addTop"] >= metrics["formBottom"]
        assert metrics["addRight"] <= metrics["viewportWidth"]
        assert metrics["addHeight"] >= 44
        assert metrics["addContentFits"]
        firefox_driver.switch_to.default_content()

    firefox_driver.set_window_size(1280, 800)
    firefox_driver.get(f"{_base_url()}/cars/")
    assert firefox_driver.execute_script(
        """
        const form = document.querySelector('.page-actions--car-list .car-search-form').getBoundingClientRect();
        const add = document.querySelector('.page-actions--car-list a.button').getBoundingClientRect();
        return Math.abs(form.top - add.top) < 2 && form.right <= add.left;
        """
    )

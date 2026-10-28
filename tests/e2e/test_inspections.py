import os
import uuid
from collections.abc import Iterator
from urllib.parse import urljoin

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

scenarios("features/inspections.feature")


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + b"\x00" * 32
PDF_SIGNATURE = b"%PDF-1.4\n" + b"\x00" * 32


@pytest.fixture
def firefox_driver(tmp_path) -> Iterator[webdriver.Firefox]:
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


@pytest.fixture
def inspection_files(tmp_path) -> dict[str, str]:
    photo = tmp_path / "inspection-photo.png"
    document = tmp_path / "inspection-document.pdf"
    photo.write_bytes(PNG_SIGNATURE)
    document.write_bytes(PDF_SIGNATURE)
    return {"photo": str(photo), "document": str(document)}


@pytest.fixture
def inspection_state() -> dict[str, str]:
    return {}


def _base_url() -> str:
    return os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _url(path: str) -> str:
    return urljoin(_base_url(), path)


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _wait(driver: webdriver.Firefox) -> WebDriverWait:
    return WebDriverWait(driver, 10)


@given("a running application server for inspections")
def running_server_for_inspections():
    pass


@given(parsers.parse('an inspection owner "{email}" is signed in'))
def inspection_owner_signed_in(firefox_driver: webdriver.Firefox, inspection_state: dict[str, str], email: str):
    inspection_state["email"] = email
    firefox_driver.get(_url(f"/set-test-session/?email={email}&next=/fleets/add/"))
    _wait(firefox_driver).until(ec.url_contains("/fleets/add/"))


@given(parsers.parse('an inspection fleet "{fleet_name}" exists'))
def create_inspection_fleet(
    firefox_driver: webdriver.Firefox,
    inspection_state: dict[str, str],
    fleet_name: str,
):
    unique_name = _unique(fleet_name)
    inspection_state["fleet_name"] = unique_name
    firefox_driver.get(_url("/fleets/add/"))
    name_input = _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, "name")))
    name_input.send_keys(unique_name)
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_contains("/fleets/"))


@given(parsers.parse('an inspection car "{car_name}" exists'))
def create_inspection_car(
    firefox_driver: webdriver.Firefox,
    inspection_state: dict[str, str],
    car_name: str,
):
    unique_name = _unique(car_name)
    inspection_state["car_name"] = unique_name
    firefox_driver.get(_url("/cars/add/"))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, "make")))
    firefox_driver.find_element(By.NAME, "usual_name").send_keys(unique_name)
    firefox_driver.find_element(By.NAME, "make").send_keys("Toyota")
    firefox_driver.find_element(By.NAME, "model").send_keys("Yaris")
    firefox_driver.find_element(By.NAME, "colour").send_keys("Blue")
    fleet_select = firefox_driver.find_element(By.NAME, "fleet")
    for option in fleet_select.find_elements(By.TAG_NAME, "option"):
        if inspection_state["fleet_name"] in option.text:
            option.click()
            break
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_contains("/cars/"))
    inspection_state["car_url"] = firefox_driver.current_url
    inspection_state["car_pk"] = inspection_state["car_url"].rstrip("/").rsplit("/", 1)[-1]


@when(parsers.parse('they create an inspection at "{inspected_at}" with notes "{notes}"'))
def create_inspection(
    firefox_driver: webdriver.Firefox,
    inspection_state: dict[str, str],
    inspected_at: str,
    notes: str,
):
    firefox_driver.get(_url(f"/cars/{inspection_state['car_pk']}/inspections/add/"))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, "inspected_at")))
    firefox_driver.execute_script(
        """
        const input = document.querySelector('input[name="inspected_at"]');
        input.value = arguments[0];
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        inspected_at,
    )
    firefox_driver.find_element(By.NAME, "notes").send_keys(notes)
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="latest-inspection"]')))


@when("they attach an inspection photo and document")
def attach_inspection_evidence(firefox_driver: webdriver.Firefox, inspection_files: dict[str, str]):
    car_pk = inspection_state_from_url(firefox_driver)
    firefox_driver.get(_url(f"/cars/{car_pk}/"))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="latest-inspection"]')))
    firefox_driver.find_element(
        By.CSS_SELECTOR,
        '[data-testid="latest-inspection"] a[href*="/inspections/"][href*="/edit/"]',
    ).click()
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, "inspected_at")))
    firefox_driver.find_element(By.NAME, "notes").clear()
    firefox_driver.find_element(By.NAME, "notes").send_keys("LATEST_INSPECTION_FINDINGS_WITH_EVIDENCE")
    firefox_driver.find_element(By.CSS_SELECTOR, 'input[name="attachments"]').send_keys(
        f"{inspection_files['photo']}\n{inspection_files['document']}"
    )
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="latest-inspection"]')))


def inspection_state_from_url(firefox_driver: webdriver.Firefox) -> str:
    return firefox_driver.current_url.rstrip("/").split("/cars/", 1)[1].split("/", 1)[0]


@then("the vehicle page shows only the latest inspection")
def vehicle_page_shows_only_latest(firefox_driver: webdriver.Firefox):
    source = firefox_driver.page_source
    assert "LATEST_INSPECTION_FINDINGS_WITH_EVIDENCE" in source
    assert "OLDER_INSPECTION_FINDINGS" not in source

    latest_section = firefox_driver.find_element(By.CSS_SELECTOR, '[data-testid="latest-inspection"]')
    assert "LATEST_INSPECTION_FINDINGS_WITH_EVIDENCE" in latest_section.text
    assert "OLDER_INSPECTION_FINDINGS" not in latest_section.text


@then("the vehicle page shows the inspection evidence")
def vehicle_page_shows_evidence(firefox_driver: webdriver.Firefox):
    attachments = firefox_driver.find_element(By.CSS_SELECTOR, '[data-testid="inspection-attachments"]')
    assert "inspection-photo.png" in attachments.text
    assert "inspection-document.pdf" in attachments.text


@when("they open the inspection history")
def open_inspection_history(firefox_driver: webdriver.Firefox):
    history_links = firefox_driver.find_elements(By.CSS_SELECTOR, '[data-testid="inspection-history-link"]')
    if history_links:
        history_links[0].click()
    else:
        car_pk = inspection_state_from_url(firefox_driver)
        firefox_driver.get(_url(f"/cars/{car_pk}/inspections/"))
    _wait(firefox_driver).until(ec.url_contains("/inspections/"))


@then("the inspection history shows both inspections")
def inspection_history_shows_both(firefox_driver: webdriver.Firefox):
    items = firefox_driver.find_elements(By.CSS_SELECTOR, '[data-testid="inspection-history-item"]')
    assert len(items) == 2
    source = firefox_driver.page_source
    assert "OLDER_INSPECTION_FINDINGS" in source
    assert "LATEST_INSPECTION_FINDINGS_WITH_EVIDENCE" in source


@then("the inspection history shows the inspection evidence")
def inspection_history_shows_evidence(firefox_driver: webdriver.Firefox):
    attachments = firefox_driver.find_elements(By.CSS_SELECTOR, '[data-testid="inspection-attachments"]')
    assert attachments
    source = firefox_driver.page_source
    assert "inspection-photo.png" in source
    assert "inspection-document.pdf" in source


@when(parsers.parse('they add recommended work "{title}" planned for "{planned_date}"'))
def add_recommended_work(firefox_driver: webdriver.Firefox, title: str, planned_date: str):
    car_pk = inspection_state_from_url(firefox_driver)
    firefox_driver.get(_url(f"/cars/{car_pk}/"))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="latest-inspection"]')))
    firefox_driver.find_element(By.CSS_SELECTOR, '[data-testid="latest-inspection"] a[href*="inspection="]').click()
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, "title")))
    firefox_driver.find_element(By.NAME, "title").send_keys(title)
    firefox_driver.execute_script(
        """
        const input = document.querySelector('input[name="planned_date"]');
        input.value = arguments[0];
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        planned_date,
    )
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="latest-inspection"]')))


@then("the latest inspection shows the recommended work")
def latest_inspection_shows_recommended_work(firefox_driver: webdriver.Firefox):
    latest_section = firefox_driver.find_element(By.CSS_SELECTOR, '[data-testid="latest-inspection"]')
    assert "Replace brake pads" in latest_section.text
    assert "Nov 1, 2026" in latest_section.text

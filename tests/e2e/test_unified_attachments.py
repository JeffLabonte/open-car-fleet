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

scenarios('features/unified_attachments.feature')

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\x0dIHDR' + b'\x00' * 32
PDF_SIGNATURE = b'%PDF-1.4\n' + b'\x00' * 32
EXE_PAYLOAD = b'MZ not really an executable, but the extension is not allowed anyway'


@pytest.fixture(scope='module')
def sample_files(tmp_path_factory) -> dict[str, str]:
    directory = tmp_path_factory.mktemp('attachments')
    paths = {
        'photo': directory / 'brake-photo.png',
        'pdf': directory / 'manual.pdf',
        'unsafe': directory / 'payload.exe',
    }
    paths['photo'].write_bytes(PNG_SIGNATURE)
    paths['pdf'].write_bytes(PDF_SIGNATURE)
    paths['unsafe'].write_bytes(EXE_PAYLOAD)
    return {name: str(path) for name, path in paths.items()}


@pytest.fixture
def firefox_driver() -> Iterator[webdriver.Firefox]:
    options = Options()
    options.add_argument('-headless')
    firefox_binary = os.environ.get('FIREFOX_BIN')
    if firefox_binary:
        options.binary_location = firefox_binary

    driver = webdriver.Firefox(options=options)
    driver.set_page_load_timeout(30)
    try:
        yield driver
    finally:
        driver.quit()


def _base_url() -> str:
    return os.environ.get('E2E_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')


def _url(path: str) -> str:
    return urljoin(_base_url(), path)


@pytest.fixture
def state() -> dict[str, str]:
    return {}


def _unique(prefix: str) -> str:
    return f'{prefix} {uuid.uuid4().hex[:8]}'


def _wait(driver: webdriver.Firefox) -> WebDriverWait:
    return WebDriverWait(driver, 10)


@given('a running application server')
def running_server():
    # The E2E suite assumes `make test-e2e` starts the Django server externally.
    pass


@given(parsers.parse('"{email}" is signed in'))
def sign_in(firefox_driver: webdriver.Firefox, state: dict[str, str], email: str):
    state['email'] = email
    firefox_driver.get(_url(f'/set-test-session/?email={email}&next=/garages/add/'))
    _wait(firefox_driver).until(ec.url_contains('/garages/add/'))


@given(parsers.parse('a fleet "{fleet_name}" owned by "{email}"'))
def create_fleet(firefox_driver: webdriver.Firefox, state: dict[str, str], fleet_name: str, email: str):
    unique_name = _unique(fleet_name)
    state['fleet_name'] = unique_name
    firefox_driver.get(_url('/garages/add/'))
    name_input = _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, 'name')))
    name_input.send_keys(unique_name)
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_contains('/garages/'))
    state['garage_url'] = firefox_driver.current_url


@given(parsers.parse('a car "{car_name}" exists in "{fleet_name}"'))
def create_car(firefox_driver: webdriver.Firefox, state: dict[str, str], car_name: str, fleet_name: str):
    unique_name = _unique(car_name)
    state['car_name'] = unique_name
    firefox_driver.get(_url('/cars/add/'))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, 'make')))
    firefox_driver.find_element(By.NAME, 'make').send_keys('Toyota')
    firefox_driver.find_element(By.NAME, 'model').send_keys('Yaris')
    firefox_driver.find_element(By.NAME, 'colour').send_keys('Blue')
    garage_select = firefox_driver.find_element(By.NAME, 'garage')
    for option in garage_select.find_elements(By.TAG_NAME, 'option'):
        if state['fleet_name'] in option.text:
            option.click()
            break
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_contains('/cars/'))
    state['car_url'] = firefox_driver.current_url


@when('they open the maintenance report form for the current car')
def open_report_form(firefox_driver: webdriver.Firefox, state: dict[str, str]):
    firefox_driver.get(_url(f"/cars/{state['car_url'].rstrip('/').rsplit('/', 1)[-1]}/reports/add/"))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, 'job_name')))


@when(parsers.parse('they fill the report with job "{job_name}"'))
def fill_report(firefox_driver: webdriver.Firefox, state: dict[str, str], job_name: str):
    unique_job = _unique(job_name)
    state['job_name'] = unique_job
    firefox_driver.find_element(By.NAME, 'job_name').send_keys(unique_job)
    # Native date inputs ignore send_keys; set the value directly instead.
    firefox_driver.execute_script(
        "const input = document.querySelector('input[name=\"date_done\"]');"
        "input.value = '2026-09-12';"
    )


@when('they attach the photo file to the report form')
def attach_photo(firefox_driver: webdriver.Firefox, sample_files: dict[str, str]):
    firefox_driver.find_element(By.CSS_SELECTOR, 'input[name="attachments"]').send_keys(sample_files['photo'])


@when('they attach the unsafe file to the report form')
def attach_unsafe(firefox_driver: webdriver.Firefox, sample_files: dict[str, str]):
    firefox_driver.find_element(By.CSS_SELECTOR, 'input[name="attachments"]').send_keys(sample_files['unsafe'])


@when('they add the external link to the report form')
def add_external_link(firefox_driver: webdriver.Firefox):
    firefox_driver.find_element(By.NAME, 'external_links').send_keys('https://example.com/invoice-link')


@when('they submit the report form')
def submit_report(firefox_driver: webdriver.Firefox):
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_contains('/cars/'))


@then('the attachment upload section is the last form field')
def attachment_section_is_last(firefox_driver: webdriver.Firefox):
    result = firefox_driver.execute_script(
        """
        const section = document.querySelector('[data-testid="attachment-upload-section"]');
        if (!section) { return {found: false}; }
        const form = section.closest('form');
        let node = section.nextElementSibling;
        while (node) {
            if (node.classList.contains('field') && !node.classList.contains('is-grouped')) {
                return {found: true, last: false};
            }
            node = node.nextElementSibling;
        }
        return {found: true, last: true};
        """
    )
    assert result['found'], 'attachment upload section is missing from the form'
    assert result['last'], 'attachment upload section is not the last form field'


@then('the external links field renders before the attachment section')
def external_links_before_attachments(firefox_driver: webdriver.Firefox):
    result = firefox_driver.execute_script(
        """
        const section = document.querySelector('[data-testid="attachment-upload-section"]');
        const links = document.querySelector('textarea[name="external_links"]');
        if (!section || !links) { return false; }
        return section.compareDocumentPosition(links) & Node.DOCUMENT_POSITION_PRECEDING;
        """
    )
    assert result, 'external links field must render before the attachment section'


@then('the car detail page lists the attachment')
def car_detail_lists_attachment(firefox_driver: webdriver.Firefox):
    _wait(firefox_driver).until(ec.presence_of_element_located(
        (By.CSS_SELECTOR, '[data-testid="report-attachments"]')
    ))
    source = firefox_driver.page_source
    assert 'brake-photo.png' in source
    assert firefox_driver.find_elements(By.CSS_SELECTOR, '[data-testid="report-attachments"]')


@then('the car detail page lists the external link')
def car_detail_lists_external_link(firefox_driver: webdriver.Firefox):
    source = firefox_driver.page_source
    assert 'https://example.com/invoice-link' in source
    assert firefox_driver.find_elements(By.CSS_SELECTOR, '[data-testid="report-attachments"]')


@then('an attachment validation error is displayed')
def attachment_validation_error(firefox_driver: webdriver.Firefox):
    _wait(firefox_driver).until(ec.presence_of_element_located(
        (By.CSS_SELECTOR, '.help.is-danger')
    ))
    source = firefox_driver.page_source
    assert 'Unsupported attachment file type.' in source


@then('the browser stays on the report form')
def stays_on_report_form(firefox_driver: webdriver.Firefox, state: dict[str, str]):
    assert '/reports/add/' in firefox_driver.current_url


@when(parsers.parse('they create a car document titled "{title}"'))
def create_car_document(firefox_driver: webdriver.Firefox, state: dict[str, str], title: str):
    car_pk = state['car_url'].rstrip('/').rsplit('/', 1)[-1]
    firefox_driver.get(_url(f'/cars/{car_pk}/docs/add/'))
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, 'title')))
    firefox_driver.find_element(By.NAME, 'title').send_keys(_unique(title))


@when('they attach the pdf file to the car document form')
def attach_pdf_to_doc(firefox_driver: webdriver.Firefox, sample_files: dict[str, str]):
    firefox_driver.find_element(By.CSS_SELECTOR, 'input[name="attachments"]').send_keys(sample_files['pdf'])


@when('they submit the car document form')
def submit_doc(firefox_driver: webdriver.Firefox, state: dict[str, str]):
    doc_list_url = state['car_url'].rstrip('/') + '/docs/'
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_to_be(doc_list_url))


@then('the car document list shows the attachment')
def doc_list_shows_attachment(firefox_driver: webdriver.Firefox):
    _wait(firefox_driver).until(ec.presence_of_element_located(
        (By.CSS_SELECTOR, '[data-testid="current-attachment"], a[href*="/attachments/"]')
    ))
    assert 'manual.pdf' in firefox_driver.page_source


@when(parsers.parse('they create a known shop named "{shop_name}"'))
def create_known_shop(firefox_driver: webdriver.Firefox, state: dict[str, str], shop_name: str):
    firefox_driver.get(_url('/shops/add/'))
    name_input = _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, 'name')))
    unique_name = _unique(shop_name)
    state['shop_name'] = unique_name
    name_input.send_keys(unique_name)
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_contains('/shops/'))
    state['shop_url'] = firefox_driver.current_url


@when('they open the add proof form for that shop')
def open_proof_form(firefox_driver: webdriver.Firefox):
    firefox_driver.find_element(By.LINK_TEXT, 'Add proof').click()
    _wait(firefox_driver).until(ec.presence_of_element_located((By.NAME, 'title')))


@when(parsers.parse('they fill the proof with title "{title}"'))
def fill_proof(firefox_driver: webdriver.Firefox, title: str):
    firefox_driver.find_element(By.NAME, 'title').send_keys(_unique(title))


@when('they attach the pdf file to the proof form')
def attach_pdf_to_proof(firefox_driver: webdriver.Firefox, sample_files: dict[str, str]):
    firefox_driver.find_element(By.CSS_SELECTOR, 'input[name="attachments"]').send_keys(sample_files['pdf'])


@when('they submit the proof form')
def submit_proof(firefox_driver: webdriver.Firefox, state: dict[str, str]):
    shop_detail_url = state['shop_url']
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()
    _wait(firefox_driver).until(ec.url_to_be(shop_detail_url))


@then('the shop detail page lists the proof attachment')
def shop_detail_lists_proof_attachment(firefox_driver: webdriver.Firefox):
    _wait(firefox_driver).until(ec.presence_of_element_located(
        (By.CSS_SELECTOR, '[data-testid="proof-attachments"]')
    ))
    assert 'manual.pdf' in firefox_driver.page_source

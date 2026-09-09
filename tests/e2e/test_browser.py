from collections.abc import Iterator
import os
from urllib.parse import urlparse

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options


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


def test_anonymous_protected_page_redirects_to_login(firefox_driver: webdriver.Firefox) -> None:
    firefox_driver.get(f'{_base_url()}/cars/')

    parsed_url = urlparse(firefox_driver.current_url)
    assert parsed_url.path == '/login/'
    assert parsed_url.query.startswith('next=')


def test_login_page_renders_in_firefox(firefox_driver: webdriver.Firefox) -> None:
    firefox_driver.get(f'{_base_url()}/login/')

    headings = [element.text for element in firefox_driver.find_elements(By.TAG_NAME, 'h1')]
    assert 'Sign in' in headings
    assert 'Missing HANKO_API_URL' in firefox_driver.find_element(By.ID, 'hanko-auth-container').text

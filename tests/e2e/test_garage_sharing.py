import os
from collections.abc import Iterator
from urllib.parse import urljoin

import pytest
from pytest_bdd import given, scenarios, then, when
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait


scenarios('features/garage_sharing.feature')


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


@given('a running application server')
def running_server():
    # The E2E suite assumes `make test-e2e` starts the Django server externally.
    pass


@given('a fleet owner "owner@example.com"')
def fleet_owner_owner():
    pass


@given('a fleet "Shared Fleet" owned by "owner@example.com"')
def shared_fleet():
    pass


@given('"owner@example.com" is signed in')
def sign_in_owner(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=owner@example.com'))


@given('a user "stranger@example.com"')
def user_stranger():
    pass


@given('"stranger@example.com" is signed in')
def sign_in_stranger(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=stranger@example.com'))


@given('"viewer@example.com" is a viewer of "Shared Fleet"')
def viewer_of_shared_fleet():
    pass


@given('"admin@example.com" is an admin of "Shared Fleet"')
def admin_of_shared_fleet():
    pass


@given('a car "Daily Driver" exists in "Shared Fleet"')
def daily_driver_car():
    pass


@given('"viewer@example.com" is signed in')
def sign_in_viewer(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=viewer@example.com'))


@given('"admin@example.com" is signed in')
def sign_in_admin(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=admin@example.com'))


@when('they visit the share page for "Shared Fleet"')
def visit_share_page(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/garages/shared-fleet-uuid/share/'))


@when('they invite "viewer@example.com" with role "Viewer"')
def invite_viewer(firefox_driver: webdriver.Firefox):
    wait = WebDriverWait(firefox_driver, 10)
    email_field = wait.until(ec.presence_of_element_located((By.NAME, 'invited_email')))
    email_field.send_keys('viewer@example.com')
    role_select = firefox_driver.find_element(By.NAME, 'role')
    role_select.find_element(By.CSS_SELECTOR, f'option[value="viewer"]').click()
    firefox_driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()


@then('a pending invitation exists for "viewer@example.com"')
def pending_invitation_exists(firefox_driver: webdriver.Firefox):
    assert 'Pending invitations' in firefox_driver.page_source
    assert 'viewer@example.com' in firefox_driver.page_source


@then('the invitation role is "Viewer"')
def invitation_role_is_viewer(firefox_driver: webdriver.Firefox):
    assert 'Viewer' in firefox_driver.page_source


@then('they are redirected away without accessing member management')
def redirected_from_share_page(firefox_driver: webdriver.Firefox):
    assert firefox_driver.current_url != _url('/garages/shared-fleet-uuid/share/')
    assert 'Send invitation' not in firefox_driver.page_source


@when('they visit the fleet detail page for "Shared Fleet"')
def visit_fleet_detail(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/garages/shared-fleet-uuid/'))


@then('they see "Daily Driver"')
def see_daily_driver(firefox_driver: webdriver.Firefox):
    assert 'Daily Driver' in firefox_driver.page_source


@then('they do not see an "Add car" button')
def no_add_car_button(firefox_driver: webdriver.Firefox):
    assert 'Add car' not in firefox_driver.page_source


@when('they change the role of "viewer@example.com" to "Mechanic"')
def change_role_to_mechanic(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/garages/shared-fleet-uuid/members/'))
    wait = WebDriverWait(firefox_driver, 10)
    row = wait.until(
        ec.presence_of_element_located((By.XPATH, "//tr[contains(., 'viewer@example.com')]"))
    )
    select = row.find_element(By.NAME, 'role')
    select.find_element(By.CSS_SELECTOR, 'option[value="mechanic"]').click()
    row.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()


@then('"viewer@example.com" has role "Mechanic" in "Shared Fleet"')
def viewer_role_is_mechanic(firefox_driver: webdriver.Firefox):
    assert 'viewer@example.com' in firefox_driver.page_source
    assert 'Mechanic' in firefox_driver.page_source


@when('they attempt to change the role of "viewer@example.com" to "Owner"')
def attempt_promote_to_owner(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/garages/shared-fleet-uuid/members/'))
    wait = WebDriverWait(firefox_driver, 10)
    row = wait.until(
        ec.presence_of_element_located((By.XPATH, "//tr[contains(., 'viewer@example.com')]"))
    )
    select = row.find_element(By.NAME, 'role')
    options = [opt.get_attribute('value') for opt in select.find_elements(By.TAG_NAME, 'option')]
    assert 'owner' not in options


@then('"viewer@example.com" still has role "Viewer" in "Shared Fleet"')
def viewer_role_unchanged(firefox_driver: webdriver.Firefox):
    assert 'viewer@example.com' in firefox_driver.page_source
    assert 'Viewer' in firefox_driver.page_source


@when('they remove "viewer@example.com" from "Shared Fleet"')
def remove_viewer(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/garages/shared-fleet-uuid/members/'))
    wait = WebDriverWait(firefox_driver, 10)
    row = wait.until(
        ec.presence_of_element_located((By.XPATH, "//tr[contains(., 'viewer@example.com')]"))
    )
    row.find_element(By.CSS_SELECTOR, 'button[formaction*="remove"]').click()


@then('"viewer@example.com" is no longer a member of "Shared Fleet"')
def viewer_removed(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/garages/shared-fleet-uuid/members/'))
    assert 'viewer@example.com' not in firefox_driver.page_source


@then('they see a not found page')
def see_not_found(firefox_driver: webdriver.Firefox):
    assert firefox_driver.title.lower() in {'not found', 'page not found'} or '404' in firefox_driver.page_source

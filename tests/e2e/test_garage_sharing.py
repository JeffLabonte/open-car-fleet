import os
from urllib.parse import urljoin

import pytest
from pytest_bdd import given, scenarios, then, when
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from shop.auth import sync_hanko_user
from shop.models import Car, Garage, GarageMembership
from shop.models.user import ShopUser


scenarios('features/garage_sharing.feature')

FLEET_NAME = 'Shared Fleet'


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


def _sync_user(email: str):
    return sync_hanko_user(
        hanko_id=f'e2e-{email}',
        email=email,
        username=email.split('@')[0],
        provider='local',
    )


def _ensure_member(garage: Garage, email: str, role: str, blocker) -> None:
    with blocker.unblock():
        user = _sync_user(email)
        membership, _ = GarageMembership.objects.get_or_create(
            garage=garage,
            user=user,
            defaults={'role': role},
        )
        if membership.role != role:
            membership.role = role
            membership.save(update_fields=['role', 'updated_at'])


@given('a running application server')
def running_server():
    pass


@given('a fleet owner "owner@example.com"')
def fleet_owner_owner():
    pass


@given('a fleet "Shared Fleet" owned by "owner@example.com"', target_fixture='shared_garage')
def shared_fleet(django_db_blocker) -> Garage:
    with django_db_blocker.unblock():
        owner = _sync_user('owner@example.com')
        garage, _ = Garage.objects.get_or_create(
            name=FLEET_NAME,
            defaults={'created_by': owner},
        )
        GarageMembership.objects.get_or_create(
            garage=garage,
            user=owner,
            defaults={'role': GarageMembership.ROLE_OWNER},
        )
        GarageMembership.objects.filter(garage=garage).exclude(user=owner).delete()
        return garage


@given('"viewer@example.com" is a viewer of "Shared Fleet"')
def viewer_of_shared_fleet(shared_garage: Garage, django_db_blocker):
    _ensure_member(shared_garage, 'viewer@example.com', GarageMembership.ROLE_VIEWER, django_db_blocker)


@given('"admin@example.com" is an admin of "Shared Fleet"')
def admin_of_shared_fleet(shared_garage: Garage, django_db_blocker):
    _ensure_member(shared_garage, 'admin@example.com', GarageMembership.ROLE_ADMIN, django_db_blocker)


@given('a car "Daily Driver" exists in "Shared Fleet"')
def daily_driver_car(shared_garage: Garage, django_db_blocker):
    with django_db_blocker.unblock():
        Car.objects.get_or_create(
            garage=shared_garage,
            usual_name='Daily Driver',
            defaults={'make': 'Toyota', 'model': 'Corolla'},
        )


@given('"viewer@example.com" is signed in')
def sign_in_viewer(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=viewer@example.com'))


@given('"admin@example.com" is signed in')
def sign_in_admin(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=admin@example.com'))


@given('"owner@example.com" is signed in')
def sign_in_owner(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=owner@example.com'))


@given('a user "stranger@example.com"')
def user_stranger():
    pass


@given('"stranger@example.com" is signed in')
def sign_in_stranger(firefox_driver: webdriver.Firefox):
    firefox_driver.get(_url('/set-test-session/?email=stranger@example.com'))


@when('they visit the share page for "Shared Fleet"')
def visit_share_page(firefox_driver: webdriver.Firefox, shared_garage: Garage):
    firefox_driver.get(_url(f'/garages/{shared_garage.pk}/share/'))


@when('they invite "viewer@example.com" with role "Viewer"')
def invite_viewer(firefox_driver: webdriver.Firefox):
    wait = WebDriverWait(firefox_driver, 10)
    email_field = wait.until(ec.presence_of_element_located((By.NAME, 'invited_email')))
    email_field.send_keys('viewer@example.com')
    role_select = firefox_driver.find_element(By.NAME, 'role')
    role_select.find_element(By.CSS_SELECTOR, 'option[value="viewer"]').click()
    firefox_driver.find_element(By.CSS_SELECTOR, '#main-content form button[type="submit"]').click()


@then('a pending invitation exists for "viewer@example.com"')
def pending_invitation_exists(firefox_driver: webdriver.Firefox):
    assert 'Pending invitations' in firefox_driver.page_source
    assert 'viewer@example.com' in firefox_driver.page_source


@then('the invitation role is "Viewer"')
def invitation_role_is_viewer(firefox_driver: webdriver.Firefox):
    assert 'Viewer' in firefox_driver.page_source


@then('they are redirected away without accessing member management')
def redirected_from_share_page(firefox_driver: webdriver.Firefox):
    assert '/share/' not in firefox_driver.current_url
    assert 'Send invitation' not in firefox_driver.page_source


@when('they visit the fleet detail page for "Shared Fleet"')
def visit_fleet_detail(firefox_driver: webdriver.Firefox, shared_garage: Garage):
    firefox_driver.get(_url(f'/garages/{shared_garage.pk}/'))


@then('they see "Daily Driver"')
def see_daily_driver(firefox_driver: webdriver.Firefox):
    assert 'Daily Driver' in firefox_driver.page_source


@then('they do not see an "Add car" button')
def no_add_car_button(firefox_driver: webdriver.Firefox):
    assert 'Add car' not in firefox_driver.page_source


@when('they change the role of "viewer@example.com" to "Mechanic"')
def change_role_to_mechanic(firefox_driver: webdriver.Firefox, shared_garage: Garage):
    firefox_driver.get(_url(f'/garages/{shared_garage.pk}/members/'))
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
def attempt_promote_to_owner(firefox_driver: webdriver.Firefox, shared_garage: Garage):
    firefox_driver.get(_url(f'/garages/{shared_garage.pk}/members/'))
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
def remove_viewer(firefox_driver: webdriver.Firefox, shared_garage: Garage):
    firefox_driver.get(_url(f'/garages/{shared_garage.pk}/members/'))
    wait = WebDriverWait(firefox_driver, 10)
    row = wait.until(
        ec.presence_of_element_located((By.XPATH, "//tr[contains(., 'viewer@example.com')]"))
    )
    row.find_element(By.CSS_SELECTOR, 'button[formaction*="remove"]').click()


@then('"viewer@example.com" is no longer a member of "Shared Fleet"')
def viewer_removed(firefox_driver: webdriver.Firefox, shared_garage: Garage):
    firefox_driver.get(_url(f'/garages/{shared_garage.pk}/members/'))
    assert 'viewer@example.com' not in firefox_driver.page_source


@then('they see a not found page')
def see_not_found(firefox_driver: webdriver.Firefox):
    assert firefox_driver.title.lower() in {'not found', 'page not found'} or '404' in firefox_driver.page_source
